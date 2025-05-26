"""
Moderation Module for HacksterBot.

This module provides comprehensive content moderation capabilities including:
- Text and image content moderation
- URL safety checking
- Automated muting system
- Violation tracking
- AI-powered review system
"""
import logging
import discord
from discord.ext import commands, tasks
from typing import List, Optional, Dict, Any

from core.module_base import ModuleBase
from core.exceptions import ModuleError
from .services.content_moderator import ContentModerator
from .services.url_safety import URLSafetyChecker
from .services.moderation_queue import start_moderation_queue, get_moderation_queue
from .services.moderation_db import ModerationDB
from .services.community_guidelines import format_mute_reason, get_guidelines_for_violations
from .agents.moderation_review import agent_moderation_review, review_flagged_content
from modules.ai.services.ai_select import get_agent

logger = logging.getLogger(__name__)


class ModerationModule(ModuleBase):
    """Content moderation module with AI-powered review system."""
    
    def __init__(self, bot, config):
        """
        Initialize the moderation module.
        
        Args:
            bot: The Discord bot instance
            config: Configuration object
        """
        super().__init__(bot, config)
        self.name = "moderation"
        self.description = "Content moderation with AI review system"
        
        # Initialize services
        self.content_moderator = None
        self.url_safety_checker = None
        self.moderation_db = None
        self.review_agent = None
        self.backup_review_agent = None
        
    async def setup(self):
        """Set up the moderation module."""
        try:
            if not self.config.moderation.enabled:
                logger.info("Moderation module is disabled")
                return
                
            # Initialize content moderator
            self.content_moderator = ContentModerator()
            
            # Initialize URL safety checker
            if self.config.url_safety.enabled:
                self.url_safety_checker = URLSafetyChecker(self.config)
            
            # Initialize database
            self.moderation_db = ModerationDB()
            
            # Start moderation queue
            await start_moderation_queue(self.config)
            
            # Initialize AI review agents if enabled
            if self.config.moderation.enabled:
                await self._setup_review_agents()
            
            # Start background tasks
            self.check_expired_mutes.start()
            
            # Register event listeners
            self.bot.add_listener(self.on_message, 'on_message')
            self.bot.add_listener(self.on_member_join, 'on_member_join')
            
            logger.info("Moderation module setup completed")
            
        except Exception as e:
            logger.error(f"Failed to setup moderation module: {e}")
            raise ModuleError(f"Moderation module setup failed: {e}")
    
    async def teardown(self):
        """Clean up the moderation module."""
        try:
            # Stop background tasks
            if self.check_expired_mutes.is_running():
                self.check_expired_mutes.cancel()
                
            # Close database connections
            if self.moderation_db:
                self.moderation_db.close()
                
            # Remove event listeners
            self.bot.remove_listener(self.on_message, 'on_message')
            self.bot.remove_listener(self.on_member_join, 'on_member_join')
            
            logger.info("Moderation module teardown completed")
            
        except Exception as e:
            logger.error(f"Error during moderation module teardown: {e}")
    
    async def _setup_review_agents(self):
        """Set up AI review agents for moderation."""
        try:
            logger.info("開始設定 AI 複審代理")
            
            # Set up primary review agent
            if self.config.moderation.review_ai_service and self.config.moderation.review_model:
                logger.info(f"設定主要複審代理: {self.config.moderation.review_ai_service} / {self.config.moderation.review_model}")
                try:
                    primary_model = await get_agent(
                        self.config.moderation.review_ai_service,
                        self.config.moderation.review_model
                    )
                    if primary_model:
                        self.review_agent = await agent_moderation_review(primary_model)
                        logger.info(f"主要複審代理設定成功: {self.config.moderation.review_ai_service}")
                    else:
                        logger.error(f"無法獲取主要 AI 代理: {self.config.moderation.review_ai_service}")
                except Exception as e:
                    logger.error(f"設定主要複審代理失敗: {e}")
            else:
                logger.warning("主要複審代理配置缺失，跳過設定")
            
            # Set up backup review agent
            if self.config.moderation.backup_review_ai_service and self.config.moderation.backup_review_model:
                logger.info(f"設定備用複審代理: {self.config.moderation.backup_review_ai_service} / {self.config.moderation.backup_review_model}")
                try:
                    backup_model = await get_agent(
                        self.config.moderation.backup_review_ai_service,
                        self.config.moderation.backup_review_model
                    )
                    if backup_model:
                        self.backup_review_agent = await agent_moderation_review(backup_model)
                        logger.info(f"備用複審代理設定成功: {self.config.moderation.backup_review_ai_service}")
                    else:
                        logger.error(f"無法獲取備用 AI 代理: {self.config.moderation.backup_review_ai_service}")
                except Exception as e:
                    logger.error(f"設定備用複審代理失敗: {e}")
            else:
                logger.info("備用複審代理配置缺失，跳過設定")
            
            # Log final status
            if self.review_agent or self.backup_review_agent:
                logger.info(f"AI 複審代理設定完成 - 主要代理: {'有' if self.review_agent else '無'}, 備用代理: {'有' if self.backup_review_agent else '無'}")
            else:
                logger.warning("所有 AI 複審代理設定失敗")
            
        except Exception as e:
            logger.error(f"設定複審代理時發生錯誤: {e}")
            import traceback
            logger.error(f"錯誤堆疊: {traceback.format_exc()}")
    
    async def on_message(self, message: discord.Message):
        """Handle message events for content moderation."""
        # Skip if not enabled or if message is from bot
        if not self.config.moderation.enabled or message.author.bot:
            return
            
        # Skip if author has bypass role
        if hasattr(message.author, 'roles'):
            for role in message.author.roles:
                if role.name in self.config.moderation.bypass_roles:
                    return
        
        try:
            await self._moderate_message(message)
        except Exception as e:
            logger.error(f"Error moderating message {message.id}: {e}")
    
    async def on_member_join(self, member: discord.Member):
        """Handle new member join events."""
        try:
            # Check if member has active timeout
            if self.moderation_db:
                active_mute = self.moderation_db.get_active_mute(member.id, member.guild.id)
                if active_mute:
                    # Reapply timeout if still active
                    import discord
                    expires_at_str = active_mute.get('expires_at')
                    if expires_at_str:
                        from datetime import datetime, timezone
                        expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                        if expires_at > discord.utils.utcnow():
                            await member.timeout(expires_at, reason="Reapplying active timeout for rejoining member")
                            logger.info(f"Reapplied timeout to rejoining member {member.id}")
        except Exception as e:
            logger.error(f"Error handling member join {member.id}: {e}")
    
    async def _moderate_message(self, message: discord.Message):
        """Moderate a single message using comprehensive content analysis."""
        # Get message author and content
        author = message.author
        text = message.content.strip()
        attachments = message.attachments
        
        logger.debug(f"開始審核訊息 {message.id}，作者: {author.display_name}")
        
        # Skip empty messages
        if not text and not attachments:
            return
        
        # Check for URLs if enabled
        url_check_result = None
        if self.url_safety_checker and text:
            try:
                urls = await self.url_safety_checker.extract_urls(text)
                
                if urls:
                    logger.info(f"檢查 {len(urls)} 個 URL 在訊息中，來自 {author.display_name}")
                    is_unsafe, url_results = await self.url_safety_checker.check_urls(urls)
                    
                    # Log the detailed results for each URL
                    for url, result in url_results.items():
                        is_url_unsafe = result.get('is_unsafe', False)
                        try:
                            if is_url_unsafe:
                                threat_types = result.get('threat_types', [])
                                severity = result.get('severity', 0)
                                redirected_to = result.get('redirected_to', None)
                                reason = result.get('reason', '')
                                
                                # Safe joining of threat types
                                threat_types_text = ""
                                try:
                                    threat_types_text = ', '.join(threat_types)
                                except Exception:
                                    threat_types_text = "[格式化錯誤]"
                                
                                # Format the log message with appropriate error handling
                                if redirected_to:
                                    logger.warning(
                                        f"URL安全檢查結果: {url} → {redirected_to} | 不安全: {is_url_unsafe} | "
                                        f"威脅類型: {threat_types_text} | 嚴重度: {severity}" + 
                                        (f" | 原因: {reason}" if reason else "")
                                    )
                                else:
                                    logger.warning(
                                        f"URL安全檢查結果: {url} | 不安全: {is_url_unsafe} | "
                                        f"威脅類型: {threat_types_text} | 嚴重度: {severity}" + 
                                        (f" | 原因: {reason}" if reason else "")
                                    )
                            else:
                                # 對於安全URL，記錄更簡潔的信息
                                message_text = result.get('message', '安全')
                                logger.info(f"URL安全檢查結果: {url} | 安全 | {message_text}")
                        except Exception as log_error:
                            # Fallback logging if any encoding or formatting errors occur
                            print(f"URL detail logging error: {str(log_error)}")
                            try:
                                logger.info(f"URL安全檢查結果: [URL記錄錯誤] | 狀態: {'不安全' if is_url_unsafe else '安全'}")
                            except:
                                logger.info("URL安全檢查結果記錄失敗")
                    
                    if is_unsafe:
                        # One or more URLs are unsafe
                        unsafe_urls = [url for url, result in url_results.items() if result.get('is_unsafe')]
                        threat_types = set()
                        max_severity = 0
                        reasons = set()
                        
                        for url, result in url_results.items():
                            if result.get('is_unsafe'):
                                # Collect all threat types
                                url_threats = result.get('threat_types', [])
                                for threat in url_threats:
                                    threat_types.add(threat)
                                
                                # Track maximum severity
                                severity = result.get('severity', 0)
                                max_severity = max(max_severity, severity)
                                
                                # Collect reasons if available
                                reason = result.get('reason')
                                if reason:
                                    reasons.add(reason)
                        
                        url_check_result = {
                            "is_unsafe": True,
                            "unsafe_urls": unsafe_urls,
                            "threat_types": list(threat_types),
                            "severity": max_severity,
                            "reasons": list(reasons) if reasons else None,
                            "results": url_results
                        }
                        
                        # Safely join reasons and threat types for logging
                        reason_text = ""
                        if reasons:
                            try:
                                reason_text = f" | 原因: {', '.join(reasons)}"
                            except Exception as e:
                                reason_text = " | 原因: [格式化錯誤]"
                                print(f"Reason formatting error: {str(e)}")
                        
                        threat_text = ""
                        if threat_types:
                            try:
                                threat_text = ', '.join(list(threat_types))
                            except Exception as e:
                                threat_text = "[格式化錯誤]"
                                print(f"Threat type formatting error: {str(e)}")
                        
                        # Safe URL count logging
                        try:
                            url_count = len(urls) if urls else 0
                            unsafe_count = len(unsafe_urls) if unsafe_urls else 0
                            logger.warning(
                                f"URL安全檢查摘要: 用戶 {author.display_name}的訊息中檢測到 "
                                f"{unsafe_count}/{url_count} 個不安全URL | 威脅類型: {threat_text}{reason_text}"
                            )
                        except Exception as log_error:
                            # Fallback for any logging errors
                            print(f"URL safety logging error: {str(log_error)}")
                            logger.warning("URL安全檢查檢測到不安全URL (詳細信息記錄失敗)")
                        
                        # If URL is unsafe, we'll continue with deletion and notification below
                        # after both URL and content checks are complete
                    else:
                        logger.info(f"URL安全檢查摘要: 用戶 {author.display_name}的訊息中的所有URL ({len(urls)}個) 都是安全的")
            except Exception as e:
                logger.error(f"URL安全檢查錯誤: {str(e)}")

        # Collect all content for moderation
        image_urls = []
        
        # Add attachment URLs
        for attachment in attachments:
            if attachment.content_type and attachment.content_type.startswith('image/'):
                image_urls.append(attachment.url)
        
        # Add image URLs from message content
        if text:
            # Extract image URLs from message content
            import re
            image_url_pattern = r'https?://[^\s<>"]+?\.(?:png|jpg|jpeg|gif|webp)'
            image_urls.extend(re.findall(image_url_pattern, text, re.IGNORECASE))
        
        # Skip if no content to moderate and no unsafe URLs
        if (not text and not image_urls) and not (url_check_result and url_check_result.get('is_unsafe')):
            return
        
        try:
            # Moderate content (text and images)
            is_flagged, results = await self.content_moderator.moderate_content(text, image_urls)
            
            # If either content is flagged or URLs are unsafe, take action
            if is_flagged or (url_check_result and url_check_result.get('is_unsafe')):
                # Save channel and author information before deletion
                channel = message.channel
                guild = message.guild
                
                                # Extract violation categories
                violation_categories = []
                
                # Add URL threat types to violation categories if applicable
                if url_check_result and url_check_result.get('is_unsafe'):
                    for threat_type in url_check_result.get('threat_types', []):
                        violation_category = threat_type.lower()  # Convert PHISHING to phishing, etc.
                        if violation_category not in violation_categories:
                            violation_categories.append(violation_category)
                
                # Check text violations
                if results.get("text_result") and results["text_result"].get("categories"):
                    categories = results["text_result"]["categories"]
                    for category, is_violated in categories.items():
                        if is_violated and category not in violation_categories:
                            violation_categories.append(category)
                
                # Check image violations
                for image_result in results.get("image_results", []):
                    if image_result.get("result") and image_result["result"].get("categories"):
                        categories = image_result["result"]["categories"]
                        for category, is_violated in categories.items():
                            if is_violated and category not in violation_categories:
                                violation_categories.append(category)
                
                logger.warning(f"訊息 {message.id} 被標記為潛在違規，類別: {violation_categories}")
                
                # If review is enabled and this is not a URL safety issue, check if the flagged content is a false positive
                review_result = None
                if (self.config.moderation.review_enabled and text and 
                    (self.review_agent or self.backup_review_agent) and 
                    not (url_check_result and url_check_result.get('is_unsafe'))):
                    from .agents.moderation_review import review_flagged_content
                    
                    try:
                        # Get message context (previous messages)
                        context = ""
                        if hasattr(message.channel, 'history'):
                            context_messages = []
                            async for msg in message.channel.history(limit=self.config.moderation.review_context_messages + 1):
                                if msg.id != message.id:
                                    context_messages.append(f"{msg.author.display_name}: {msg.content}")
                                    if len(context_messages) >= self.config.moderation.review_context_messages:
                                        break
                            
                            if context_messages:
                                context = "最近的訊息（從舊到新）：\n" + "\n".join(reversed(context_messages))
                        
                        # Review the flagged content using OpenAI mod + LLM
                        review_result = await review_flagged_content(
                            agent=self.review_agent,
                            content=text,
                            violation_categories=violation_categories,
                            context=context,
                            backup_agent=self.backup_review_agent
                        )
                        
                        print(f"[審核系統] 用戶 {author.display_name} 的訊息審核結果: {'非違規(誤判)' if not review_result['is_violation'] else '確認違規'}")
                        
                        # If the review agent determined it's a false positive, don't delete or punish
                        if not review_result["is_violation"]:
                            print(f"[審核系統] 誤判原因: {review_result['reason'][:100]}")
                            # 不對誤判做任何處理，直接返回
                            return
                            
                    except Exception as review_error:
                        print(f"[審核系統] 執行審核時出錯: {str(review_error)}")
                        # 只根據違規類型數量來決定
                        if len(violation_categories) >= 3:
                            print(f"[審核系統] 評估失敗但檢測到多種違規類型，視為違規")
                            review_result = {
                                "is_violation": True,
                                "reason": f"評估過程出錯，但內容觸發了多種違規類型({', '.join(violation_categories[:3])})，系統判定為違規。",
                                "original_response": f"ERROR: {str(review_error)}"
                            }
                        # 在其他情況下，繼續常規審核流程，無review_result
                
                # Skip review for URL safety issues - unsafe URLs are always violations
                if url_check_result and url_check_result.get('is_unsafe'):
                    if not review_result:
                        review_result = {
                            "is_violation": True,
                            "reason": f"訊息包含不安全的連結，這些連結可能含有詐騙、釣魚或惡意軟體內容。",
                            "original_response": "URL_SAFETY_CHECK: Unsafe URLs detected"
                        }
                    elif not review_result.get("is_violation"):
                        # Override non-violation review result for unsafe URLs
                        review_result["is_violation"] = True
                        review_result["reason"] = f"訊息包含不安全的連結，這些連結可能含有詐騙、釣魚或惡意軟體內容。原始審核結果: {review_result['reason']}"
                        review_result["original_response"] = "URL_SAFETY_CHECK: Unsafe URLs detected"
                
                # Process as violation
                await self._process_violation(message, violation_categories, {
                    'text_result': results.get("text_result"),
                    'image_results': results.get("image_results", []),
                    'url_results': url_check_result,
                    'review_result': review_result
                })
            else:
                logger.debug(f"訊息 {message.id} 通過所有審核檢查")
        except Exception as e:
            logger.error(f"內容審核錯誤: {str(e)}")
            import traceback
            logger.error(f"錯誤堆疊: {traceback.format_exc()}")
            # Log the error but don't raise, to avoid interrupting normal bot operation
    
    async def _review_flagged_content(self, message: discord.Message, violation_categories: List[str], moderation_result: Dict) -> Dict[str, Any]:
        """Use AI to review flagged content."""
        try:
            logger.info(f"開始 AI 複審 - 訊息 {message.id}，違規類別: {violation_categories}")
            
            # Get context messages if configured
            context = None
            if self.config.moderation.review_context_messages > 0:
                logger.debug(f"獲取上下文訊息，數量: {self.config.moderation.review_context_messages}")
                context_messages = []
                async for msg in message.channel.history(
                    limit=self.config.moderation.review_context_messages,
                    before=message,
                    oldest_first=False
                ):
                    context_messages.append(f"{msg.author.display_name}: {msg.content}")
                
                if context_messages:
                    context = "\n".join(reversed(context_messages))
                    logger.debug(f"已獲取 {len(context_messages)} 條上下文訊息")
                else:
                    logger.debug("未找到上下文訊息")
            
            # Log review details
            logger.info(f"準備發送給 AI 複審 - 內容: {message.content[:100]}...")
            logger.debug(f"複審代理狀態 - 主要: {'有' if self.review_agent else '無'}, 備用: {'有' if self.backup_review_agent else '無'}")
            
            # Review the content
            review_result = await review_flagged_content(
                agent=self.review_agent,
                content=message.content,
                violation_categories=violation_categories,
                context=context,
                backup_agent=self.backup_review_agent
            )
            
            logger.info(f"AI 複審完成 - 訊息 {message.id}，結果: {review_result}")
            return review_result
            
        except Exception as e:
            logger.error(f"AI 複審過程發生錯誤 - 訊息 {message.id}: {e}")
            import traceback
            logger.error(f"錯誤堆疊: {traceback.format_exc()}")
            # Default to treating as violation on error
            return {"is_violation": True, "reason": "複審失敗，基於安全考慮視為違規"}
    
    async def _process_violation(self, message: discord.Message, violation_categories: List[str], details: Dict):
        """Process a content violation with comprehensive handling."""
        try:
            logger.warning(f"開始處理違規訊息 {message.id}，類別: {violation_categories}")
            
            # Save channel and author information before deletion
            channel = message.channel
            guild = message.guild
            author = message.author
            text = message.content
            
            # Delete the message (only happens if the review agent confirms it's a violation or review is disabled)
            try:
                review_result = details.get('review_result')
                if review_result is None or review_result.get("is_violation", True):
                    await message.delete()
                    print(f"[審核系統] 已刪除標記為違規的訊息，用戶: {author.display_name}")
                else:
                    # 如果被判定為誤判，不刪除消息也不通知用戶
                    print(f"[審核系統] 消息被標記但審核確認為誤判，已保留。用戶: {author.display_name}")
                    return
            except Exception as e:
                print(f"[審核系統] 刪除消息失敗: {str(e)}")
                return
            
            # Check if user was recently punished - if so, just delete the message without additional notification
            import time
            current_time = time.time()
            user_id = author.id
            is_recent_violator = False
            
            # Simple in-memory tracking for recent violators
            if not hasattr(self, 'tracked_violators'):
                self.tracked_violators = {}
            
            if user_id in self.tracked_violators:
                expiry_time = self.tracked_violators[user_id]
                if current_time < expiry_time:
                    is_recent_violator = True
                    print(f"[審核系統] 用戶 {author.display_name} 最近已被處罰，僅刪除消息而不重複處罰")
                else:
                    # Expired tracking, remove from dictionary
                    del self.tracked_violators[user_id]
            
            # If this is a recent violator, just return after deleting the message
            if is_recent_violator:
                return
                
            # Track this user as a recent violator (24 hours)
            VIOLATION_TRACKING_WINDOW = 24 * 60 * 60  # 24 hours
            self.tracked_violators[user_id] = current_time + VIOLATION_TRACKING_WINDOW
            
            # Record violation in database
            violation_id = self.moderation_db.add_violation(
                user_id=author.id,
                guild_id=guild.id,
                content=text[:1000],  # Limit content length
                violation_categories=violation_categories,
                details=details
            )
            logger.info(f"已記錄違規 {violation_id}，用戶: {author.id}")
            
            # Get violation count
            violation_count = self.moderation_db.get_violation_count(author.id, guild.id)
            logger.info(f"用戶 {author.id} 違規次數: {violation_count}")
            
            # Apply mute if warranted
            mute_success = False
            mute_reason = ""
            mute_embed = None
            if violation_count >= 1:
                logger.warning(f"準備對用戶 {author.id} 實施禁言 (違規次數: {violation_count})")
                try:
                    # Add URL safety results if applicable
                    if details.get('url_results') and details['url_results'].get('is_unsafe'):
                        # Update the moderation results to include URL safety results
                        if "url_safety" not in details:
                            details["url_safety"] = details['url_results']
                    
                    mute_success, mute_reason, mute_embed = await self._apply_mute_with_notification(
                        user=author,
                        violation_categories=violation_categories,
                        content=text,
                        details=details,
                        violation_count=violation_count
                    )
                    print(f"[審核系統] 用戶 {author.display_name} 禁言狀態: {mute_success}")
                except Exception as mute_error:
                    print(f"[審核系統] 禁言用戶 {author.display_name} 時出錯: {str(mute_error)}")
            
            # Clean up old entries in tracked_violators
            if len(self.tracked_violators) > 1000:  # Just to prevent unbounded growth
                current_time = time.time()
                expired_keys = [k for k, v in self.tracked_violators.items() if v < current_time]
                for k in expired_keys:
                    del self.tracked_violators[k]
            
            # Send comprehensive violation notification
            await self._send_comprehensive_violation_notification(
                message, author, channel, guild, violation_categories, violation_count, details, mute_embed
            )
            
            logger.info(f"違規處理完成 - 違規ID: {violation_id}，用戶: {author.id}")
            
        except Exception as e:
            logger.error(f"處理違規訊息 {message.id} 時發生錯誤: {e}")
            import traceback
            logger.error(f"錯誤堆疊: {traceback.format_exc()}")
    

    
    async def _apply_mute_with_notification(self, user: discord.Member, violation_categories: List[str], 
                                           content: str, details: Dict, violation_count: int):
        """Apply Discord timeout to a user and return mute notification embed."""
        try:
            # Calculate mute duration
            duration = self.moderation_db.calculate_mute_duration(violation_count)
            
            if not duration:
                return False, "", None  # No mute needed
            
            # Apply Discord timeout (modern approach, no role needed)
            timeout_until = discord.utils.utcnow() + duration
            await user.timeout(timeout_until, reason=f"Content violation #{violation_count}: {', '.join(violation_categories)}")
            
            # Record mute in database
            self.moderation_db.add_mute(user.id, user.guild.id, violation_count, duration)
            
            logger.info(f"Applied timeout to user {user.id} for {duration}")
            
            # Create mute notification embed
            mute_embed = discord.Embed(
                title="🔇 禁言通知",
                description=f"由於您的違規行為，您已被禁言。",
                color=discord.Color.red()
            )
            
            # Format duration
            total_seconds = int(duration.total_seconds())
            if total_seconds >= 86400:  # 1 day
                days = total_seconds // 86400
                mute_embed.add_field(
                    name="禁言時長",
                    value=f"{days} 天",
                    inline=True
                )
            elif total_seconds >= 3600:  # 1 hour
                hours = total_seconds // 3600
                mute_embed.add_field(
                    name="禁言時長",
                    value=f"{hours} 小時",
                    inline=True
                )
            else:
                minutes = total_seconds // 60
                mute_embed.add_field(
                    name="禁言時長",
                    value=f"{minutes} 分鐘",
                    inline=True
                )
            
            # Calculate next violation duration for warning
            next_violation_count = violation_count + 1
            next_duration = self.moderation_db.calculate_mute_duration(next_violation_count)
            if next_duration:
                next_total_seconds = int(next_duration.total_seconds())
                if next_total_seconds >= 86400:
                    next_days = next_total_seconds // 86400
                    next_duration_text = f"{next_days} 天"
                elif next_total_seconds >= 3600:
                    next_hours = next_total_seconds // 3600
                    next_duration_text = f"{next_hours} 小時"
                else:
                    next_minutes = next_total_seconds // 60
                    next_duration_text = f"{next_minutes} 分鐘"
                
                mute_embed.add_field(
                    name="⚠️ 下次違規",
                    value=f"下次違規將被禁言 **{next_duration_text}**",
                    inline=False
                )
            
            return True, f"Timed out for {duration}", mute_embed
            
        except Exception as e:
            logger.error(f"Error applying timeout to user {user.id}: {e}")
            import traceback
            logger.error(f"錯誤堆疊: {traceback.format_exc()}")
            return False, str(e), None

    async def _send_comprehensive_violation_notification(self, message: discord.Message, author: discord.Member, 
                                                       channel: discord.TextChannel, guild: discord.Guild,
                                                       violation_categories: List[str], violation_count: int, 
                                                       details: Dict, mute_embed: discord.Embed = None):
        """Send comprehensive violation notification based on AIHacker implementation."""
        try:
            import asyncio
            from datetime import datetime, timezone
            
            logger.info(f"開始發送違規通知 - 用戶: {author.display_name}，違規類別: {violation_categories}")
            
            # Create both embeds then send them simultaneously
            try:
                # Channel notification embed - 美觀且簡潔的公共通知
                notification_embed = discord.Embed(
                    title="🛡️ 內容審核",
                    description=f"<@{author.id}> 您的訊息因違反社群規範已被移除",
                    color=discord.Color.from_rgb(231, 76, 60)  # 更柔和的紅色
                )
                
                # 添加違規類型的簡潔顯示
                if violation_categories:
                    from .services.violation_mapping import get_chinese_category
                    
                    # 簡潔的違規類型映射（只用一個表情符號）
                    violation_display = {
                        'harassment': '🚫 騷擾內容',
                        'harassment_threatening': '⚔️ 威脅性騷擾',
                        'hate': '💢 仇恨言論',
                        'violence': '👊 暴力內容',
                        'sexual': '🔞 性相關內容',
                        'self-harm': '💔 自我傷害',
                        'self_harm': '💔 自我傷害',
                        'phishing': '🎣 釣魚網站',
                        'malware': '🦠 惡意軟體',
                        'scam': '💰 詐騙內容'
                    }
                    
                    violation_text = []
                    for category in violation_categories[:2]:  # 最多顯示2個，避免太長
                        display_text = violation_display.get(category.lower())
                        if not display_text:
                            # 如果沒有預設的，使用翻譯
                            chinese_name = get_chinese_category(category)
                            display_text = f"⚠️ {chinese_name}"
                        violation_text.append(display_text)
                    
                    if len(violation_categories) > 2:
                        violation_text.append(f"等 {len(violation_categories)} 項違規")
                    
                    notification_embed.add_field(
                        name="違規類型",
                        value="\n".join(violation_text),
                        inline=False
                    )
                
                # 添加禁言信息（如果有）
                if mute_embed:
                    duration_field = None
                    for field in mute_embed.fields:
                        if field.name == "禁言時長":
                            duration_field = field.value
                            break
                    
                    if duration_field:
                        notification_embed.add_field(
                            name="🔇 處罰",
                            value=f"禁言 {duration_field}",
                            inline=True
                        )
                
                notification_embed.add_field(
                    name="📬 詳細說明",
                    value="已發送詳細通知至您的私訊",
                    inline=True
                )
                
                # 添加時間戳和小字提示
                notification_embed.timestamp = datetime.now(timezone.utc)
                notification_embed.set_footer(text=f"此訊息將在 {self.config.moderation.notification_timeout} 秒後自動刪除")
                
                # DM embed
                dm_embed = discord.Embed(
                    title="🛡️ 內容審核通知",
                    description=f"您在 **{guild.name}** 發送的訊息因含有不適當內容而被移除。",
                    color=discord.Color.from_rgb(230, 126, 34)  # Warm orange color
                )
                
                # Add server icon if available
                if guild.icon:
                    dm_embed.set_thumbnail(url=guild.icon.url)
                
                dm_embed.timestamp = datetime.now(timezone.utc)
                
                # Add URL safety information if applicable
                url_results = details.get('url_results')
                if url_results and url_results.get('is_unsafe'):
                    unsafe_urls = url_results.get('unsafe_urls', [])
                    if unsafe_urls:
                        url_list = "\n".join([f"- {url}" for url in unsafe_urls[:5]])  # Limit to 5 URLs
                        if len(unsafe_urls) > 5:
                            url_list += f"\n- ...以及 {len(unsafe_urls) - 5} 個其他不安全連結"
                            
                        threat_types_map = {
                            'PHISHING': '釣魚網站',
                            'MALWARE': '惡意軟體',
                            'SCAM': '詐騙網站',
                            'SUSPICIOUS': '可疑網站'
                        }
                        
                        threat_descriptions = []
                        for threat in url_results.get('threat_types', []):
                            threat_descriptions.append(threat_types_map.get(threat, threat))
                            
                        threat_text = "、".join(threat_descriptions) if threat_descriptions else "不安全連結"
                        
                        dm_embed.add_field(
                            name="⚠️ 不安全連結",
                            value=f"您的訊息包含可能是{threat_text}的連結：\n{url_list}",
                            inline=False
                        )
                
                # Add violation types with emoji indicators and Chinese translations
                if violation_categories:
                    from .services.violation_mapping import get_chinese_category, get_chinese_description
                    
                    violation_list = []
                    for category in violation_categories:
                        category_text = get_chinese_category(category)
                        violation_list.append(category_text)
                    
                    dm_embed.add_field(
                        name="違規類型",
                        value="\n".join(violation_list),
                        inline=False
                    )
                
                # Add channel information
                dm_embed.add_field(
                    name="📝 頻道",
                    value=f"#{channel.name}",
                    inline=True
                )
                
                # Add violation count
                dm_embed.add_field(
                    name="🔢 違規次數",
                    value=f"這是您的第 **{violation_count}** 次違規",
                    inline=True
                )
                
                # Add a divider
                dm_embed.add_field(
                    name="",
                    value="━━━━━━━━━━━━━━━━━━━━━━━",
                    inline=False
                )
                
                # Add the original content that was flagged
                if message.content:
                    # Truncate text if too long
                    display_text = message.content if len(message.content) <= 1000 else message.content[:997] + "..."
                    dm_embed.add_field(
                        name="📄 訊息內容",
                        value=f"```\n{display_text}\n```",
                        inline=False
                    )
                
                if message.attachments:
                    dm_embed.add_field(
                        name="🖼️ 附件",
                        value=f"包含 {len(message.attachments)} 個附件",
                        inline=False
                    )
                
                # Add another divider
                dm_embed.add_field(
                    name="",
                    value="━━━━━━━━━━━━━━━━━━━━━━━━",
                    inline=False
                )
                
                # Add note and resources
                dm_embed.add_field(
                    name="📋 請注意",
                    value="請確保您發送的內容符合社群規範。重複違規可能導致更嚴重的處罰。\n\n如果您對此決定有疑問，請聯繫伺服器工作人員。",
                    inline=False
                )
                
                # Add guidelines link
                dm_embed.add_field(
                    name="📚 社群規範",
                    value=f"請閱讀我們的[社群規範](https://discord.com/channels/{guild.id}/rules)以了解更多資訊。",
                    inline=False
                )
                
                # Send both messages simultaneously
                tasks = []
                tasks.append(channel.send(embed=notification_embed))
                tasks.append(author.send(embed=dm_embed))
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Log any DM errors
                if len(results) > 1 and isinstance(results[1], Exception):
                    print(f"Failed to send DM: {str(results[1])}")
                
                # Send mute notification after content moderation notification
                if mute_embed:
                    try:
                        await author.send(embed=mute_embed)
                    except Exception as e:
                        print(f"Failed to send mute notification DM: {str(e)}")

                # Extract channel notification for deletion
                if len(results) > 0 and isinstance(results[0], discord.Message):
                    channel_notification = results[0]
                    # Delete the notification after a short delay
                    await asyncio.sleep(self.config.moderation.notification_timeout)
                    try:
                        await channel_notification.delete()
                    except:
                        pass  # Ignore deletion errors
                
            except Exception as e:
                print(f"Failed to send notification messages: {str(e)}")
                
            logger.info(f"違規通知處理完成 - 用戶: {author.display_name}")
            
        except Exception as e:
            logger.error(f"發送違規通知時發生錯誤: {e}")
            import traceback
            logger.error(f"錯誤堆疊: {traceback.format_exc()}")
    
    @tasks.loop(minutes=5)
    async def check_expired_mutes(self):
        """Check for and remove expired timeouts."""
        try:
            expired_mutes = self.moderation_db.check_and_update_expired_mutes()
            
            for mute_data in expired_mutes:
                try:
                    guild = self.bot.get_guild(mute_data['guild_id'])
                    if not guild:
                        continue
                    
                    member = guild.get_member(mute_data['user_id'])
                    if not member:
                        continue
                    
                    # Check if member still has timeout and remove it
                    if member.timed_out_until:
                        await member.timeout(None, reason="Timeout expired")
                        logger.info(f"Removed expired timeout from user {member.id}")
                        
                except Exception as e:
                    logger.error(f"Error removing expired timeout: {e}")
                    
        except Exception as e:
            logger.error(f"Error checking expired timeouts: {e}")
    
    @check_expired_mutes.before_loop
    async def before_check_expired_mutes(self):
        """Wait until bot is ready before starting the task."""
        await self.bot.wait_until_ready()


def setup(bot, config):
    """Set up the moderation module."""
    return ModerationModule(bot, config) 
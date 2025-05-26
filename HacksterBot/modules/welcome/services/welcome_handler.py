"""
Welcome Handler Service for HacksterBot.

This service handles the generation and sending of welcome messages,
including AI-powered personalized messages and fallback templates.
完全基於 AIHacker 的實現。
"""
import logging
import discord
from typing import Optional, List
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)


class WelcomeHandler:
    """Handles welcome message generation and sending."""
    
    def __init__(self, bot, config, welcomed_members_db):
        """
        Initialize the welcome handler.
        
        Args:
            bot: The Discord bot instance
            config: Configuration object
            welcomed_members_db: Database for tracking welcomed members
        """
        self.bot = bot
        self.config = config
        self.welcomed_members_db = welcomed_members_db
        self.ai_agent = None
        
    async def _ensure_ai_agent(self):
        """Ensure AI agent is available for generating welcome messages."""
        if self.ai_agent is not None:
            return
            
        try:
            # Import AI services
            from modules.ai.services.ai_select import get_agent
            from modules.ai.agents.general import create_general_agent
            
            # Get primary AI model for welcome messages (使用主要模型生成創意歡迎訊息)
            model = await get_agent(
                self.config.ai.primary_provider,
                self.config.ai.primary_model
            )
            
            if model:
                # Create a general agent with the model
                self.ai_agent = await create_general_agent(model)
                logger.info("AI agent setup for welcome handler")
            else:
                logger.warning("Failed to get AI model, using default welcome templates")
                
        except Exception as e:
            logger.error(f"Error setting up AI agent for welcome: {e}")
            # Continue without AI - fallback to default templates
    
    async def send_welcome_message(self, member: discord.Member, is_first_join: bool, 
                                 join_count: int, is_retry: bool = False):
        """
        Send welcome message to new member.
        完全基於 AIHacker 的實現。
        
        Args:
            member: The member to welcome
            is_first_join: Whether this is the member's first join
            join_count: Number of times the member has joined
            is_retry: Whether this is a retry attempt
        """
        try:
            print(f"開始發送歡迎訊息給 {member.display_name} (首次加入: {is_first_join}, 加入次數: {join_count})")
            
            # 檢查加入次數限制：第三次及以後不再發送歡迎訊息
            if join_count >= 3:
                print(f"成員 {member.display_name} 已經是第 {join_count} 次加入，不再發送歡迎訊息")
                # 仍然標記為成功，避免重試
                self.welcomed_members_db.mark_welcome_success(member.id, member.guild.id)
                return
            
            # 檢查是否有配置歡迎頻道
            if not self.config.welcome.channel_ids:
                print("警告：未配置歡迎頻道 ID")
                return
                
            print(f"配置的歡迎頻道 IDs: {self.config.welcome.channel_ids}")
            
            # 嘗試在配置的歡迎頻道中發送訊息
            welcome_sent = False
            for channel_id_str in self.config.welcome.channel_ids:
                try:
                    channel_id = int(channel_id_str)
                    print(f"嘗試在頻道 {channel_id} 發送歡迎訊息")
                    channel = self.bot.get_channel(channel_id)
                    
                    if not channel:
                        print(f"無法獲取頻道 {channel_id}，可能是ID錯誤或機器人沒有權限")
                        continue
                        
                    print(f"成功獲取頻道: {channel.name} (ID: {channel_id})")
                    
                    # 檢查權限
                    permissions = channel.permissions_for(member.guild.me)
                    if not permissions.send_messages:
                        print(f"機器人在頻道 {channel_id} 沒有發送訊息的權限")
                        continue
                        
                    print(f"機器人在頻道 {channel_id} 具有發送訊息的權限")
                    
                    # 根據加入次數生成不同的歡迎訊息 - 完全複製 AIHacker 的提示詞
                    welcome_prompt = f"""有一位{'新的' if is_first_join else '回歸的'}使用者 {member.display_name} {'首次' if is_first_join else '第二次'}加入了我們的伺服器！

作為一個活潑可愛的精靈，請你：
1. 用充滿想像力和創意的方式歡迎他
2. 可以提到他的名字，但要巧妙地融入故事中
3. 可以加入一些奇幻或有趣的元素
4. 用 2-3 句話來表達，不要太短
5. 適當使用表情符號來增添趣味
6. {'歡迎新成員加入並簡單介紹伺服器' if is_first_join else '熱情歡迎老朋友回來'}

以下是一些歡迎訊息的例子：
- 哇！✨ 看看是誰從異次元的彩虹橋上滑下來啦！{member.display_name} 帶著滿身的星光降臨到我們這個充滿歡樂的小宇宙，我已經聞到空氣中瀰漫著新朋友的香氣了！🌈

- 叮咚！🔮 我正在喝下午茶的時候，{member.display_name} 就這樣從我的茶杯裡冒出來了！歡迎來到我們這個瘋狂又溫暖的小天地，這裡有數不清的驚喜等著你去發現呢！🫖✨

- 咦？是誰把魔法星星撒在地上了？原來是 {member.display_name} 順著星光來到我們的秘密基地！讓我們一起在這個充滿創意和歡笑的地方，創造屬於我們的奇幻故事吧！🌟

- 哎呀！我的水晶球顯示，有個叫 {member.display_name} 的旅行者，騎著會飛的獨角獸來到了我們的魔法聚會！在這裡，每個人都是獨特的魔法師，期待看到你的神奇表演！🦄✨

請生成一段溫暖但有趣的歡迎訊息。記得要活潑、有趣、富有創意，但不要太過誇張或失禮。"""

                    print(f"開始生成歡迎訊息，提示詞: {welcome_prompt}")
                    
                    try:
                        async with channel.typing():
                            response_received = False
                            full_response = ""
                            
                            # 使用流式回應生成歡迎訊息
                            async for chunk in self._get_streaming_response(welcome_prompt):
                                if chunk:  # 只在有內容時處理
                                    print(f"收到回應片段: {chunk}")
                                    full_response += chunk
                                    
                            if full_response:
                                print(f"生成的完整歡迎訊息: {full_response}")
                                await channel.send(f"{member.mention} {full_response}")
                                welcome_sent = True
                                response_received = True
                                # 標記歡迎成功
                                self.welcomed_members_db.mark_welcome_success(member.id, member.guild.id)
                            else:
                                print("AI 沒有生成任何回應")
                                # 標記歡迎失敗
                                self.welcomed_members_db.mark_welcome_failed(member.id, member.guild.id)
                    except discord.Forbidden as e:
                        print(f"發送訊息時權限錯誤: {str(e)}")
                        self.welcomed_members_db.mark_welcome_failed(member.id, member.guild.id)
                        continue
                    except Exception as e:
                        print(f"在頻道 {channel_id} 生成/發送歡迎訊息時發生錯誤: {str(e)}")
                        self.welcomed_members_db.mark_welcome_failed(member.id, member.guild.id)
                        continue
                    
                    if welcome_sent:
                        print("成功發送歡迎訊息")
                        break  # 如果已經成功發送訊息，就不需要嘗試其他頻道
                        
                except (ValueError, TypeError):
                    print(f"無效的頻道 ID: {channel_id_str}")
                    continue
                except Exception as e:
                    print(f"處理頻道 {channel_id_str} 時發生錯誤: {str(e)}")
                    self.welcomed_members_db.mark_welcome_failed(member.id, member.guild.id)
                    continue
            
            # 如果所有配置的頻道都失敗了，且這是第一次或第二次加入，嘗試找一個可用的文字頻道
            if not welcome_sent:
                print("在配置的頻道中發送訊息失敗，嘗試使用備用頻道")
                try:
                    # 尋找第一個可用的文字頻道
                    fallback_channel = next((channel for channel in member.guild.channels 
                                           if isinstance(channel, discord.TextChannel) and 
                                           channel.permissions_for(member.guild.me).send_messages), None)
                    
                    if fallback_channel:
                        print(f"找到備用頻道: {fallback_channel.name} (ID: {fallback_channel.id})")
                        # 發送預設歡迎訊息
                        await fallback_channel.send(self.config.welcome.default_message.format(member=member.mention))
                        print(f"使用備用頻道 {fallback_channel.id} 發送歡迎訊息成功")
                        self.welcomed_members_db.mark_welcome_success(member.id, member.guild.id)
                    else:
                        print("找不到任何可用的頻道來發送歡迎訊息")
                        self.welcomed_members_db.mark_welcome_failed(member.id, member.guild.id)
                        
                except Exception as e:
                    print(f"使用備用頻道發送歡迎訊息時發生錯誤: {str(e)}")
                    self.welcomed_members_db.mark_welcome_failed(member.id, member.guild.id)
            
            print("成員加入事件處理完成")
                
        except Exception as e:
            logger.error(f"Error sending welcome message for member {member.id}: {e}")
            self.welcomed_members_db.mark_welcome_failed(member.id, member.guild.id)
    
    async def _get_streaming_response(self, message: str):
        """
        Get a streaming response from the AI.
        完全基於 AIHacker 的實現。
        """
        await self._ensure_ai_agent()
        
        if not self.ai_agent:
            # 如果沒有 AI 代理，返回空
            return
            
        try:
            # 使用 pydantic_ai 的流式回應
            async with self.ai_agent.run_stream(message) as result:
                async for chunk in result.stream_text(delta=True):
                    if chunk:
                        yield chunk
                        
        except Exception as e:
            logger.error(f"Error getting streaming AI response: {e}")
            print(f"AI 回應失敗: {str(e)}")
            # 不產生任何回應，讓調用方處理失敗情況 
"""
Mute management service for progressive punishment system.

This module manages Discord timeouts/mutes with progressive punishment levels.
"""
import logging
import discord
from discord.ext import commands
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone, timedelta
import json
import os
import asyncio
from .violation_mapping import format_violation_categories

logger = logging.getLogger(__name__)

class MuteManager:
    """Manages Discord timeouts and progressive punishment system."""
    
    def __init__(self, bot, config):
        """
        Initialize the mute manager.
        
        Args:
            bot: The Discord bot instance
            config: Configuration object
        """
        self.bot = bot
        self.config = config
        
        # Progressive mute durations (in minutes)
        self.mute_durations = [
            5,        # 1st offense: 5 minutes
            720,      # 2nd offense: 12 hours  
            10080,    # 3rd offense: 7 days
            10080,    # 4th offense: 7 days
            40320     # 5th+ offense: 28 days
        ]
        
        # Violation tracking file
        self.violations_file = "data/violations.json"
        self._ensure_data_directory()
        
        # Load existing violations
        self.violations = self._load_violations()
        
        # Active mutes tracking
        self.active_mutes = {}
        
    def _ensure_data_directory(self):
        """Ensure the data directory exists."""
        os.makedirs("data", exist_ok=True)
        
    def _load_violations(self) -> Dict:
        """Load violation history from file."""
        try:
            if os.path.exists(self.violations_file):
                with open(self.violations_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading violations: {e}")
        return {}
        
    def _save_violations(self):
        """Save violation history to file."""
        try:
            with open(self.violations_file, 'w', encoding='utf-8') as f:
                json.dump(self.violations, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving violations: {e}")
    
    def get_user_violation_count(self, user_id: int, guild_id: int) -> int:
        """
        Get the violation count for a user in a guild.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            
        Returns:
            Number of violations
        """
        key = f"{guild_id}:{user_id}"
        return len(self.violations.get(key, []))
    
    def add_violation(self, user_id: int, guild_id: int, violation_categories: List[str], 
                     content: str, details: Dict) -> int:
        """
        Add a violation record for a user.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            violation_categories: List of violation categories
            content: The violating content
            details: Additional violation details
            
        Returns:
            New violation count
        """
        key = f"{guild_id}:{user_id}"
        
        if key not in self.violations:
            self.violations[key] = []
        
        violation_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "categories": violation_categories,
            "content": content[:500] if content else "",  # Limit content length
            "details": details
        }
        
        self.violations[key].append(violation_record)
        self._save_violations()
        
        violation_count = len(self.violations[key])
        logger.info(f"Added violation for user {user_id} in guild {guild_id}. Total: {violation_count}")
        
        return violation_count
    
    def get_mute_duration(self, violation_count: int) -> int:
        """
        Get the mute duration in minutes for a given violation count.
        
        Args:
            violation_count: Number of violations
            
        Returns:
            Mute duration in minutes
        """
        if violation_count <= 0:
            return 0
            
        # Use the appropriate duration from our progressive system
        index = min(violation_count - 1, len(self.mute_durations) - 1)
        return self.mute_durations[index]
    
    async def mute_user(self, user: discord.Member, violation_categories: List[str], 
                       content: str, details: Dict) -> Tuple[bool, str, Optional[discord.Embed]]:
        """
        Mute a user with progressive punishment.
        
        Args:
            user: Discord member to mute
            violation_categories: List of violation categories
            content: The violating content
            details: Additional violation details
            
        Returns:
            Tuple of (success, reason, mute_embed)
        """
        try:
            guild = user.guild
            
            # Add violation record
            violation_count = self.add_violation(
                user.id, guild.id, violation_categories, content, details
            )
            
            # Get mute duration
            mute_duration_minutes = self.get_mute_duration(violation_count)
            
            if mute_duration_minutes <= 0:
                return False, "No mute duration calculated", None
            
            # Apply Discord timeout
            duration = timedelta(minutes=mute_duration_minutes)
            timeout_until = discord.utils.utcnow() + duration
            
            await user.timeout(timeout_until, reason=f"Violation #{violation_count}: {', '.join(violation_categories)}")
            
            # Create mute notification embed
            mute_embed = self._create_mute_embed(user, violation_count, mute_duration_minutes, violation_categories)
            
            # Send DM to user
            await self._send_mute_dm(user, violation_count, mute_duration_minutes, violation_categories, details)
            
            # Track active mute
            self.active_mutes[user.id] = {
                "guild_id": guild.id,
                "expires_at": timeout_until.isoformat(),
                "violation_count": violation_count,
                "categories": violation_categories
            }
            
            logger.info(f"Muted user {user.name} ({user.id}) for {mute_duration_minutes} minutes (violation #{violation_count})")
            
            return True, f"User muted for {self._format_duration(mute_duration_minutes)}", mute_embed
            
        except discord.Forbidden:
            logger.error(f"No permission to mute user {user.name} ({user.id})")
            return False, "No permission to mute user", None
        except Exception as e:
            logger.error(f"Error muting user {user.name} ({user.id}): {e}")
            return False, f"Error muting user: {str(e)}", None
    
    def _create_mute_embed(self, user: discord.Member, violation_count: int, 
                          duration_minutes: int, violation_categories: List[str]) -> discord.Embed:
        """Create embed for mute notification."""
        embed = discord.Embed(
            title="🔇 用戶已被禁言",
            description=f"{user.mention} 因違反社群規範已被禁言",
            color=discord.Color.orange()
        )
        
        embed.add_field(
            name="禁言時長",
            value=self._format_duration(duration_minutes),
            inline=True
        )
        
        embed.add_field(
            name="違規次數",
            value=f"第 {violation_count} 次",
            inline=True
        )
        
        if violation_categories:
            embed.add_field(
                name="違規類型",
                value=format_violation_categories(violation_categories),
                inline=False
            )
        
        # Add progressive punishment explanation
        next_duration = self.get_mute_duration(violation_count + 1)
        if next_duration > duration_minutes:
            embed.add_field(
                name="⚠️ 下次違規處罰",
                value=f"下次違規將被禁言 {self._format_duration(next_duration)}",
                inline=False
            )
        
        embed.set_footer(text="請遵守社群規範，避免再次違規")
        embed.timestamp = datetime.now(timezone.utc)
        
        return embed
    
    async def _send_mute_dm(self, user: discord.Member, violation_count: int, 
                           duration_minutes: int, violation_categories: List[str], details: Dict):
        """Send DM notification to muted user."""
        try:
            embed = discord.Embed(
                title="🔇 您已被禁言",
                description=f"您在 **{user.guild.name}** 因違反社群規範已被禁言",
                color=discord.Color.red()
            )
            
            embed.add_field(
                name="禁言時長",
                value=self._format_duration(duration_minutes),
                inline=True
            )
            
            embed.add_field(
                name="違規次數",
                value=f"第 {violation_count} 次",
                inline=True
            )
            
            if violation_categories:
                embed.add_field(
                    name="違規類型",
                    value=format_violation_categories(violation_categories),
                    inline=False
                )
            
            # Add URL safety information if applicable
            if details.get("url_safety") and details["url_safety"].get("is_unsafe"):
                url_info = details["url_safety"]
                unsafe_urls = url_info.get("unsafe_urls", [])
                if unsafe_urls:
                    url_list = "\n".join([f"- {url}" for url in unsafe_urls[:3]])
                    if len(unsafe_urls) > 3:
                        url_list += f"\n- ...以及 {len(unsafe_urls) - 3} 個其他不安全連結"
                    
                    embed.add_field(
                        name="🔗 不安全連結",
                        value=f"您的訊息包含以下不安全連結：\n{url_list}",
                        inline=False
                    )
            
            # Progressive punishment warning
            next_violation_count = violation_count + 1
            next_duration = self.get_mute_duration(next_violation_count)
            if next_duration > duration_minutes:
                embed.add_field(
                    name="⚠️ 重要提醒",
                    value=f"這是您的第 {violation_count} 次違規。下次違規將被禁言 {self._format_duration(next_duration)}。請務必遵守社群規範！",
                    inline=False
                )
            elif violation_count >= len(self.mute_durations):
                embed.add_field(
                    name="🚨 最終警告",
                    value="您已達到最高違規等級。持續違規可能導致永久封禁。",
                    inline=False
                )
            
            embed.add_field(
                name="📖 社群規範",
                value="請仔細閱讀並遵守我們的社群規範，避免發送不適當的內容。",
                inline=False
            )
            
            embed.set_footer(text=f"禁言將在 {self._format_duration(duration_minutes)} 後自動解除")
            embed.timestamp = datetime.now(timezone.utc)
            
            await user.send(embed=embed)
            logger.info(f"Sent mute DM to {user.name}")
            
        except discord.Forbidden:
            logger.info(f"Could not DM muted user {user.name}")
        except Exception as e:
            logger.error(f"Error sending mute DM to {user.name}: {e}")
    
    def _format_duration(self, minutes: int) -> str:
        """Format duration in a human-readable way."""
        if minutes < 60:
            return f"{minutes} 分鐘"
        elif minutes < 1440:  # Less than 24 hours
            hours = minutes // 60
            remaining_minutes = minutes % 60
            if remaining_minutes == 0:
                return f"{hours} 小時"
            else:
                return f"{hours} 小時 {remaining_minutes} 分鐘"
        else:  # Days
            days = minutes // 1440
            remaining_hours = (minutes % 1440) // 60
            if remaining_hours == 0:
                return f"{days} 天"
            else:
                return f"{days} 天 {remaining_hours} 小時"
    
    async def check_expired_mutes(self):
        """Check and clean up expired mutes."""
        try:
            current_time = discord.utils.utcnow()
            expired_users = []
            
            for user_id, mute_info in self.active_mutes.items():
                expires_at_str = mute_info["expires_at"]
                # Ensure timezone awareness when parsing ISO format
                if expires_at_str.endswith('Z'):
                    expires_at_str = expires_at_str.replace('Z', '+00:00')
                elif not expires_at_str.endswith(('+00:00', '+0000')):
                    # If no timezone info, assume UTC
                    expires_at_str += '+00:00'
                
                expires_at = datetime.fromisoformat(expires_at_str)
                if current_time >= expires_at:
                    expired_users.append(user_id)
            
            # Clean up expired mutes
            for user_id in expired_users:
                del self.active_mutes[user_id]
                logger.info(f"Cleaned up expired mute tracking for user {user_id}")
                
        except Exception as e:
            logger.error(f"Error checking expired mutes: {e}")
    
    async def remove_mute(self, user: discord.Member, reason: str = None) -> bool:
        """
        Remove mute from a user.
        
        Args:
            user: Discord member to unmute
            reason: Reason for removing mute
            
        Returns:
            True if successful
        """
        try:
            await user.timeout(None, reason=reason or "Mute removed")
            
            # Remove from active tracking
            if user.id in self.active_mutes:
                del self.active_mutes[user.id]
            
            logger.info(f"Removed mute from user {user.name} ({user.id})")
            return True
            
        except discord.Forbidden:
            logger.error(f"No permission to remove mute from user {user.name} ({user.id})")
            return False
        except Exception as e:
            logger.error(f"Error removing mute from user {user.name} ({user.id}): {e}")
            return False
    
    def is_user_muted(self, user_id: int) -> bool:
        """Check if a user is currently tracked as muted."""
        return user_id in self.active_mutes
    
    def get_mute_info(self, user_id: int) -> Optional[Dict]:
        """Get mute information for a user."""
        return self.active_mutes.get(user_id)
    
    def clear_user_violations(self, user_id: int, guild_id: int) -> bool:
        """
        Clear all violations for a user (admin command).
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            
        Returns:
            True if violations were cleared
        """
        key = f"{guild_id}:{user_id}"
        if key in self.violations:
            del self.violations[key]
            self._save_violations()
            logger.info(f"Cleared violations for user {user_id} in guild {guild_id}")
            return True
        return False 
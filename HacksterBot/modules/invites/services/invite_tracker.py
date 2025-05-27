"""
Invite tracker for monitoring Discord invite usage.
Handles tracking invite codes and determining who invited new members.
"""
import logging
import discord
from typing import Dict, Optional, Tuple
import asyncio

logger = logging.getLogger(__name__)


class InviteTracker:
    """Tracks Discord invite usage to determine who invited new members."""
    
    def __init__(self, bot, config, invite_mongo, event_manager):
        """
        Initialize invite tracker.
        
        Args:
            bot: Discord bot instance
            config: Bot configuration
            invite_mongo: Invite MongoDB service
            event_manager: Event manager instance
        """
        self.bot = bot
        self.config = config
        self.invite_mongo = invite_mongo
        self.event_manager = event_manager
        
        # Cache of invite data for each guild
        self.guild_invites = {}
        
    async def cache_guild_invites(self, guild: discord.Guild) -> bool:
        """
        Cache all current invites for a guild.
        
        Args:
            guild: Discord guild
            
        Returns:
            bool: True if successful
        """
        try:
            if not guild.me.guild_permissions.manage_guild:
                logger.warning(f"Missing manage_guild permission in {guild.name}")
                return False
            
            invites = await guild.invites()
            invite_data = {}
            
            for invite in invites:
                invite_data[invite.code] = {
                    'uses': invite.uses or 0,
                    'max_uses': invite.max_uses,
                    'inviter_id': invite.inviter.id if invite.inviter else None,
                    'created_at': invite.created_at,
                    'expires_at': invite.expires_at
                }
            
            self.guild_invites[guild.id] = invite_data
            logger.debug(f"Cached {len(invite_data)} invites for guild {guild.name}")
            return True
            
        except discord.Forbidden:
            logger.warning(f"No permission to fetch invites for guild {guild.name}")
            return False
        except Exception as e:
            logger.error(f"Error caching guild invites for {guild.name}: {e}")
            return False
    
    async def update_guild_invites(self, guild: discord.Guild) -> Optional[Dict]:
        """
        Update cached invites and return new invite data.
        
        Args:
            guild: Discord guild
            
        Returns:
            Dict: New invite data, None if error
        """
        try:
            if not guild.me.guild_permissions.manage_guild:
                return None
            
            old_invites = self.guild_invites.get(guild.id, {})
            
            invites = await guild.invites()
            new_invite_data = {}
            
            for invite in invites:
                new_invite_data[invite.code] = {
                    'uses': invite.uses or 0,
                    'max_uses': invite.max_uses,
                    'inviter_id': invite.inviter.id if invite.inviter else None,
                    'created_at': invite.created_at,
                    'expires_at': invite.expires_at
                }
            
            self.guild_invites[guild.id] = new_invite_data
            return new_invite_data
            
        except discord.Forbidden:
            logger.warning(f"No permission to fetch invites for guild {guild.name}")
            return None
        except Exception as e:
            logger.error(f"Error updating guild invites for {guild.name}: {e}")
            return None
    
    async def handle_member_join(self, member: discord.Member) -> Optional[Tuple[str, int]]:
        """
        Handle a member joining and determine who invited them.
        
        Args:
            member: The member who joined
            
        Returns:
            Tuple[str, int]: (invite_code, inviter_id) if found, None otherwise
        """
        try:
            guild = member.guild
            
            # Get old invite data
            old_invites = self.guild_invites.get(guild.id, {})
            
            # Update invite cache
            new_invites = await self.update_guild_invites(guild)
            if new_invites is None:
                logger.warning(f"Could not update invites for {guild.name}")
                return None
            
            # Find which invite was used
            invite_info = self.invite_mongo.find_invite_by_usage(
                guild.id, old_invites, new_invites
            )
            
            if invite_info:
                invite_code, inviter_id = invite_info
                
                # Record the invite join
                invite_record = self.invite_mongo.record_invite_join(
                    invite_code=invite_code,
                    guild_id=guild.id,
                    inviter_id=inviter_id,
                    invited_user_id=member.id,
                    invited_user_name=member.display_name
                )
                
                # Check for event rewards
                await self._process_invite_rewards(
                    inviter_id, guild.id, member.id, member.display_name
                )
                
                # Send notification if enabled
                if self.config.invite.notify_on_invite:
                    await self._send_invite_notification(
                        guild, inviter_id, member, invite_code
                    )
                
                logger.info(f"Processed invite join: {member.display_name} invited by {inviter_id}")
                return invite_code, inviter_id
            
            return None
            
        except Exception as e:
            logger.error(f"Error handling member join for {member.display_name}: {e}")
            return None
    
    async def handle_member_leave(self, member: discord.Member) -> Optional[int]:
        """
        Handle a member leaving and update invite statistics.
        
        Args:
            member: The member who left
            
        Returns:
            int: Inviter user ID if found, None otherwise
        """
        try:
            # Record the leave
            invite_record = self.invite_mongo.record_invite_leave(
                invited_user_id=member.id,
                guild_id=member.guild.id
            )
            
            if invite_record:
                inviter_id = invite_record.inviter_id
                
                # Revoke tickets for this invite (now async)
                revoked_count = await self.invite_mongo.revoke_invite_tickets(
                    inviter_id, member.id, member.guild.id
                )
                
                if revoked_count > 0:
                    logger.info(f"Revoked {revoked_count} tickets from user {inviter_id} due to {member.display_name} leaving")
                
                # Send notification if enabled
                if self.config.invite.notify_on_leave:
                    await self._send_leave_notification(
                        member.guild, inviter_id, member
                    )
                
                logger.info(f"Processed invite leave: {member.display_name} (invited by {inviter_id})")
                return inviter_id
            
            return None
            
        except Exception as e:
            logger.error(f"Error handling member leave for {member.display_name}: {e}")
            return None
    
    async def _process_invite_rewards(self, inviter_id: int, guild_id: int, 
                                    invited_user_id: int, invited_user_name: str):
        """
        Process any rewards for an invite.
        
        Args:
            inviter_id: User ID of inviter
            guild_id: Guild ID
            invited_user_id: User ID of invited user
            invited_user_name: Name of invited user
        """
        try:
            if not self.config.invite.rewards_enabled:
                logger.info(f"Invite rewards disabled, skipping reward processing for {inviter_id}")
                return
            
            logger.info(f"Processing invite rewards for inviter {inviter_id}, invited user {invited_user_name}")
            
            # Check for rewards
            rewards = self.event_manager.check_invite_rewards(
                inviter_id, guild_id, invited_user_id, invited_user_name
            )
            
            if not rewards:
                logger.warning(f"No rewards found for invite by {inviter_id}")
                return
            
            logger.info(f"Found {len(rewards)} rewards to process for inviter {inviter_id}")
            
            # Process each reward (now using async method)
            for reward_data in rewards:
                logger.info(f"Processing reward: {reward_data['event']['name']}")
                result = await self.event_manager.process_reward(reward_data)
                
                if result and result.get('success'):
                    logger.info(f"Reward processed successfully: {result}")
                else:
                    logger.error(f"Failed to process reward: {result}")
                
        except Exception as e:
            logger.error(f"Error processing invite rewards: {e}")
            import traceback
            traceback.print_exc()
    
    async def _send_invite_notification(self, guild: discord.Guild, inviter_id: int, 
                                      member: discord.Member, invite_code: str):
        """Send notification about new invite join."""
        try:
            if not self.config.invite.notification_channel_id:
                return
            
            channel = guild.get_channel(self.config.invite.notification_channel_id)
            if not channel:
                return
            
            # Get inviter stats
            stats = self.invite_mongo.get_user_invite_stats(inviter_id, guild.id)
            
            embed = discord.Embed(
                title="🎯 新成員加入",
                color=0x00ff00,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(
                name="新成員",
                value=f"{member.mention} ({member.display_name})",
                inline=True
            )
            
            embed.add_field(
                name="邀請者",
                value=f"<@{inviter_id}>",
                inline=True
            )
            
            embed.add_field(
                name="邀請碼",
                value=f"`{invite_code}`",
                inline=True
            )
            
            if stats:
                embed.add_field(
                    name="邀請統計",
                    value=f"總邀請: {stats.total_invites}\n活躍邀請: {stats.active_invites}",
                    inline=False
                )
            
            await channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error sending invite notification: {e}")
    
    async def _send_leave_notification(self, guild: discord.Guild, inviter_id: int, 
                                     member: discord.Member):
        """Send notification about member leaving."""
        try:
            if not self.config.invite.notification_channel_id:
                return
            
            channel = guild.get_channel(self.config.invite.notification_channel_id)
            if not channel:
                return
            
            # Get updated inviter stats
            stats = self.invite_mongo.get_user_invite_stats(inviter_id, guild.id)
            
            embed = discord.Embed(
                title="📤 成員離開",
                color=0xff6b6b,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(
                name="離開成員",
                value=f"{member.display_name}",
                inline=True
            )
            
            embed.add_field(
                name="原邀請者",
                value=f"<@{inviter_id}>",
                inline=True
            )
            
            if stats:
                embed.add_field(
                    name="更新後統計",
                    value=f"總邀請: {stats.total_invites}\n活躍邀請: {stats.active_invites}",
                    inline=False
                )
            
            await channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error sending leave notification: {e}")
    
    async def _send_dm_notifications(self, user_id: int, messages: list):
        """Send DM notifications to user."""
        try:
            user = self.bot.get_user(user_id)
            if not user:
                user = await self.bot.fetch_user(user_id)
            
            if not user:
                logger.warning(f"Could not fetch user {user_id} for DM notification")
                return
            
            for message in messages:
                try:
                    await user.send(message)
                    logger.info(f"Sent DM notification to user {user_id}")
                    await asyncio.sleep(0.5)  # Small delay between messages
                except discord.Forbidden:
                    logger.warning(f"Cannot send DM to user {user_id} (DMs disabled)")
                except Exception as e:
                    logger.error(f"Error sending DM to user {user_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error sending DM notifications: {e}")
    
    async def initialize_all_guilds(self):
        """Initialize invite cache for all guilds."""
        try:
            for guild in self.bot.guilds:
                await self.cache_guild_invites(guild)
                await asyncio.sleep(0.1)  # Small delay to avoid rate limits
                
            logger.info(f"Initialized invite cache for {len(self.bot.guilds)} guilds")
            
        except Exception as e:
            logger.error(f"Error initializing guild invites: {e}") 
"""
Invite Module for HacksterBot.

This module provides comprehensive invite tracking functionality including:
- Invite usage tracking and statistics
- Event-based reward system
- Integration with centralized ticket system
- Leaderboards and analytics
- Daily reports with growth charts and leaderboards
"""
import logging
import discord
from discord.ext import commands
from discord import app_commands
from typing import List, Optional, Dict, Any

from core.module_base import ModuleBase
from core.exceptions import ModuleError
from .services.invite_mongo import InviteMongo
from .services.event_manager import EventManager
from .services.invite_tracker import InviteTracker
from .services.task_scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class InviteModule(ModuleBase):
    """Invite tracking module with event-based rewards and daily reports."""
    
    def __init__(self, bot, config):
        """
        Initialize the invite module.
        
        Args:
            bot: The Discord bot instance
            config: Configuration object
        """
        super().__init__(bot, config)
        self.name = "invites"
        self.description = "Invite tracking system with event rewards and daily reports"
        
        # Initialize services
        self.invite_mongo = None
        self.event_manager = None
        self.invite_tracker = None
        self.task_scheduler = None
        
    async def setup(self):
        """Set up the invite module."""
        try:
            if not self.config.invite.enabled:
                logger.info("Invite module is disabled")
                return
                
            # Initialize MongoDB service
            self.invite_mongo = InviteMongo(self.config)
            
            # Get ticket system reference and set it in invite_mongo
            ticket_system = self.bot.get_module('tickets_system')
            if ticket_system:
                self.invite_mongo.set_ticket_system(ticket_system)
                logger.info("Ticket system integration enabled")
            else:
                logger.warning("Ticket system module not found - ticket operations will be disabled")
            
            # Initialize event manager with ticket system integration
            self.event_manager = EventManager(self.config, self.invite_mongo, self.bot)
            
            # Initialize invite tracker
            self.invite_tracker = InviteTracker(
                self.bot, self.config, self.invite_mongo, self.event_manager
            )
            
            # Initialize task scheduler for daily reports
            self.task_scheduler = TaskScheduler(self.config, self.invite_mongo, self.bot)
            
            # Register event listeners
            self.bot.add_listener(self.on_member_join, 'on_member_join')
            self.bot.add_listener(self.on_member_remove, 'on_member_remove')
            self.bot.add_listener(self.on_guild_join, 'on_guild_join')
            self.bot.add_listener(self.on_ready, 'on_ready')
            
            # Register slash commands
            await self._register_commands()
            
            logger.info("Invite module setup completed")
            
        except Exception as e:
            logger.error(f"Failed to setup invite module: {e}")
            raise ModuleError(f"Invite module setup failed: {e}")
    
    async def teardown(self):
        """Clean up the invite module."""
        try:
            # Stop task scheduler
            if self.task_scheduler:
                await self.task_scheduler.stop()
            
            # Remove event listeners
            self.bot.remove_listener(self.on_member_join, 'on_member_join')
            self.bot.remove_listener(self.on_member_remove, 'on_member_remove')
            self.bot.remove_listener(self.on_guild_join, 'on_guild_join')
            self.bot.remove_listener(self.on_ready, 'on_ready')
            
            logger.info("Invite module teardown completed")
            
        except Exception as e:
            logger.error(f"Error during invite module teardown: {e}")
    
    async def on_ready(self):
        """Handle bot ready event."""
        if self.invite_tracker:
            await self.invite_tracker.initialize_all_guilds()
        
        # Start task scheduler for daily reports
        if self.task_scheduler:
            await self.task_scheduler.start()
    
    async def on_guild_join(self, guild: discord.Guild):
        """Handle bot joining a new guild."""
        if self.invite_tracker:
            await self.invite_tracker.cache_guild_invites(guild)
    
    async def on_member_join(self, member: discord.Member):
        """Handle new member join events."""
        try:
            if not self.config.invite.track_invites:
                return
                
            if self.invite_tracker:
                await self.invite_tracker.handle_member_join(member)
                
        except Exception as e:
            logger.error(f"Error handling member join {member.id}: {e}")
    
    async def on_member_remove(self, member: discord.Member):
        """Handle member leave events."""
        try:
            if not self.config.invite.track_invites:
                return
                
            if self.invite_tracker:
                await self.invite_tracker.handle_member_leave(member)
                
        except Exception as e:
            logger.error(f"Error handling member leave {member.id}: {e}")
    
    async def _register_commands(self):
        """Register slash commands for the invite module."""
        
        @self.bot.tree.command(name="invites", description="查看你的邀請統計")
        async def invites_command(interaction: discord.Interaction, user: discord.Member = None):
            """Show invite statistics for a user."""
            await self._handle_invites_command(interaction, user)
        
        @self.bot.tree.command(name="invite_leaderboard", description="查看邀請排行榜")
        async def leaderboard_command(interaction: discord.Interaction):
            """Show invite leaderboard."""
            await self._handle_leaderboard_command(interaction)
        
        @self.bot.tree.command(name="invite_stats", description="查看伺服器邀請統計")
        async def stats_command(interaction: discord.Interaction):
            """Show server invite statistics."""
            await self._handle_stats_command(interaction)
        
        @self.bot.tree.command(name="daily_report", description="立即發送每日報告 (僅管理員)")
        async def daily_report_command(interaction: discord.Interaction):
            """Send daily report immediately (admin only)."""
            await self._handle_daily_report_command(interaction)
    
    async def _handle_invites_command(self, interaction: discord.Interaction, user: discord.Member = None):
        """Handle invites command."""
        try:
            await interaction.response.defer(ephemeral=True)  # Private response
            
            target_user = user or interaction.user
            
            stats = self.invite_mongo.get_user_invite_stats(target_user.id, interaction.guild.id)
            
            embed = discord.Embed(
                title=f"📊 {target_user.display_name} 的邀請統計",
                color=0x3498db,
                timestamp=discord.utils.utcnow()
            )
            
            if stats:
                embed.add_field(
                    name="總邀請數",
                    value=str(stats.total_invites),
                    inline=True
                )
                embed.add_field(
                    name="活躍邀請",
                    value=str(stats.active_invites),
                    inline=True
                )
                embed.add_field(
                    name="已離開",
                    value=str(stats.left_invites),
                    inline=True
                )
                
                if stats.first_invite_at:
                    # Convert to GMT+8 for display
                    gmt8_time = self.invite_mongo.to_gmt8_time(stats.first_invite_at)
                    embed.add_field(
                        name="首次邀請",
                        value=f"<t:{int(gmt8_time.timestamp())}:D>",
                        inline=True
                    )
                
                if stats.last_invite_at:
                    # Convert to GMT+8 for display
                    gmt8_time = self.invite_mongo.to_gmt8_time(stats.last_invite_at)
                    embed.add_field(
                        name="最近邀請",
                        value=f"<t:{int(gmt8_time.timestamp())}:R>",
                        inline=True
                    )
            else:
                embed.description = "尚無邀請記錄"
            
            embed.set_thumbnail(url=target_user.display_avatar.url)
            embed.set_footer(text="使用 /tickets 查看你的活動票券")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in invites command: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("查詢邀請統計時發生錯誤", ephemeral=True)
                else:
                    await interaction.followup.send("查詢邀請統計時發生錯誤", ephemeral=True)
            except Exception as followup_error:
                logger.error(f"Error sending error message: {followup_error}")
    
    async def _handle_leaderboard_command(self, interaction: discord.Interaction):
        """Handle leaderboard command."""
        try:
            await interaction.response.defer(ephemeral=True)  # Private response
            
            leaderboard = self.invite_mongo.get_invite_leaderboard(interaction.guild.id, 10)
            
            embed = discord.Embed(
                title="🏆 邀請排行榜",
                color=0xf1c40f,
                timestamp=discord.utils.utcnow()
            )
            
            if leaderboard:
                leaderboard_text = ""
                for i, stats in enumerate(leaderboard, 1):
                    emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏅"
                    leaderboard_text += f"{emoji} <@{stats.user_id}>: **{stats.active_invites}** 活躍邀請\n"
                
                embed.description = leaderboard_text
            else:
                embed.description = "還沒有邀請記錄"
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in leaderboard command: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("查詢排行榜時發生錯誤", ephemeral=True)
                else:
                    await interaction.followup.send("查詢排行榜時發生錯誤", ephemeral=True)
            except Exception as followup_error:
                logger.error(f"Error sending error message: {followup_error}")
    
    async def _handle_stats_command(self, interaction: discord.Interaction):
        """Handle server stats command."""
        try:
            await interaction.response.defer(ephemeral=True)  # Private response
            
            stats = await self.invite_mongo.get_guild_statistics(interaction.guild.id)
            
            embed = discord.Embed(
                title=f"📈 {interaction.guild.name} 邀請統計",
                color=0x9b59b6,
                timestamp=discord.utils.utcnow()
            )
            
            if stats:
                embed.add_field(
                    name="總邀請者",
                    value=str(stats.get('total_inviters', 0)),
                    inline=True
                )
                embed.add_field(
                    name="總邀請數",
                    value=str(stats.get('total_invites', 0)),
                    inline=True
                )
                embed.add_field(
                    name="活躍邀請",
                    value=str(stats.get('active_invites', 0)),
                    inline=True
                )
                embed.add_field(
                    name="最近7天加入",
                    value=str(stats.get('recent_joins_7d', 0)),
                    inline=True
                )
                embed.add_field(
                    name="已發放票券",
                    value=str(stats.get('tickets_awarded', 0)),
                    inline=True
                )
            else:
                embed.description = "尚無統計數據"
            
            embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in stats command: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("查詢統計數據時發生錯誤", ephemeral=True)
                else:
                    await interaction.followup.send("查詢統計數據時發生錯誤", ephemeral=True)
            except Exception as followup_error:
                logger.error(f"Error sending error message: {followup_error}")

    async def _handle_daily_report_command(self, interaction: discord.Interaction):
        """Handle daily report command (admin only)."""
        try:
            # Check permissions
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ 此指令僅限管理員使用", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            if not self.task_scheduler:
                await interaction.followup.send("❌ 任務調度器未初始化", ephemeral=True)
                return
            
            # Send test report
            success = await self.task_scheduler.send_test_report(interaction.guild.id)
            
            if success:
                await interaction.followup.send("✅ 每日報告已成功發送！", ephemeral=True)
            else:
                await interaction.followup.send("❌ 發送每日報告失敗，請檢查配置或日誌", ephemeral=True)
                
        except Exception as e:
            logger.error(f"Error in daily report command: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ 發送每日報告時發生錯誤", ephemeral=True)
                else:
                    await interaction.followup.send("❌ 發送每日報告時發生錯誤", ephemeral=True)
            except Exception as followup_error:
                logger.error(f"Error sending error message: {followup_error}")


def setup(bot, config):
    """Set up the invite module."""
    return InviteModule(bot, config) 
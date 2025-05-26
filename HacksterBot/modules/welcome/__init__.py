"""
Welcome Module for HacksterBot.

This module provides comprehensive member welcome functionality including:
- AI-generated personalized welcome messages
- Member join tracking and statistics
- Retry mechanism for failed welcomes
- Fallback welcome messages
"""
import logging
import discord
from discord.ext import commands, tasks
from typing import List, Optional, Dict, Any
import asyncio

from core.module_base import ModuleBase
from core.exceptions import ModuleError
from .services.welcomed_members_db import WelcomedMembersDB
from .services.welcome_handler import WelcomeHandler

logger = logging.getLogger(__name__)


class WelcomeModule(ModuleBase):
    """Member welcome module with AI-powered personalized messages."""
    
    def __init__(self, bot, config):
        """
        Initialize the welcome module.
        
        Args:
            bot: The Discord bot instance
            config: Configuration object
        """
        super().__init__(bot, config)
        self.name = "welcome"
        self.description = "Member welcome system with AI-generated messages"
        
        # Initialize services
        self.welcomed_members_db = None
        self.welcome_handler = None
        
    async def setup(self):
        """Set up the welcome module."""
        try:
            if not self.config.welcome.enabled:
                logger.info("Welcome module is disabled")
                return
                
            # Initialize database
            self.welcomed_members_db = WelcomedMembersDB(self.config)
            
            # Initialize welcome handler
            self.welcome_handler = WelcomeHandler(self.bot, self.config, self.welcomed_members_db)
            
            # Start background tasks
            self.retry_welcome_messages.start()
            
            # Register event listeners
            self.bot.add_listener(self.on_member_join, 'on_member_join')
            
            logger.info("Welcome module setup completed")
            
        except Exception as e:
            logger.error(f"Failed to setup welcome module: {e}")
            raise ModuleError(f"Welcome module setup failed: {e}")
    
    async def teardown(self):
        """Clean up the welcome module."""
        try:
            # Stop background tasks
            if self.retry_welcome_messages.is_running():
                self.retry_welcome_messages.cancel()
                
            # Close database connections
            if self.welcomed_members_db:
                self.welcomed_members_db.close()
                
            # Remove event listeners
            self.bot.remove_listener(self.on_member_join, 'on_member_join')
            
            logger.info("Welcome module teardown completed")
            
        except Exception as e:
            logger.error(f"Error during welcome module teardown: {e}")
    
    async def on_member_join(self, member: discord.Member):
        """Handle new member join events."""
        try:
            await self.send_welcome(member)
        except Exception as e:
            logger.error(f"Error handling member join {member.id}: {e}")
    
    async def send_welcome(self, member: discord.Member):
        """Send welcome message to new member."""
        print(f"新成員加入事件觸發: {member.name} (ID: {member.id})")
        
        # 確保服務已初始化
        if not self.welcomed_members_db or not self.welcome_handler:
            print("歡迎服務未初始化")
            return
        
        # 更新成員加入記錄
        is_first_join, join_count = self.welcomed_members_db.add_or_update_member(
            member.id, 
            member.guild.id, 
            member.name
        )
        
        print(f"成員 {member.name} 加入狀態 - 首次加入: {is_first_join}, 加入次數: {join_count}")
        
        # 如果是第三次或更多次加入，不發送歡迎訊息
        if join_count > 2:
            print(f"成員 {member.name} 已經加入 {join_count} 次，不再發送歡迎訊息")
            return
        
        # 檢查是否有配置歡迎頻道
        if not self.config.welcome.channel_ids:
            print("警告：未配置歡迎頻道 ID")
            return
            
        print(f"配置的歡迎頻道 IDs: {self.config.welcome.channel_ids}")
        
        # 使用 welcome handler 發送歡迎訊息
        await self.welcome_handler.send_welcome_message(member, is_first_join, join_count)
        
        print("成員加入事件處理完成")
    
    @tasks.loop(minutes=5)
    async def retry_welcome_messages(self):
        """Retry failed welcome messages."""
        try:
            if not self.welcomed_members_db or not self.welcome_handler:
                return
                
            # Get pending welcomes
            pending_welcomes = self.welcomed_members_db.get_pending_welcomes(
                max_retry=self.config.welcome.max_retries,
                retry_interval_minutes=self.config.welcome.retry_interval_minutes
            )
            
            if not pending_welcomes:
                return
                
            logger.info(f"Found {len(pending_welcomes)} pending welcome messages to retry")
            
            for welcome_data in pending_welcomes:
                try:
                    guild = self.bot.get_guild(welcome_data['guild_id'])
                    if not guild:
                        continue
                        
                    member = guild.get_member(welcome_data['user_id'])
                    if not member:
                        # Member left, mark as failed
                        self.welcomed_members_db.mark_welcome_failed(
                            welcome_data['user_id'], 
                            welcome_data['guild_id']
                        )
                        continue
                    
                    # Get join count for retry
                    join_count = self.welcomed_members_db.get_member_join_count(
                        member.id, 
                        member.guild.id
                    )
                    
                    # Retry welcome message
                    await self.welcome_handler.send_welcome_message(
                        member, 
                        join_count == 1, 
                        join_count,
                        is_retry=True
                    )
                    
                except Exception as e:
                    logger.error(f"Error retrying welcome for user {welcome_data['user_id']}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in retry welcome messages task: {e}")
    
    @retry_welcome_messages.before_loop
    async def before_retry_welcome_messages(self):
        """Wait until bot is ready before starting the task."""
        await self.bot.wait_until_ready()


def setup(bot, config):
    """Set up the welcome module."""
    return WelcomeModule(bot, config) 
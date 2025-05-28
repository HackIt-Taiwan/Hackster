"""
Task scheduler for invite system.
Handles daily report scheduling using discord.ext.tasks.
"""
import logging
import asyncio
from datetime import datetime, timedelta
from discord.ext import tasks
from typing import Optional
from pathlib import Path

from .daily_reporter import DailyReporter

logger = logging.getLogger(__name__)


class TaskScheduler:
    """Handles scheduling of daily tasks for invite system."""
    
    def __init__(self, config, invite_mongo, bot):
        """
        Initialize task scheduler.
        
        Args:
            config: Bot configuration
            invite_mongo: Invite MongoDB service
            bot: Discord bot instance
        """
        self.config = config
        self.invite_mongo = invite_mongo
        self.bot = bot
        self.daily_reporter = DailyReporter(config, invite_mongo, bot)
        
        # Create tasks
        self.daily_report_task = tasks.loop(hours=24)(self._daily_report_task)
        self.config_check_task = tasks.loop(minutes=10)(self._config_check_task)
        
        self._is_running = False
        self._next_report_time = None
        self._last_config_mtime = None
    
    async def start(self):
        """Start the task scheduler."""
        try:
            if self._is_running:
                logger.warning("Task scheduler is already running")
                return
            
            # Load configuration
            if not self.daily_reporter.load_report_config():
                logger.warning("Failed to load report config - daily reports disabled")
                return
            
            if not self.daily_reporter.is_enabled():
                logger.info("Daily reports are disabled")
                return
            
            # Check if channel is configured
            channel_id = self.daily_reporter.get_channel_id()
            if not channel_id:
                logger.warning("No channel configured for daily reports - set channel_id in invite_events.json")
                return
            
            # Calculate when to start the task
            self._next_report_time = self.daily_reporter.get_next_report_time()
            if not self._next_report_time:
                logger.error("Could not calculate next report time")
                return
            
            # Store config file modification time
            self._update_config_mtime()
            
            # Calculate delay until first run
            now = datetime.utcnow()
            delay_seconds = (self._next_report_time - now).total_seconds()
            
            if delay_seconds > 0:
                logger.info(f"Daily reports scheduled to start at {self._next_report_time} UTC")
                logger.info(f"Next report in {delay_seconds/3600:.1f} hours")
                
                # Wait until the scheduled time, then start the loop
                await asyncio.sleep(delay_seconds)
            
            # Start the daily task loop
            self.daily_report_task.start()
            
            # Start config check task
            self.config_check_task.start()
            
            self._is_running = True
            
            logger.info("Task scheduler started successfully")
            
        except Exception as e:
            logger.error(f"Error starting task scheduler: {e}")
    
    async def stop(self):
        """Stop the task scheduler."""
        try:
            if not self._is_running:
                return
            
            # Stop the daily task
            self.daily_report_task.cancel()
            
            # Stop config check task
            self.config_check_task.cancel()
            
            self._is_running = False
            logger.info("Task scheduler stopped")
            
        except Exception as e:
            logger.error(f"Error stopping task scheduler: {e}")
    
    def _update_config_mtime(self):
        """Update the stored config file modification time."""
        try:
            config_file = Path(self.config.invite.events_config_file)
            if config_file.exists():
                self._last_config_mtime = config_file.stat().st_mtime
        except Exception as e:
            logger.error(f"Error getting config file mtime: {e}")
    
    async def _config_check_task(self):
        """Check for config file changes and restart if needed."""
        try:
            config_file = Path(self.config.invite.events_config_file)
            if not config_file.exists():
                return
            
            current_mtime = config_file.stat().st_mtime
            
            # Check if config file was modified
            if self._last_config_mtime and current_mtime > self._last_config_mtime:
                logger.info("Config file changed, restarting task scheduler...")
                
                # Stop current tasks
                await self.stop()
                
                # Wait a moment for file operations to complete
                await asyncio.sleep(2)
                
                # Restart with new config
                await self.start()
                
        except Exception as e:
            logger.error(f"Error in config check task: {e}")
    
    async def _daily_report_task(self):
        """Execute daily report task."""
        try:
            logger.info("Executing daily report task...")
            
            # Reload configuration in case it changed
            if not self.daily_reporter.load_report_config():
                logger.error("Failed to reload report config")
                return
            
            if not self.daily_reporter.is_enabled():
                logger.info("Daily reports are disabled - skipping")
                return
            
            # Send reports for all guilds where the bot is present
            success_count = 0
            total_guilds = len(self.bot.guilds)
            
            for guild in self.bot.guilds:
                try:
                    success = await self.daily_reporter.send_daily_report(guild.id)
                    if success:
                        success_count += 1
                        logger.info(f"Daily report sent successfully for guild {guild.name} ({guild.id})")
                    else:
                        logger.warning(f"Failed to send daily report for guild {guild.name} ({guild.id})")
                        
                except Exception as e:
                    logger.error(f"Error sending daily report for guild {guild.name} ({guild.id}): {e}")
            
            logger.info(f"Daily report task completed: {success_count}/{total_guilds} guilds successful")
            
        except Exception as e:
            logger.error(f"Error in daily report task: {e}")
    
    async def send_test_report(self, guild_id: int) -> bool:
        """
        Send a test daily report immediately.
        
        Args:
            guild_id: Guild ID to send test report for
            
        Returns:
            bool: True if sent successfully
        """
        try:
            logger.info(f"Sending test daily report for guild {guild_id}")
            
            # Load current configuration
            if not self.daily_reporter.load_report_config():
                logger.error("Failed to load report config")
                return False
            
            # Send the report
            success = await self.daily_reporter.send_daily_report(guild_id)
            
            if success:
                logger.info(f"Test daily report sent successfully for guild {guild_id}")
            else:
                logger.warning(f"Failed to send test daily report for guild {guild_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending test daily report: {e}")
            return False
    
    def is_running(self) -> bool:
        """Check if the scheduler is running."""
        return self._is_running
    
    def get_next_report_time(self) -> Optional[datetime]:
        """Get the next scheduled report time."""
        return self._next_report_time
    
    def get_status(self) -> dict:
        """Get scheduler status information."""
        return {
            'running': self._is_running,
            'next_report_time': self._next_report_time,
            'daily_reports_enabled': self.daily_reporter.is_enabled(),
            'scheduled_time': self.daily_reporter.get_schedule_time(),
            'timezone': self.daily_reporter.get_timezone(),
            'channel_id': self.daily_reporter.get_channel_id()
        } 
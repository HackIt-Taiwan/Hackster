"""
Reminder service for automatic meeting notifications.
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
import discord
import pytz
from discord.ext import tasks
from core.models import Meeting, MeetingReminder


class ReminderService:
    """Service for managing meeting reminders."""
    
    def __init__(self, bot, config):
        self.bot = bot
        self.config = config
        self.logger = bot.logger
        self.timezone = pytz.timezone(config.meetings.default_timezone)
        self._running = False
        
    async def start(self):
        """Start the reminder service."""
        if not self._running:
            self.reminder_task.start()
            self._running = True
            self.logger.info("Meeting reminder service started")
    
    async def stop(self):
        """Stop the reminder service."""
        if self._running:
            self.reminder_task.cancel()
            self._running = False
            self.logger.info("Meeting reminder service stopped")
    
    @tasks.loop(minutes=1)  # Check every minute
    async def reminder_task(self):
        """Main reminder task loop."""
        try:
            await self._process_pending_reminders()
        except Exception as e:
            self.logger.error(f"Reminder task error: {e}")
    
    async def _process_pending_reminders(self):
        """Process all pending reminders."""
        now = datetime.utcnow()
        
        # Find all pending reminders that should be sent
        pending_reminders = MeetingReminder.objects(
            scheduled_time__lte=now,
            is_sent=False
        )
        
        for reminder in pending_reminders:
            try:
                await self._send_reminder(reminder)
                
                # Mark as sent
                reminder.is_sent = True
                reminder.sent_at = now
                reminder.save()
                
            except Exception as e:
                self.logger.error(f"Failed to send reminder {reminder.id}: {e}")
                
                # Increment retry count
                reminder.retry_count += 1
                reminder.error_message = str(e)
                
                # If too many retries, mark as failed
                if reminder.retry_count >= 3:
                    reminder.is_sent = True  # Mark as "sent" to stop retrying
                    reminder.error_message = f"Failed after {reminder.retry_count} retries: {e}"
                
                reminder.save()
    
    async def _send_reminder(self, reminder: MeetingReminder):
        """Send a specific reminder."""
        # Get the meeting
        meeting = Meeting.objects(id=reminder.meeting_id).first()
        if not meeting:
            self.logger.warning(f"Meeting not found for reminder: {reminder.meeting_id}")
            return
        
        # Skip if meeting is cancelled or ended
        if meeting.status in ['cancelled', 'ended']:
            self.logger.info(f"Skipping reminder for {meeting.status} meeting: {meeting.id}")
            return
        
        # Get guild
        guild = self.bot.get_guild(meeting.guild_id)
        if not guild:
            self.logger.warning(f"Guild not found: {meeting.guild_id}")
            return
        
        # Send reminder based on type
        if reminder.reminder_type == '24h':
            await self._send_24h_reminder(meeting, guild)
        elif reminder.reminder_type == '5min':
            await self._send_5min_reminder(meeting, guild)
        else:
            self.logger.warning(f"Unknown reminder type: {reminder.reminder_type}")
    
    async def _send_24h_reminder(self, meeting: Meeting, guild: discord.Guild):
        """Send 24 hour reminder."""
        embed = discord.Embed(
            title="📅 會議提醒 - 24小時前",
            description=f"您有一個會議將在明天舉行：\n**{meeting.title}**",
            color=discord.Color.blue()
        )
        
        # Meeting time
        local_time = meeting.scheduled_time.replace(
            tzinfo=pytz.timezone(meeting.timezone)
        )
        time_str = local_time.strftime('%Y/%m/%d %H:%M')
        
        embed.add_field(
            name="⏰ 會議時間",
            value=time_str,
            inline=True
        )
        
        # Organizer
        organizer = guild.get_member(meeting.organizer_id)
        if organizer:
            embed.add_field(
                name="👤 發起人",
                value=organizer.display_name,
                inline=True
            )
        
        # Attendance status
        attending_count = meeting.get_attending_count()
        embed.add_field(
            name="👥 參與狀況",
            value=f"{attending_count} 人確認參加",
            inline=True
        )
        
        if meeting.description:
            embed.add_field(
                name="📋 描述",
                value=meeting.description,
                inline=False
            )
        
        embed.add_field(
            name="💡 提醒",
            value="請提前準備，會議將自動創建語音頻道並開始錄製。",
            inline=False
        )
        
        embed.set_footer(text=f"會議 ID: {meeting.id}")
        
        # Send to attending members
        await self._send_to_attendees(meeting, guild, embed)
        
        # Update meeting to mark 24h reminder sent
        meeting.reminder_24h_sent = True
        meeting.save()
        
        self.logger.info(f"24h reminder sent for meeting: {meeting.id}")
    
    async def _send_5min_reminder(self, meeting: Meeting, guild: discord.Guild):
        """Send 5 minute reminder."""
        embed = discord.Embed(
            title="🚨 會議即將開始 - 5分鐘前",
            description=f"您的會議即將開始：\n**{meeting.title}**",
            color=discord.Color.orange()
        )
        
        # Meeting time
        local_time = meeting.scheduled_time.replace(
            tzinfo=pytz.timezone(meeting.timezone)
        )
        time_str = local_time.strftime('%H:%M')
        
        embed.add_field(
            name="⏰ 開始時間",
            value=f"今天 {time_str}",
            inline=True
        )
        
        # Quick info
        attending_count = meeting.get_attending_count()
        embed.add_field(
            name="👥 參與者",
            value=f"{attending_count} 人",
            inline=True
        )
        
        embed.add_field(
            name="🎯 行動",
            value="請準備加入會議，語音頻道即將創建。",
            inline=False
        )
        
        embed.set_footer(text=f"會議 ID: {meeting.id}")
        
        # Send to attending members
        await self._send_to_attendees(meeting, guild, embed)
        
        # Update meeting to mark 5min reminder sent
        meeting.reminder_5min_sent = True
        meeting.save()
        
        self.logger.info(f"5min reminder sent for meeting: {meeting.id}")
    
    async def _send_to_attendees(self, meeting: Meeting, guild: discord.Guild, 
                               embed: discord.Embed):
        """Send reminder to all attending members."""
        sent_count = 0
        failed_count = 0
        
        for attendee in meeting.attendees:
            if attendee.status == 'attending':
                member = guild.get_member(attendee.user_id)
                if member:
                    try:
                        await member.send(embed=embed)
                        sent_count += 1
                    except discord.Forbidden:
                        # User has DMs disabled
                        failed_count += 1
                    except Exception as e:
                        self.logger.error(f"Failed to send reminder to {member.id}: {e}")
                        failed_count += 1
        
        self.logger.info(f"Reminder sent to {sent_count} members, {failed_count} failed")
    
    async def schedule_meeting_reminders(self, meeting: Meeting):
        """
        Schedule all reminders for a meeting.
        
        Args:
            meeting: Meeting to schedule reminders for
        """
        try:
            # Schedule 24h reminder
            if self.config.meetings.reminder_24h_enabled:
                reminder_24h_time = meeting.scheduled_time - timedelta(hours=24)
                
                # Only schedule if in the future
                if reminder_24h_time > datetime.utcnow():
                    reminder_24h = MeetingReminder(
                        meeting_id=str(meeting.id),
                        reminder_type='24h',
                        scheduled_time=reminder_24h_time
                    )
                    reminder_24h.save()
                    
                    self.logger.info(f"24h reminder scheduled for meeting {meeting.id}")
            
            # Schedule 5min reminder
            if self.config.meetings.reminder_5min_enabled:
                reminder_5min_time = meeting.scheduled_time - timedelta(minutes=5)
                
                # Only schedule if in the future
                if reminder_5min_time > datetime.utcnow():
                    reminder_5min = MeetingReminder(
                        meeting_id=str(meeting.id),
                        reminder_type='5min',
                        scheduled_time=reminder_5min_time
                    )
                    reminder_5min.save()
                    
                    self.logger.info(f"5min reminder scheduled for meeting {meeting.id}")
            
        except Exception as e:
            self.logger.error(f"Failed to schedule reminders for meeting {meeting.id}: {e}")
            raise
    
    async def cancel_meeting_reminders(self, meeting_id: str):
        """
        Cancel all reminders for a meeting.
        
        Args:
            meeting_id: Meeting ID to cancel reminders for
        """
        try:
            # Delete all pending reminders for this meeting
            deleted_count = MeetingReminder.objects(
                meeting_id=meeting_id,
                is_sent=False
            ).delete()
            
            self.logger.info(f"Cancelled {deleted_count} reminders for meeting {meeting_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to cancel reminders for meeting {meeting_id}: {e}")
    
    @reminder_task.before_loop
    async def before_reminder_task(self):
        """Wait for bot to be ready before starting reminder task."""
        await self.bot.wait_until_ready()
        self.logger.info("Bot ready, starting reminder service") 
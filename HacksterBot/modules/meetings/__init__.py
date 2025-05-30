"""
Meetings module for HacksterBot.

This module provides meeting scheduling functionality including:
- Natural language time parsing with AI
- Meeting confirmation and invitations
- Attendance management 
- Automatic reminders (24h/5min before)
- Voice channel creation and recording integration
- Meeting management (reschedule, cancel, modify)
"""

import discord
from discord.ext import commands
from core.module_base import ModuleBase
from .services.meeting_scheduler import MeetingScheduler
from .services.reminder_service import ReminderService
from .services.meeting_manager import MeetingManager
from .agents.time_parser import TimeParserAgent


async def create_module(bot, config):
    """Create the meetings module instance."""
    return MeetingsModule(bot, config)


class MeetingsModule(ModuleBase):
    """Main meetings module class."""
    
    def __init__(self, bot, config):
        super().__init__(bot, config)
        self.scheduler = None
        self.reminder_service = None
        self.manager = None
        self.time_parser = None
        
    async def setup(self):
        """Setup the meetings module."""
        try:
            self.logger.info("Setting up meetings module...")
            
            # MongoDB is already initialized by the core system
            # No need to initialize it again here
            
            # Initialize services
            self.meeting_scheduler = MeetingScheduler(self.bot, self.config)
            self.meeting_manager = MeetingManager(self.bot, self.config)
            self.reminder_service = ReminderService(self.bot, self.config)
            
            # Add aliases for backward compatibility
            self.scheduler = self.meeting_scheduler
            self.manager = self.meeting_manager
            
            # Start reminder task
            await self.reminder_service.start()
            
            # Register commands
            await self._register_commands()
            
            # Register persistent views for meeting buttons
            await self._register_persistent_views()
            
            self.logger.info("Meetings module setup completed")
            
        except Exception as e:
            self.logger.error(f"Error setting up meetings module: {e}")
            raise
            
    async def teardown(self):
        """Clean up meetings module."""
        if self.reminder_service:
            await self.reminder_service.stop()
        
        # Remove event listeners
        self.bot.remove_listener(self._on_voice_state_update, 'on_voice_state_update')
            
    async def _register_commands(self):
        """Register slash commands."""
        
        @self.bot.tree.command(name="meet", description="安排會議")
        async def meet_command(interaction: discord.Interaction, 
                              時間: str, 
                              參與者: str, 
                              標題: str = None,
                              描述: str = None,
                              最大人數: int = None):
            """
            Schedule a meeting with natural language time parsing.
            
            Args:
                時間: Meeting time in natural language (e.g., "明天下午2點", "週五早上10點")
                參與者: Mention users or use "公開" for public meeting
                標題: Meeting title (optional)
                描述: Meeting description (optional)  
                最大人數: Maximum number of attendees (optional)
            """
            await self.meeting_scheduler.handle_meeting_request(
                interaction, 時間, 參與者, 標題, 描述, 最大人數
            )
        
        @self.bot.tree.command(name="meetings", description="查看我的會議")
        async def my_meetings_command(interaction: discord.Interaction):
            """View your scheduled meetings."""
            await self.meeting_manager.show_user_meetings(interaction)
        
        @self.bot.tree.command(name="meeting_info", description="查看會議詳情")
        async def meeting_info_command(interaction: discord.Interaction, 會議id: str):
            """View detailed meeting information."""
            await self.meeting_manager.show_meeting_info(interaction, 會議id)
    
    async def _register_persistent_views(self):
        """Register persistent views to handle button interactions after bot restart."""
        from .views.meeting_attendance_view import MeetingAttendanceView
        from .views.meeting_control_view import MeetingControlView
        
        # Get all active meetings to register their views
        try:
            from core.models import Meeting
            active_meetings = Meeting.objects(status__in=['scheduled', 'started']).all()
            
            for meeting in active_meetings:
                # Register attendance view for each active meeting
                attendance_view = MeetingAttendanceView(str(meeting.id))
                self.bot.add_view(attendance_view)
                
                # Register control view for meetings with organizers
                control_view = MeetingControlView(str(meeting.id), meeting.organizer_id)
                self.bot.add_view(control_view)
            
            self.logger.info(f"Registered persistent views for {len(active_meetings)} active meetings")
            
        except Exception as e:
            self.logger.error(f"Error registering persistent views: {e}")
    
    # Public API methods for other modules
    async def get_meeting_by_id(self, meeting_id: str):
        """Get meeting by ID."""
        if self.meeting_manager:
            return await self.meeting_manager.get_meeting_by_id(meeting_id)
        return None
    
    async def cancel_meeting(self, meeting_id: str, user_id: int):
        """Cancel a meeting."""
        if self.meeting_manager:
            return await self.meeting_manager.cancel_meeting(meeting_id, user_id)
        return False
    
    async def start_meeting(self, meeting_id: str):
        """Start a meeting (create voice channel and begin recording)."""
        if self.meeting_manager:
            return await self.meeting_manager.start_meeting(meeting_id)
        return False
    
    async def end_meeting(self, meeting_id: str):
        """End a meeting (stop recording and cleanup)."""
        if self.manager:
            return await self.manager.end_meeting(meeting_id)
        return False
    
    async def _on_voice_state_update(self, member, before, after):
        """Handle voice state updates to detect empty meeting channels."""
        try:
            # Check if someone left a voice channel
            if before.channel and not after.channel:
                await self._check_empty_meeting_channel(before.channel)
            elif before.channel and after.channel and before.channel != after.channel:
                await self._check_empty_meeting_channel(before.channel)
                
        except Exception as e:
            self.logger.error(f"Error handling voice state update: {e}")
    
    async def _check_empty_meeting_channel(self, voice_channel):
        """Check if a voice channel is empty and end meeting if needed."""
        try:
            # Only check voice channels we created for meetings
            if not voice_channel.name.startswith("🎤"):
                return
            
            # Check if channel is now empty
            if len(voice_channel.members) > 0:
                return
            
            # Find meeting associated with this channel
            from core.models import Meeting
            meeting = Meeting.objects(
                voice_channel_id=voice_channel.id,
                status='started'
            ).first()
            
            if not meeting:
                return
            
            # Auto-end meeting after a short delay to avoid premature endings
            import asyncio
            await asyncio.sleep(60)  # Wait 1 minute
            
            # Re-check if still empty
            updated_channel = self.bot.get_channel(voice_channel.id)
            if updated_channel and len(updated_channel.members) == 0:
                await self.manager.end_meeting(str(meeting.id))
                self.logger.info(f"Auto-ended empty meeting {meeting.id}")
                
        except Exception as e:
            self.logger.error(f"Error checking empty meeting channel: {e}") 
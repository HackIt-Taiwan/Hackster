"""
Meeting Manager - Handles meeting viewing, management, and lifecycle operations.

This service provides functionality for:
- Viewing user meetings
- Managing meeting details
- Starting meetings (voice channel creation)
- Canceling and rescheduling meetings
- Meeting lifecycle management
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional

import discord
from discord.ext import commands

from core.models import Meeting, MeetingAttendee
from ..utils.timezone_utils import get_current_time_gmt8, format_datetime_gmt8


class MeetingManager:
    """Manages meeting operations and lifecycle."""
    
    def __init__(self, bot, config):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    async def show_user_meetings(self, interaction: discord.Interaction):
        """Show all meetings for a user."""
        try:
            user_id = interaction.user.id
            guild_id = interaction.guild.id
            
            # Get user's organized meetings
            organized_meetings = Meeting.objects(
                guild_id=guild_id,
                organizer_id=user_id,
                status__in=['scheduled', 'started']
            ).order_by('scheduled_time')
            
            # Get meetings user is attending
            attending_meetings = Meeting.objects(
                guild_id=guild_id,
                status__in=['scheduled', 'started'],
                attendees__user_id=user_id,
                attendees__status__in=['attending', 'pending']
            ).order_by('scheduled_time')
            
            embed = discord.Embed(
                title="📅 我的會議",
                color=discord.Color.blue(),
                timestamp=get_current_time_gmt8()
            )
            
            # Add organized meetings
            if organized_meetings:
                organized_text = ""
                for meeting in organized_meetings[:5]:  # Limit to 5 meetings
                    time_str = meeting.scheduled_time.strftime("%m/%d %H:%M")
                    status_emoji = "🟢" if meeting.status == "scheduled" else "🔴"
                    organized_text += f"{status_emoji} **{meeting.title}**\n"
                    organized_text += f"   📅 {time_str} | 👥 {len([a for a in meeting.attendees if a.status == 'attending'])}人\n"
                    organized_text += f"   🆔 `{str(meeting.id)}`\n\n"
                
                embed.add_field(
                    name="🎯 我主辦的會議",
                    value=organized_text.strip(),
                    inline=False
                )
            
            # Add attending meetings (excluding ones user organized)
            attending_only = [m for m in attending_meetings if m.organizer_id != user_id]
            if attending_only:
                attending_text = ""
                for meeting in attending_only[:5]:  # Limit to 5 meetings
                    time_str = meeting.scheduled_time.strftime("%m/%d %H:%M")
                    # Get user's attendance status
                    user_status = "pending"
                    for attendee in meeting.attendees:
                        if attendee.user_id == user_id:
                            user_status = attendee.status
                            break
                    
                    status_emoji = {"attending": "✅", "pending": "⏳"}.get(user_status, "⏳")
                    attending_text += f"{status_emoji} **{meeting.title}**\n"
                    attending_text += f"   📅 {time_str} | 👤 <@{meeting.organizer_id}>\n"
                    attending_text += f"   🆔 `{str(meeting.id)}`\n\n"
                
                embed.add_field(
                    name="👥 參與的會議",
                    value=attending_text.strip(),
                    inline=False
                )
            
            if not organized_meetings and not attending_only:
                embed.description = "你目前沒有任何會議安排。\n\n使用 `/meet` 指令來安排新會議！"
            else:
                embed.set_footer(text="使用 /meeting_info <會議ID> 查看詳細資訊")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Error showing user meetings: {e}")
            await interaction.response.send_message(
                "❌ 查看會議時發生錯誤，請稍後再試。", 
                ephemeral=True
            )
    
    async def show_meeting_info(self, interaction: discord.Interaction, meeting_id: str):
        """Show detailed meeting information."""
        try:
            # Validate meeting ID format
            if not meeting_id or len(meeting_id) != 24:
                await interaction.response.send_message(
                    "❌ 會議ID格式錯誤。請確認ID是否正確。", 
                    ephemeral=True
                )
                return
            
            # Get meeting
            meeting = await self.get_meeting_by_id(meeting_id)
            if not meeting:
                await interaction.response.send_message(
                    "❌ 找不到指定的會議。請確認會議ID是否正確。", 
                    ephemeral=True
                )
                return
            
            # Check if user has access to this meeting
            user_id = interaction.user.id
            has_access = (
                meeting.organizer_id == user_id or 
                any(a.user_id == user_id for a in meeting.attendees)
            )
            
            if not has_access:
                await interaction.response.send_message(
                    "❌ 你沒有權限查看這個會議。", 
                    ephemeral=True
                )
                return
            
            embed = await self._create_meeting_info_embed(meeting, interaction.guild)
            
            # Create management buttons if user is organizer
            view = None
            if meeting.organizer_id == user_id and meeting.status in ['scheduled', 'started']:
                view = MeetingManagementView(meeting, self)
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Error showing meeting info: {e}")
            await interaction.response.send_message(
                "❌ 查看會議資訊時發生錯誤，請稍後再試。", 
                ephemeral=True
            )
    
    async def get_meeting_by_id(self, meeting_id: str) -> Optional[Meeting]:
        """Get meeting by ID."""
        try:
            return Meeting.objects(id=meeting_id).first()
        except Exception as e:
            self.logger.error(f"Error getting meeting by ID {meeting_id}: {e}")
            return None
    
    async def cancel_meeting(self, meeting_id: str, user_id: int) -> bool:
        """Cancel a meeting."""
        try:
            meeting = await self.get_meeting_by_id(meeting_id)
            if not meeting:
                return False
            
            # Check permissions
            if meeting.organizer_id != user_id:
                return False
            
            if meeting.status not in ['scheduled', 'started']:
                return False
            
            # Update meeting status
            meeting.status = 'cancelled'
            meeting.cancelled_at = get_current_time_gmt8()
            meeting.save()
            
            # Cancel reminders
            from .reminder_service import ReminderService
            reminder_service = ReminderService(self.bot, self.config)
            await reminder_service.cancel_meeting_reminders(meeting_id)
            
            # Notify attendees
            await self._notify_meeting_cancelled(meeting)
            
            # Delete voice and text channels if they exist
            if meeting.voice_channel_id:
                await self._cleanup_voice_channel(meeting.voice_channel_id)
            if meeting.text_channel_id:
                await self._cleanup_text_channel(meeting.text_channel_id)
            
            self.logger.info(f"Meeting {meeting_id} cancelled by user {user_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error cancelling meeting {meeting_id}: {e}")
            return False
    
    async def start_meeting(self, meeting_id: str) -> bool:
        """Start a meeting by creating voice channel and beginning recording."""
        try:
            meeting = await self.get_meeting_by_id(meeting_id)
            if not meeting:
                return False
            
            if meeting.status != 'scheduled':
                return False
            
            guild = self.bot.get_guild(meeting.guild_id)
            if not guild:
                return False
            
            # Create voice channel
            voice_channel = await self._create_meeting_voice_channel(meeting, guild)
            if not voice_channel:
                return False
            
            # Update meeting status
            meeting.status = 'started'
            meeting.started_at = get_current_time_gmt8()
            meeting.voice_channel_id = voice_channel.id
            meeting.save()
            
            # Start recording if enabled and recording module available
            if (meeting.recording_enabled and 
                self.config.meetings.auto_start_recording):
                await self._start_meeting_recording(meeting, voice_channel)
            
            # Notify attendees that meeting has started
            await self._notify_meeting_started(meeting, voice_channel)
            
            self.logger.info(f"Meeting {meeting_id} started with voice channel {voice_channel.id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error starting meeting {meeting_id}: {e}")
            return False
    
    async def end_meeting(self, meeting_id: str) -> bool:
        """End a meeting and stop recording."""
        try:
            meeting = await self.get_meeting_by_id(meeting_id)
            if not meeting:
                return False
            
            if meeting.status != 'started':
                return False
            
            # Stop recording if it was started
            if meeting.recording_started and meeting.voice_channel_id:
                await self._stop_meeting_recording(meeting, meeting.voice_channel_id)
            
            # Update meeting status
            meeting.status = 'ended'
            meeting.ended_at = get_current_time_gmt8()
            meeting.save()
            
            # Notify attendees that meeting has ended
            await self._notify_meeting_ended(meeting)
            
            # Clean up voice and text channels after delay
            if meeting.voice_channel_id:
                await self._cleanup_voice_channel(meeting.voice_channel_id)
            if meeting.text_channel_id:
                await self._cleanup_text_channel(meeting.text_channel_id)
            
            self.logger.info(f"Meeting {meeting_id} ended")
            return True
            
        except Exception as e:
            self.logger.error(f"Error ending meeting {meeting_id}: {e}")
            return False

    async def _stop_meeting_recording(self, meeting: Meeting, voice_channel_id: int):
        """Stop recording for the meeting."""
        try:
            # Check if recording module is available
            recording_module = self.bot.modules.get('recording')
            if not recording_module:
                self.logger.warning(f"Recording module not available for meeting {meeting.id}")
                return False
            
            # Stop recording through recording module API
            success = await recording_module.stop_recording(voice_channel_id)
            if success:
                # Update meeting with recording info
                meeting.recording_started = False
                meeting.recording_stopped_at = get_current_time_gmt8()
                meeting.save()
                
                self.logger.info(f"Stopped recording for meeting {meeting.id} in channel {voice_channel_id}")
                return True
            else:
                self.logger.warning(f"Failed to stop recording for meeting {meeting.id}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error stopping recording for meeting {meeting.id}: {e}")
            return False

    async def _notify_meeting_ended(self, meeting: Meeting):
        """Notify attendees that meeting has ended."""
        try:
            guild = self.bot.get_guild(meeting.guild_id)
            if not guild:
                return
            
            embed = discord.Embed(
                title="✅ 會議已結束",
                description=f"**{meeting.title}** 已結束。",
                color=discord.Color.green(),
                timestamp=get_current_time_gmt8()
            )
            
            embed.add_field(
                name="⏰ 結束時間",
                value=f"**{format_datetime_gmt8(meeting.ended_at)}**",
                inline=True
            )
            
            if meeting.started_at:
                duration = meeting.ended_at - meeting.started_at
                duration_str = f"{int(duration.total_seconds() // 60)}分鐘"
                embed.add_field(
                    name="⏱️ 會議時長",
                    value=duration_str,
                    inline=True
                )
            
            # Recording info
            if meeting.recording_started:
                embed.add_field(
                    name="🎥 錄製",
                    value="錄製已保存",
                    inline=True
                )
            
            # Send to announcement channel
            if meeting.announcement_channel_id:
                channel = guild.get_channel(meeting.announcement_channel_id)
                if channel:
                    await channel.send(embed=embed)
            
        except Exception as e:
            self.logger.error(f"Error notifying meeting ended {meeting.id}: {e}")
    
    async def _create_meeting_info_embed(self, meeting: Meeting, guild: discord.Guild) -> discord.Embed:
        """Create detailed meeting information embed."""
        embed = discord.Embed(
            title=f"📋 {meeting.title}",
            color=self._get_status_color(meeting.status),
            timestamp=meeting.created_at
        )
        
        # Meeting details
        time_str = format_datetime_gmt8(meeting.scheduled_time)
        duration_str = f"{meeting.duration_minutes}分鐘"
        
        embed.add_field(
            name="⏰ 會議時間",
            value=f"📅 {time_str}\n⏱️ 預計時長：{duration_str}",
            inline=True
        )
        
        # Organizer
        organizer = guild.get_member(meeting.organizer_id)
        organizer_name = organizer.display_name if organizer else f"<@{meeting.organizer_id}>"
        embed.add_field(
            name="👤 主辦人",
            value=organizer_name,
            inline=True
        )
        
        # Status
        status_map = {
            'scheduled': '📅 已安排',
            'started': '🟢 進行中',
            'ended': '✅ 已結束',
            'cancelled': '❌ 已取消',
            'rescheduled': '🔄 已改期'
        }
        embed.add_field(
            name="📊 狀態",
            value=status_map.get(meeting.status, meeting.status),
            inline=True
        )
        
        # Description
        if meeting.description:
            embed.add_field(
                name="📝 會議描述",
                value=meeting.description,
                inline=False
            )
        
        # Attendees
        attendee_text = self._format_attendees(meeting, guild)
        if attendee_text:
            embed.add_field(
                name="👥 參與者",
                value=attendee_text,
                inline=False
            )
        
        # Voice channel info
        if meeting.voice_channel_id:
            embed.add_field(
                name="🔊 語音頻道",
                value=f"<#{meeting.voice_channel_id}>",
                inline=True
            )
        
        # Meeting ID
        embed.add_field(
            name="🆔 會議ID",
            value=f"`{str(meeting.id)}`",
            inline=True
        )
        
        embed.set_footer(text="會議管理系統")
        return embed
    
    def _format_attendees(self, meeting: Meeting, guild: discord.Guild) -> str:
        """Format attendees list for display in Apple style."""
        if not meeting.attendees:
            return "尚無參與者"
        
        attendee_groups = {
            'attending': [],
            'not_attending': [],
            'pending': []
        }
        
        for attendee in meeting.attendees:
            member = guild.get_member(attendee.user_id)
            name = member.display_name if member else f"<@{attendee.user_id}>"
            attendee_groups[attendee.status].append(name)
        
        result = []
        
        if attendee_groups['attending']:
            result.append(f"**參加者** ({len(attendee_groups['attending'])})")
            # Show first 8 names for clean display
            shown = attendee_groups['attending'][:8]
            result.append("・".join(shown))
            if len(attendee_groups['attending']) > 8:
                result.append(f"等 {len(attendee_groups['attending'])} 人")
        
        if attendee_groups['pending']:
            if result:
                result.append("")  # Add spacing
            result.append(f"**待回覆** ({len(attendee_groups['pending'])})")
            # Only show pending if not too many
            if len(attendee_groups['pending']) <= 5:
                result.append("・".join(attendee_groups['pending']))
            else:
                result.append(f"{len(attendee_groups['pending'])} 人")
        
        if attendee_groups['not_attending'] and len(attendee_groups['not_attending']) <= 3:
            if result:
                result.append("")  # Add spacing
            result.append(f"**無法參加** ({len(attendee_groups['not_attending'])})")
            result.append("・".join(attendee_groups['not_attending']))
        
        return "\n".join(result) if result else "尚無參與者"
    
    def _get_status_color(self, status: str) -> discord.Color:
        """Get color for meeting status."""
        color_map = {
            'scheduled': discord.Color.blue(),
            'started': discord.Color.green(),
            'ended': discord.Color.dark_grey(),
            'cancelled': discord.Color.red(),
            'rescheduled': discord.Color.orange()
        }
        return color_map.get(status, discord.Color.default())
    
    async def _create_meeting_voice_channel(self, meeting: Meeting, guild: discord.Guild):
        """Create a voice channel for the meeting with advanced category logic."""
        try:
            # Get the channel where meeting was scheduled
            announcement_channel = guild.get_channel(meeting.announcement_channel_id)
            
            # First try to find "會議室" in the same category as announcement channel
            target_category = None
            meeting_room_channel = None
            meeting_record_forum = None
            
            if announcement_channel and hasattr(announcement_channel, 'category') and announcement_channel.category:
                # Check if the announcement channel's category has "會議室" voice channel and "會議記錄" forum
                for channel in announcement_channel.category.channels:
                    if isinstance(channel, discord.VoiceChannel) and channel.name == "會議室":
                        meeting_room_channel = channel
                    elif isinstance(channel, discord.ForumChannel) and channel.name == "會議記錄":
                        meeting_record_forum = channel
                
                # If both exist, use this category
                if meeting_room_channel and meeting_record_forum:
                    target_category = announcement_channel.category
                    self.logger.info(f"Found meeting infrastructure in category: {target_category.name}")
            
            # If not found, look for or create "公共會議空間" category
            if not target_category:
                public_meeting_category_name = "公共會議空間"
                for cat in guild.categories:
                    if cat.name == public_meeting_category_name:
                        target_category = cat
                        break
                
                if not target_category:
                    # Create the public meeting category
                    target_category = await guild.create_category(public_meeting_category_name)
                    self.logger.info(f"Created new category: {public_meeting_category_name}")
                
                # Check if this category has the required channels
                for channel in target_category.channels:
                    if isinstance(channel, discord.VoiceChannel) and channel.name == "會議室":
                        meeting_room_channel = channel
                    elif isinstance(channel, discord.ForumChannel) and channel.name == "會議記錄":
                        meeting_record_forum = channel
                
                # Create missing infrastructure
                if not meeting_room_channel:
                    meeting_room_channel = await target_category.create_voice_channel(
                        name="會議室",
                        reason="Created meeting room for meeting infrastructure"
                    )
                    self.logger.info("Created '會議室' voice channel")
                
                if not meeting_record_forum:
                    meeting_record_forum = await target_category.create_forum_channel(
                        name="會議記錄",
                        reason="Created meeting record forum for meeting infrastructure"
                    )
                    self.logger.info("Created '會議記錄' forum channel")
            
            # Create the actual meeting voice channel
            channel_name = f"🎤 {meeting.title}"
            if len(channel_name) > 100:  # Discord limit
                channel_name = f"🎤 {meeting.title[:90]}..."
            
            # Set up permissions for meeting participants
            overwrites = {}
            
            # Default permissions - deny everyone except meeting participants
            overwrites[guild.default_role] = discord.PermissionOverwrite(
                view_channel=False,
                connect=False
            )
            
            # Allow meeting organizer and attendees
            organizer = guild.get_member(meeting.organizer_id)
            if organizer:
                overwrites[organizer] = discord.PermissionOverwrite(
                    view_channel=True,
                    connect=True,
                    speak=True,
                    use_voice_activation=True,
                    priority_speaker=True  # Give organizer priority
                )
            
            # Add permissions for all attendees
            for attendee in meeting.attendees:
                if attendee.status == 'attending':  # Only confirmed attendees
                    member = guild.get_member(attendee.user_id)
                    if member:
                        overwrites[member] = discord.PermissionOverwrite(
                            view_channel=True,
                            connect=True,
                            speak=True,
                            use_voice_activation=True
                        )
            
            # Create the meeting voice channel
            voice_channel = await target_category.create_voice_channel(
                name=channel_name,
                overwrites=overwrites,
                reason=f"Meeting: {meeting.title}"
            )
            
            # Create corresponding text channel for meeting coordination
            text_channel_name = f"📝-{meeting.title.lower().replace(' ', '-')}"
            if len(text_channel_name) > 100:
                text_channel_name = f"📝-{meeting.title[:90].lower().replace(' ', '-')}..."
            
            text_channel = await target_category.create_text_channel(
                name=text_channel_name,
                overwrites=overwrites,
                reason=f"Meeting text channel: {meeting.title}"
            )
            
            # Update meeting with channel info
            meeting.voice_channel_id = voice_channel.id
            meeting.text_channel_id = text_channel.id
            meeting.save()
            
            # Send welcome message to text channel
            embed = discord.Embed(
                title="🎯 會議協調頻道",
                description=f"歡迎參加 **{meeting.title}**！\n\n" +
                           f"🔊 語音頻道：{voice_channel.mention}\n" +
                           f"📝 文字頻道：{text_channel.mention}\n\n" +
                           "請等待錄製機器人加入，會議即將開始錄製。",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="👤 主辦人",
                value=f"<@{meeting.organizer_id}>",
                inline=True
            )
            
            embed.add_field(
                name="⏰ 會議時間", 
                value=f"**{meeting.scheduled_time.strftime('%Y/%m/%d %H:%M')}**",
                inline=True
            )
            
            await text_channel.send(embed=embed)
            
            # Schedule recording bot to join and start 5-minute timeout
            await self._setup_meeting_recording_and_timeout(meeting, voice_channel, text_channel)
            
            self.logger.info(f"Created meeting channels - Voice: {voice_channel.id}, Text: {text_channel.id}")
            return voice_channel
            
        except Exception as e:
            self.logger.error(f"Error creating voice channel for meeting {meeting.id}: {e}")
            return None
    
    async def _setup_meeting_recording_and_timeout(self, meeting: Meeting, voice_channel: discord.VoiceChannel, text_channel: discord.TextChannel):
        """Setup recording bot and 5-minute timeout for meeting."""
        import asyncio
        
        try:
            # Get recording module
            recording_module = self.bot.modules.get('recording')
            if not recording_module:
                self.logger.warning(f"Recording module not available for meeting {meeting.id}")
                return
            
            # Try to get a recording bot to join the voice channel
            if recording_module.recording_manager:
                # Get an available recording bot
                assigned_bot = recording_module.recording_manager.assign_bot_for_meeting()
                if assigned_bot:
                    try:
                        # Connect the recording bot to voice channel
                        voice_client = await voice_channel.connect(bot=assigned_bot)
                        self.logger.info(f"Recording bot {assigned_bot.user.name} joined voice channel {voice_channel.id}")
                        
                        # Update recording bot's meeting info
                        assigned_bot.meeting_voice_channel_info[voice_channel.id] = {
                            "start_time": time.time(),
                            "active_participants": set(),
                            "all_participants": set(),
                            "forum_thread_id": None,
                            "summary_message_id": None,
                            "recording_task": None,
                            "user_join_time": {},
                            "user_leave_time": {},
                            "user_recording_status": {},
                            "voice_client": voice_client,
                            "meeting_id": str(meeting.id),
                            "text_channel_id": text_channel.id
                        }
                        
                        # Send confirmation to text channel
                        await text_channel.send("✅ 錄製機器人已加入，會議準備就緒！")
                        
                    except Exception as e:
                        self.logger.error(f"Failed to connect recording bot: {e}")
                        await text_channel.send("⚠️ 錄製機器人連接失敗，但會議仍可進行。")
                else:
                    self.logger.warning("No available recording bot")
                    await text_channel.send("⚠️ 目前沒有可用的錄製機器人，會議將不會錄製。")
            
            # Start 5-minute timeout task
            asyncio.create_task(self._monitor_meeting_timeout(meeting, voice_channel, text_channel))
            
        except Exception as e:
            self.logger.error(f"Error setting up meeting recording and timeout: {e}")
    
    async def _monitor_meeting_timeout(self, meeting: Meeting, voice_channel: discord.VoiceChannel, text_channel: discord.TextChannel):
        """Monitor meeting for 5-minute timeout if no one joins."""
        import asyncio
        import time
        
        try:
            # Wait 5 minutes
            timeout_minutes = 5
            timeout_seconds = timeout_minutes * 60
            
            self.logger.info(f"Starting {timeout_minutes}-minute timeout monitor for meeting {meeting.id}")
            
            # Send initial warning to text channel
            embed = discord.Embed(
                title="⏰ 會議超時監控",
                description=f"會議將在 **{timeout_minutes} 分鐘**內自動取消，除非有參與者加入語音頻道。",
                color=discord.Color.orange()
            )
            timeout_message = await text_channel.send(embed=embed)
            
            # Check every 30 seconds
            check_interval = 30
            elapsed = 0
            
            while elapsed < timeout_seconds:
                await asyncio.sleep(check_interval)
                elapsed += check_interval
                
                # Refresh voice channel info
                updated_voice_channel = self.bot.get_channel(voice_channel.id)
                if not updated_voice_channel:
                    # Channel was deleted
                    return
                
                # Check if anyone (except bots) joined
                human_members = [m for m in updated_voice_channel.members if not m.bot]
                if human_members:
                    # Someone joined! Cancel timeout
                    embed = discord.Embed(
                        title="✅ 會議已開始",
                        description="參與者已加入，會議正常進行！",
                        color=discord.Color.green()
                    )
                    await timeout_message.edit(embed=embed)
                    self.logger.info(f"Meeting {meeting.id} started - participants joined")
                    return
                
                # Update timeout message with remaining time
                remaining_minutes = (timeout_seconds - elapsed) // 60
                remaining_seconds = (timeout_seconds - elapsed) % 60
                
                if remaining_minutes > 0:
                    remaining_str = f"{remaining_minutes} 分 {remaining_seconds} 秒"
                else:
                    remaining_str = f"{remaining_seconds} 秒"
                
                embed = discord.Embed(
                    title="⏰ 會議超時監控",
                    description=f"會議將在 **{remaining_str}** 後自動取消，除非有參與者加入語音頻道。",
                    color=discord.Color.orange()
                )
                try:
                    await timeout_message.edit(embed=embed)
                except:
                    pass  # Message might be deleted
            
            # Timeout reached - cancel meeting
            self.logger.info(f"Meeting {meeting.id} timed out - no participants joined within {timeout_minutes} minutes")
            
            # Update timeout message
            embed = discord.Embed(
                title="❌ 會議已自動取消",
                description=f"由於 {timeout_minutes} 分鐘內無人加入，會議已自動取消。",
                color=discord.Color.red()
            )
            try:
                await timeout_message.edit(embed=embed)
            except:
                pass
            
            # Cancel the meeting
            await self._cancel_meeting_due_to_timeout(meeting, voice_channel, text_channel)
            
        except asyncio.CancelledError:
            # Timeout was cancelled (meeting started normally)
            self.logger.info(f"Timeout monitor cancelled for meeting {meeting.id}")
        except Exception as e:
            self.logger.error(f"Error in meeting timeout monitor: {e}")
    
    async def _cancel_meeting_due_to_timeout(self, meeting: Meeting, voice_channel: discord.VoiceChannel, text_channel: discord.TextChannel):
        """Cancel meeting due to timeout and cleanup."""
        try:
            # Update meeting status
            meeting.status = 'cancelled'
            meeting.cancelled_at = get_current_time_gmt8()
            meeting.cancellation_reason = '5分鐘內無人加入自動取消'
            meeting.save()
            
            # Disconnect recording bot if connected
            recording_module = self.bot.modules.get('recording')
            if recording_module and recording_module.recording_manager:
                for bot in recording_module.recording_manager.recording_bots:
                    if voice_channel.id in bot.meeting_voice_channel_info:
                        voice_client = bot.meeting_voice_channel_info[voice_channel.id].get('voice_client')
                        if voice_client:
                            await voice_client.disconnect()
                            self.logger.info(f"Disconnected recording bot from voice channel {voice_channel.id}")
                        
                        # Clean up meeting info
                        del bot.meeting_voice_channel_info[voice_channel.id]
            
            # Send final message to text channel
            embed = discord.Embed(
                title="🔄 清理會議頻道",
                description="會議頻道將在 30 秒後自動刪除。",
                color=discord.Color.red()
            )
            await text_channel.send(embed=embed)
            
            # Notify attendees about cancellation
            await self._notify_meeting_cancelled(meeting)
            
            # Schedule cleanup
            import asyncio
            await asyncio.sleep(30)
            
            # Delete channels
            try:
                await voice_channel.delete(reason="Meeting cancelled due to timeout")
                await text_channel.delete(reason="Meeting cancelled due to timeout") 
                self.logger.info(f"Deleted meeting channels for timed out meeting {meeting.id}")
            except Exception as e:
                self.logger.error(f"Error deleting timeout meeting channels: {e}")
                
        except Exception as e:
            self.logger.error(f"Error cancelling meeting due to timeout: {e}")
    
    async def _start_meeting_recording(self, meeting: Meeting, voice_channel: discord.VoiceChannel):
        """Start recording for the meeting."""
        try:
            # Check if recording module is available
            recording_module = self.bot.modules.get('recording')
            if not recording_module:
                self.logger.warning(f"Recording module not available for meeting {meeting.id}")
                return False
            
            # Start recording through recording module API
            success = await recording_module.start_recording(voice_channel.id)
            if success:
                # Update meeting with recording info
                meeting.recording_started = True
                meeting.recording_started_at = get_current_time_gmt8()
                meeting.save()
                
                self.logger.info(f"Started recording for meeting {meeting.id} in channel {voice_channel.id}")
                return True
            else:
                self.logger.warning(f"Failed to start recording for meeting {meeting.id}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error starting recording for meeting {meeting.id}: {e}")
            return False
    
    async def _notify_meeting_started(self, meeting: Meeting, voice_channel: discord.VoiceChannel):
        """Notify attendees that meeting has started."""
        try:
            guild = self.bot.get_guild(meeting.guild_id)
            if not guild:
                return
            
            embed = discord.Embed(
                title="🟢 會議已開始！",
                description=f"**{meeting.title}** 現在開始了！",
                color=discord.Color.green(),
                timestamp=get_current_time_gmt8()
            )
            
            embed.add_field(
                name="🔊 語音頻道",
                value=f"{voice_channel.mention}",
                inline=False
            )
            
            embed.add_field(
                name="⏰ 開始時間",
                value=f"**{format_datetime_gmt8(meeting.started_at)}**",
                inline=True
            )
            
            if meeting.duration_minutes:
                end_time = meeting.started_at + timedelta(minutes=meeting.duration_minutes)
                embed.add_field(
                    name="⏱️ 預計結束",
                    value=f"**{format_datetime_gmt8(end_time)}**",
                    inline=True
                )
            
            # Send to announcement channel
            if meeting.announcement_channel_id:
                channel = guild.get_channel(meeting.announcement_channel_id)
                if channel:
                    await channel.send(embed=embed)
            
            # DM the organizer and all relevant attendees
            dm_recipients = set()
            
            # Always notify the organizer
            dm_recipients.add(meeting.organizer_id)
            
            # Notify attendees based on their status
            for attendee in meeting.attendees:
                # Send to those who are attending or still pending (they might want to know it started)
                if attendee.status in ['attending', 'pending']:
                    dm_recipients.add(attendee.user_id)
            
            # Send DMs
            for user_id in dm_recipients:
                try:
                    member = guild.get_member(user_id)
                    if member:
                        # Create personalized message
                        personal_embed = embed.copy()
                        if user_id == meeting.organizer_id:
                            personal_embed.description = f"您主辦的會議 **{meeting.title}** 現在開始了！"
                        else:
                            personal_embed.description = f"會議 **{meeting.title}** 現在開始了！快來參與吧！"
                        
                        await member.send(embed=personal_embed)
                        self.logger.info(f"Sent meeting start DM to user {user_id}")
                except discord.Forbidden:
                    self.logger.debug(f"Cannot send DM to user {user_id} - DMs disabled")
                except Exception as e:
                    self.logger.error(f"Error sending meeting start DM to {user_id}: {e}")
                        
        except Exception as e:
            self.logger.error(f"Error notifying meeting started {meeting.id}: {e}")
    
    async def _notify_meeting_cancelled(self, meeting: Meeting):
        """Notify attendees that meeting was cancelled."""
        try:
            guild = self.bot.get_guild(meeting.guild_id)
            if not guild:
                return
            
            embed = discord.Embed(
                title="❌ 會議已取消",
                description=f"**{meeting.title}** 已被主辦人取消。",
                color=discord.Color.red(),
                timestamp=get_current_time_gmt8()
            )
            
            embed.add_field(
                name="📅 原定時間",
                value=f"**{format_datetime_gmt8(meeting.scheduled_time)}**",
                inline=True
            )
            
            embed.add_field(
                name="👤 主辦人",
                value=f"<@{meeting.organizer_id}>",
                inline=True
            )
            
            # Send to announcement channel
            if meeting.announcement_channel_id:
                channel = guild.get_channel(meeting.announcement_channel_id)
                if channel:
                    await channel.send(embed=embed)
            
            # DM attendees
            for attendee in meeting.attendees:
                try:
                    member = guild.get_member(attendee.user_id)
                    if member:
                        await member.send(embed=embed)
                except discord.Forbidden:
                    pass  # User has DMs disabled
                except Exception as e:
                    self.logger.error(f"Error sending meeting cancel DM to {attendee.user_id}: {e}")
                    
        except Exception as e:
            self.logger.error(f"Error notifying meeting cancelled {meeting.id}: {e}")
    
    async def _cleanup_voice_channel(self, voice_channel_id: int):
        """Clean up voice channel after meeting ends/cancels."""
        try:
            # Stop recording first if still active
            recording_module = self.bot.modules.get('recording')
            if recording_module:
                await recording_module.stop_recording(voice_channel_id)
            
            # Add delay before cleanup
            await asyncio.sleep(self.config.meetings.voice_channel_delete_delay)
            
            channel = self.bot.get_channel(voice_channel_id)
            if channel and isinstance(channel, discord.VoiceChannel):
                # Only delete if empty
                if not channel.members:
                    await channel.delete(reason="Meeting ended/cancelled")
                    self.logger.info(f"Deleted voice channel {voice_channel_id}")
                    
        except Exception as e:
            self.logger.error(f"Error cleaning up voice channel {voice_channel_id}: {e}")
    
    async def _cleanup_text_channel(self, text_channel_id: int):
        """Clean up text channel after meeting ends/cancels."""
        try:
            # Add delay before cleanup
            await asyncio.sleep(self.config.meetings.voice_channel_delete_delay)
            
            channel = self.bot.get_channel(text_channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                await channel.delete(reason="Meeting ended/cancelled")
                self.logger.info(f"Deleted text channel {text_channel_id}")
                    
        except Exception as e:
            self.logger.error(f"Error cleaning up text channel {text_channel_id}: {e}")


class MeetingManagementView(discord.ui.View):
    """View for meeting management buttons."""
    
    def __init__(self, meeting: Meeting, manager: MeetingManager):
        super().__init__(timeout=300)  # 5 minutes
        self.meeting = meeting
        self.manager = manager
        
        # Add buttons based on meeting status
        if meeting.status == 'scheduled':
            self.add_item(StartMeetingButton())
            self.add_item(CancelMeetingButton())
        elif meeting.status == 'started':
            self.add_item(EndMeetingButton())
            self.add_item(CancelMeetingButton())
    
    async def on_timeout(self):
        """Disable all buttons when view times out."""
        for item in self.children:
            item.disabled = True


class StartMeetingButton(discord.ui.Button):
    """Button to start a meeting."""
    
    def __init__(self):
        super().__init__(label="🚀 開始會議", style=discord.ButtonStyle.green)
    
    async def callback(self, interaction: discord.Interaction):
        """Start the meeting."""
        await interaction.response.defer(ephemeral=True)
        
        view = self.view
        success = await view.manager.start_meeting(str(view.meeting.id))
        if success:
            await interaction.followup.send("✅ 會議已開始！語音頻道已創建。", ephemeral=True)
        else:
            await interaction.followup.send("❌ 開始會議失敗，請稍後再試。", ephemeral=True)


class EndMeetingButton(discord.ui.Button):
    """Button to end a meeting."""
    
    def __init__(self):
        super().__init__(label="🔴 結束會議", style=discord.ButtonStyle.secondary)
    
    async def callback(self, interaction: discord.Interaction):
        """End the meeting."""
        await interaction.response.defer(ephemeral=True)
        
        view = self.view
        success = await view.manager.end_meeting(str(view.meeting.id))
        if success:
            await interaction.followup.send("✅ 會議已結束！錄製已停止。", ephemeral=True)
            # Disable all buttons
            for item in view.children:
                item.disabled = True
        else:
            await interaction.followup.send("❌ 結束會議失敗，請稍後再試。", ephemeral=True)


class CancelMeetingButton(discord.ui.Button):
    """Button to cancel a meeting."""
    
    def __init__(self):
        super().__init__(label="❌ 取消會議", style=discord.ButtonStyle.red)
    
    async def callback(self, interaction: discord.Interaction):
        """Cancel the meeting."""
        await interaction.response.defer(ephemeral=True)
        
        view = self.view
        success = await view.manager.cancel_meeting(str(view.meeting.id), interaction.user.id)
        if success:
            await interaction.followup.send("✅ 會議已取消，參與者將收到通知。", ephemeral=True)
            # Disable all buttons
            for item in view.children:
                item.disabled = True
        else:
            await interaction.followup.send("❌ 取消會議失敗，請確認你是會議主辦人。", ephemeral=True) 
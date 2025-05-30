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
                timestamp=datetime.utcnow()
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
            meeting.cancelled_at = datetime.utcnow()
            meeting.save()
            
            # Cancel reminders
            from .reminder_service import ReminderService
            reminder_service = ReminderService(self.bot, self.config)
            await reminder_service.cancel_meeting_reminders(meeting_id)
            
            # Notify attendees
            await self._notify_meeting_cancelled(meeting)
            
            # Delete voice channel if exists
            if meeting.voice_channel_id:
                await self._cleanup_voice_channel(meeting.voice_channel_id)
            
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
            meeting.started_at = datetime.utcnow()
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
            meeting.ended_at = datetime.utcnow()
            meeting.save()
            
            # Notify attendees that meeting has ended
            await self._notify_meeting_ended(meeting)
            
            # Clean up voice channel after delay
            if meeting.voice_channel_id:
                await self._cleanup_voice_channel(meeting.voice_channel_id)
            
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
                meeting.recording_stopped_at = datetime.utcnow()
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
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="⏰ 結束時間",
                value=f"**{meeting.ended_at.strftime('%Y/%m/%d %H:%M')}**",
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
        time_str = meeting.scheduled_time.strftime("%Y/%m/%d %H:%M")
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
        """Create a voice channel for the meeting."""
        try:
            # Find meeting category
            category = None
            category_name = self.config.meetings.meeting_category_name
            for cat in guild.categories:
                if cat.name == category_name:
                    category = cat
                    break
            
            if not category:
                # Create category if it doesn't exist
                category = await guild.create_category(category_name)
            
            # Create voice channel
            channel_name = f"🎤 {meeting.title}"
            if len(channel_name) > 100:  # Discord limit
                channel_name = f"🎤 {meeting.title[:90]}..."
            
            voice_channel = await category.create_voice_channel(
                name=channel_name,
                reason=f"Meeting: {meeting.title}"
            )
            
            return voice_channel
            
        except Exception as e:
            self.logger.error(f"Error creating voice channel for meeting {meeting.id}: {e}")
            return None
    
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
                meeting.recording_started_at = datetime.utcnow()
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
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="🔊 語音頻道",
                value=f"{voice_channel.mention}",
                inline=False
            )
            
            embed.add_field(
                name="⏰ 開始時間",
                value=f"**{meeting.started_at.strftime('%Y/%m/%d %H:%M')}**",
                inline=True
            )
            
            if meeting.duration_minutes:
                end_time = meeting.started_at + timedelta(minutes=meeting.duration_minutes)
                embed.add_field(
                    name="⏱️ 預計結束",
                    value=f"**{end_time.strftime('%Y/%m/%d %H:%M')}**",
                    inline=True
                )
            
            # Send to announcement channel
            if meeting.announcement_channel_id:
                channel = guild.get_channel(meeting.announcement_channel_id)
                if channel:
                    await channel.send(embed=embed)
            
            # DM attendees who are marked as attending
            for attendee in meeting.attendees:
                if attendee.status == 'attending':
                    try:
                        member = guild.get_member(attendee.user_id)
                        if member:
                            await member.send(embed=embed)
                    except discord.Forbidden:
                        pass  # User has DMs disabled
                    except Exception as e:
                        self.logger.error(f"Error sending meeting start DM to {attendee.user_id}: {e}")
                        
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
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="📅 原定時間",
                value=f"**{meeting.scheduled_time.strftime('%Y/%m/%d %H:%M')}**",
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
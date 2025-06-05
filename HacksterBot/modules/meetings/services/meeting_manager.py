"""
Meeting Manager - Handles meeting viewing, management, and lifecycle operations.

This service provides functionality for:
- Viewing user meetings
- Managing meeting details
- Meeting reminders and notifications
- Canceling and rescheduling meetings
- Meeting lifecycle management (without voice channel creation)
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
                status='scheduled'
            ).order_by('scheduled_time')
            
            # Get meetings user is attending
            attending_meetings = Meeting.objects(
                guild_id=guild_id,
                status='scheduled',
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
            if meeting.organizer_id == user_id and meeting.status in ['scheduled']:
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
            
            if meeting.status not in ['scheduled']:
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
            
            self.logger.info(f"Meeting {meeting_id} cancelled by user {user_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error cancelling meeting {meeting_id}: {e}")
            return False
    
    async def _notify_meeting_cancelled(self, meeting: Meeting):
        """Notify attendees that meeting has been cancelled."""
        try:
            guild = self.bot.get_guild(meeting.guild_id)
            if not guild:
                return
            
            embed = discord.Embed(
                title="❌ 會議已取消",
                description=f"**{meeting.title}** 已被取消。",
                color=discord.Color.red(),
                timestamp=get_current_time_gmt8()
            )
            
            embed.add_field(
                name="⏰ 原定時間",
                value=f"**{format_datetime_gmt8(meeting.scheduled_time)}**",
                inline=True
            )
            
            embed.add_field(
                name="👤 發起人",
                value=f"<@{meeting.organizer_id}>",
                inline=True
            )
            
            # Send to announcement channel
            if meeting.announcement_channel_id:
                channel = guild.get_channel(meeting.announcement_channel_id)
                if channel:
                    await channel.send(embed=embed)
            
            # Send DM to attendees
            for attendee in meeting.attendees:
                if attendee.status == 'attending':
                    member = guild.get_member(attendee.user_id)
                    if member:
                        try:
                            await member.send(embed=embed)
                        except discord.Forbidden:
                            # Can't send DM to this user
                            pass
            
        except Exception as e:
            self.logger.error(f"Error notifying meeting cancelled {meeting.id}: {e}")
    
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
                name="📝 描述",
                value=meeting.description,
                inline=False
            )
        
        # Attendees
        attendees_text = self._format_attendees(meeting, guild)
        if attendees_text:
            embed.add_field(
                name="👥 參與者",
                value=attendees_text,
                inline=False
            )
        
        # Meeting ID for reference
        embed.set_footer(text=f"會議 ID: {meeting.id}")
        
        return embed
    
    def _format_attendees(self, meeting: Meeting, guild: discord.Guild) -> str:
        """Format attendees list for display."""
        if not meeting.attendees:
            return "無其他參與者"
        
        attending = []
        pending = []
        not_attending = []
        
        for attendee in meeting.attendees:
            member = guild.get_member(attendee.user_id)
            name = member.display_name if member else f"<@{attendee.user_id}>"
            
            if attendee.status == 'attending':
                attending.append(f"✅ {name}")
            elif attendee.status == 'pending':
                pending.append(f"⏳ {name}")
            elif attendee.status == 'not_attending':
                not_attending.append(f"❌ {name}")
        
        result_parts = []
        if attending:
            result_parts.append(f"**參加 ({len(attending)}):** " + ", ".join(attending))
        if pending:
            result_parts.append(f"**待回覆 ({len(pending)}):** " + ", ".join(pending))
        if not_attending:
            result_parts.append(f"**無法參加 ({len(not_attending)}):** " + ", ".join(not_attending))
        
        return "\n".join(result_parts) if result_parts else "無其他參與者"
    
    def _get_status_color(self, status: str) -> discord.Color:
        """Get color for meeting status."""
        color_map = {
            'scheduled': discord.Color.blue(),
            'ended': discord.Color.green(),
            'cancelled': discord.Color.red(),
            'rescheduled': discord.Color.orange()
        }
        return color_map.get(status, discord.Color.gray())


class MeetingManagementView(discord.ui.View):
    """View for meeting management buttons (organizer only)."""
    
    def __init__(self, meeting: Meeting, manager: MeetingManager):
        super().__init__(timeout=300)
        self.meeting = meeting
        self.manager = manager
        
        # Only show cancel button for scheduled meetings
        if meeting.status == 'scheduled':
            self.add_item(CancelMeetingButton())
    
    async def on_timeout(self):
        """Called when the view times out."""
        for item in self.children:
            item.disabled = True


class CancelMeetingButton(discord.ui.Button):
    """Button to cancel a meeting."""
    
    def __init__(self):
        super().__init__(label="取消會議", style=discord.ButtonStyle.danger)
    
    async def callback(self, interaction: discord.Interaction):
        """Handle cancel meeting button click."""
        view = self.view
        meeting = view.meeting
        
        # Verify user is organizer
        if interaction.user.id != meeting.organizer_id:
            await interaction.response.send_message(
                "❌ 只有會議發起人可以取消會議。", 
                ephemeral=True
            )
            return
        
        # Cancel the meeting
        success = await view.manager.cancel_meeting(str(meeting.id), interaction.user.id)
        
        if success:
            await interaction.response.send_message(
                "✅ 會議已成功取消，已通知所有參與者。", 
                ephemeral=True
            )
            # Disable all buttons
            for item in view.children:
                item.disabled = True
            await interaction.edit_original_response(view=view)
        else:
            await interaction.response.send_message(
                "❌ 取消會議失敗，請稍後再試。", 
                ephemeral=True
            ) 
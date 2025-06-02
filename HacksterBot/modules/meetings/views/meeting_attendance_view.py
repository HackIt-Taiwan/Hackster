"""
Meeting attendance view for users to respond to meeting invitations.
"""

import discord
from core.models import Meeting
from ..utils.timezone_utils import format_datetime_gmt8


class MeetingAttendanceView(discord.ui.View):
    """View for meeting attendance responses."""
    
    def __init__(self, meeting_id: str):
        super().__init__(timeout=None)  # Persistent view
        self.meeting_id = meeting_id
    
    @discord.ui.button(label="參加", style=discord.ButtonStyle.green, custom_id="meeting_attend")
    async def attend_meeting(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Mark user as attending the meeting."""
        # Update custom_id with meeting_id
        button.custom_id = f"meeting_attend_{self.meeting_id}"
        await self._update_attendance(interaction, 'attending')
    
    @discord.ui.button(label="無法參加", style=discord.ButtonStyle.red, custom_id="meeting_decline")
    async def decline_meeting(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Mark user as not attending the meeting.""" 
        # Update custom_id with meeting_id
        button.custom_id = f"meeting_decline_{self.meeting_id}"
        
        # Show modal to collect alternative times
        modal = AvailableTimesModal(self.meeting_id)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="會議控制", style=discord.ButtonStyle.gray, custom_id="meeting_control")
    async def show_control_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show control panel for meeting organizer."""
        # Update custom_id with meeting_id
        button.custom_id = f"meeting_control_{self.meeting_id}"
        
        try:
            meeting = Meeting.objects(id=self.meeting_id).first()
            if not meeting:
                await interaction.response.send_message("會議不存在", ephemeral=True)
                return
            
            # Check if user is the organizer
            if interaction.user.id != meeting.organizer_id:
                await interaction.response.send_message(
                    "只有會議發起人可以使用控制面板", ephemeral=True
                )
                return
            
            # Import here to avoid circular import
            from .meeting_control_view import MeetingControlView
            
            # Create control view
            control_view = MeetingControlView(self.meeting_id, meeting.organizer_id)
            
            embed = discord.Embed(
                title="🎛️ 會議控制面板",
                description=f"**{meeting.title}**\n管理您的會議設定",
                color=0x8E8E93
            )
            
            embed.add_field(
                name="⏰ 會議時間",
                value=f"**{format_datetime_gmt8(meeting.scheduled_time)}**",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, view=control_view, ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message("系統錯誤，請稍後再試", ephemeral=True)
    
    async def _update_attendance(self, interaction: discord.Interaction, status: str):
        """Update user's attendance status."""
        try:
            meeting = Meeting.objects(id=self.meeting_id).first()
            if not meeting:
                await interaction.response.send_message(
                    "❌ 找不到該會議。", ephemeral=True
                )
                return
            
            # Check if meeting is full (for attending status)
            if status == 'attending' and meeting.is_full():
                # Check if user is already attending
                current_attendee = meeting.get_attendee(interaction.user.id)
                if not current_attendee or current_attendee.status != 'attending':
                    await interaction.response.send_message(
                        "😔 抱歉，會議已滿員，無法參加。", ephemeral=True
                    )
                    return
            
            # Update attendance
            meeting.add_attendee(
                interaction.user.id,
                interaction.user.display_name,
                status
            )
            meeting.save()
            
            # Create response embed
            status_text = {
                'attending': '✅ 已標記為參加',
                'not_attending': '❌ 已標記為無法參加'
            }
            
            embed = discord.Embed(
                title=status_text[status],
                description=f"您已回應會議：**{meeting.title}**",
                color=self._get_status_color(status)
            )
            
            # Add meeting info
            embed.add_field(
                name="⏰ 時間",
                value=f"**{format_datetime_gmt8(meeting.scheduled_time)}**",
                inline=True
            )
            
            embed.add_field(
                name="👥 目前狀況",
                value=f"{meeting.get_attending_count()} 人確認參加",
                inline=True
            )
            
            # Update the original message with new counts
            try:
                await self._update_announcement_embed(interaction, meeting)
            except:
                pass  # Don't fail if we can't update the announcement
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(
                "❌ 更新出席狀態時發生錯誤。", ephemeral=True
            )
    
    async def _update_announcement_embed(self, interaction: discord.Interaction, meeting):
        """Update the announcement embed with current attendance."""
        try:
            if not meeting.announcement_message_id or not meeting.announcement_channel_id:
                return
            
            channel = interaction.guild.get_channel(meeting.announcement_channel_id)
            if not channel:
                return
            
            message = await channel.fetch_message(meeting.announcement_message_id)
            if not message or not message.embeds:
                return
            
            embed = message.embeds[0]
            
            # Create simplified attendance lists
            attending_list = []
            declined_list = []
            pending_list = []
            
            for attendee in meeting.attendees:
                # Use mention format instead of display name
                mention = f"<@{attendee.user_id}>"
                
                if attendee.status == 'attending':
                    attending_list.append(mention)
                elif attendee.status == 'not_attending':
                    declined_list.append(mention)
                elif attendee.status == 'pending':
                    pending_list.append(mention)
            
            # Build attendance status as three separate fields in a row
            # Clear existing attendance fields first
            for i in range(len(embed.fields) - 1, -1, -1):
                if any(status in embed.fields[i].name for status in ["出席", "無法出席", "待定", "📊"]):
                    embed.remove_field(i)
            
            # Add three fields in a row
            # Attending field
            attending_text = "\n".join(attending_list) if attending_list else "無"
            embed.add_field(
                name=f"出席 ({len(attending_list)})",
                value=attending_text,
                inline=True
            )
            
            # Not attending field  
            declined_text = "\n".join(declined_list) if declined_list else "無"
            embed.add_field(
                name=f"無法出席 ({len(declined_list)})",
                value=declined_text,
                inline=True
            )
            
            # Pending field
            pending_text = "\n".join(pending_list) if pending_list else "無"
            embed.add_field(
                name=f"待定 ({len(pending_list)})",
                value=pending_text,
                inline=True
            )
            
            await message.edit(embed=embed)
            
        except Exception as e:
            print(f"Error updating announcement embed: {e}")
    
    def _get_status_color(self, status: str) -> discord.Color:
        """Get color for attendance status."""
        colors = {
            'attending': discord.Color.green(),
            'not_attending': discord.Color.red()
        }
        return colors.get(status, discord.Color.blue())


class AvailableTimesModal(discord.ui.Modal):
    """Modal for collecting user's alternative available times when declining."""
    
    def __init__(self, meeting_id: str):
        super().__init__(title="提供其他有空時間")
        self.meeting_id = meeting_id
        
        self.available_times_input = discord.ui.TextInput(
            label="您其他有空的時間",
            placeholder="請詳細描述您有空的時間，例如：\n• 週一到週三晚上7-9點\n• 週六下午任何時間\n• 下週二上午10點後",
            style=discord.TextStyle.long,
            max_length=1000,
            required=True
        )
        self.add_item(self.available_times_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Process the available times and mark as not attending."""
        try:
            meeting = Meeting.objects(id=self.meeting_id).first()
            if not meeting:
                await interaction.response.send_message("會議不存在", ephemeral=True)
                return
            
            # Update attendance with available times
            meeting.add_attendee(
                interaction.user.id,
                interaction.user.display_name,
                'not_attending',
                self.available_times_input.value.strip()
            )
            meeting.save()
            
            # Create response embed
            embed = discord.Embed(
                title="❌ 已標記為無法參加",
                description=f"您已回應會議：**{meeting.title}**\n\n您的其他有空時間已記錄，會議發起人修改時間時會參考這些資訊。",
                color=discord.Color.red()
            )
            
            embed.add_field(
                name="⏰ 會議時間",
                value=f"**{format_datetime_gmt8(meeting.scheduled_time)}**",
                inline=True
            )
            
            embed.add_field(
                name="📝 您提供的有空時間",
                value=f"```\n{self.available_times_input.value.strip()}\n```",
                inline=False
            )
            
            # Update the original message with new counts
            try:
                from .meeting_attendance_view import MeetingAttendanceView
                view = MeetingAttendanceView(str(meeting.id))
                await view._update_announcement_embed(interaction, meeting)
            except:
                pass  # Don't fail if we can't update the announcement
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(
                "❌ 更新出席狀態時發生錯誤。", ephemeral=True
            ) 
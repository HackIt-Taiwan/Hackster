"""
Apple-style meeting attendance view with real-time attendance updates.
"""

import discord
from core.models import Meeting


class MeetingAttendanceView(discord.ui.View):
    """Persistent view for meeting attendance responses with Apple-style design."""
    
    def __init__(self, meeting_id: str):
        super().__init__(timeout=None)  # Persistent view
        self.meeting_id = meeting_id
        
        # Add control panel button - will be shown/hidden based on user
        self.control_button = discord.ui.Button(
            label="🎛️ 會議控制",
            style=discord.ButtonStyle.gray,
            custom_id=f"meeting_control_{meeting_id}"
        )
        self.control_button.callback = self.show_control_panel
        self.add_item(self.control_button)
    
    @discord.ui.button(label="參加", style=discord.ButtonStyle.green)
    async def attend_meeting(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Mark user as attending."""
        # Set custom_id for persistence
        if not button.custom_id:
            button.custom_id = f"meeting_attend_{self.meeting_id}"
        await self._update_attendance(interaction, 'attending')
    
    @discord.ui.button(label="無法參加", style=discord.ButtonStyle.red)
    async def decline_meeting(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Mark user as not attending."""
        # Set custom_id for persistence
        if not button.custom_id:
            button.custom_id = f"meeting_decline_{self.meeting_id}"
        await self._update_attendance(interaction, 'not_attending')
    
    async def _update_attendance(self, interaction: discord.Interaction, status: str):
        """Update user's attendance status with real-time message updates."""
        try:
            meeting = Meeting.objects(id=self.meeting_id).first()
            if not meeting:
                await interaction.response.send_message(
                    "會議不存在", ephemeral=True
                )
                return
            
            # Check if meeting is full (for attending status)
            if status == 'attending' and meeting.is_full():
                current_attendee = meeting.get_attendee(interaction.user.id)
                if not current_attendee or current_attendee.status != 'attending':
                    await interaction.response.send_message(
                        "會議已滿員", ephemeral=True
                    )
                    return
            
            # Update attendance
            meeting.add_attendee(
                interaction.user.id,
                interaction.user.display_name,
                status
            )
            meeting.save()
            
            # Update the original announcement message with new attendance list
            await self._update_announcement_embed(interaction, meeting)
            
            # Create Apple-style response
            status_config = {
                'attending': {'emoji': '✓', 'text': '已確認參加', 'color': 0x34C759},
                'not_attending': {'emoji': '✗', 'text': '已標記無法參加', 'color': 0xFF3B30}
            }
            
            config = status_config[status]
            embed = discord.Embed(
                description=f"{config['emoji']} {config['text']}",
                color=config['color']
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(
                "更新失敗，請稍後再試", ephemeral=True
            )
    
    async def _update_announcement_embed(self, interaction: discord.Interaction, meeting: Meeting):
        """Update the original announcement message with real-time attendance list."""
        if not meeting.announcement_message_id or not meeting.announcement_channel_id:
            return
        
        try:
            channel = interaction.guild.get_channel(meeting.announcement_channel_id)
            if not channel:
                return
            
            message = await channel.fetch_message(meeting.announcement_message_id)
            if not message or not message.embeds:
                return
            
            # Get current embed and update it
            embed = message.embeds[0]
            
            # Create comprehensive attendance lists
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
            
            # Build comprehensive attendance display
            attendance_text = ""
            
            # 參加者 (綠色圓點)
            if attending_list:
                attendance_text += f"🟢 **參加** ({len(attending_list)})\n"
                shown_attending = attending_list[:6]  # Show up to 6 names
                attendance_text += "・".join(shown_attending)
                if len(attending_list) > 6:
                    attendance_text += f" 等 {len(attending_list)} 人"
                attendance_text += "\n\n"
            
            # 不出席者 (紅色圓點)
            if declined_list:
                attendance_text += f"🔴 **不出席** ({len(declined_list)})\n"
                shown_declined = declined_list[:6]  # Show up to 6 names
                attendance_text += "・".join(shown_declined)
                if len(declined_list) > 6:
                    attendance_text += f" 等 {len(declined_list)} 人"
                attendance_text += "\n\n"
            
            # 待回覆者 (黃色圓點)
            if pending_list:
                attendance_text += f"🟡 **待回覆** ({len(pending_list)})\n"
                shown_pending = pending_list[:6]  # Show up to 6 names
                attendance_text += "・".join(shown_pending)
                if len(pending_list) > 6:
                    attendance_text += f" 等 {len(pending_list)} 人"
            
            # If no one has responded yet
            if not attendance_text.strip():
                attendance_text = "尚無回覆"
            
            # Find and update attendance field or add it
            attendance_field_found = False
            for i, field in enumerate(embed.fields):
                if "參與狀況" in field.name or "出席" in field.name:
                    embed.set_field_at(i, name="👥 出席狀況", value=attendance_text, inline=False)
                    attendance_field_found = True
                    break
            
            if not attendance_field_found:
                # Remove old participant count field if exists and add new attendance field
                new_fields = []
                for field in embed.fields:
                    if "參與狀況" not in field.name and "出席" not in field.name:
                        new_fields.append((field.name, field.value, field.inline))
                
                # Rebuild embed with new attendance field
                embed.clear_fields()
                for name, value, inline in new_fields:
                    embed.add_field(name=name, value=value, inline=inline)
                embed.add_field(name="👥 出席狀況", value=attendance_text, inline=False)
            
            await message.edit(embed=embed, view=self)
            
        except Exception as e:
            # Silently fail - not critical
            pass 

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check interaction and hide/show control button based on organizer status."""
        try:
            meeting = Meeting.objects(id=self.meeting_id).first()
            if not meeting:
                return False
            
            # Hide control button for non-organizers
            if interaction.user.id != meeting.organizer_id:
                self.control_button.disabled = True
                self.control_button.style = discord.ButtonStyle.gray
            else:
                self.control_button.disabled = False
                self.control_button.style = discord.ButtonStyle.secondary
            
            return True
        except Exception:
            return False
    
    async def show_control_panel(self, interaction: discord.Interaction):
        """Show the meeting control panel (organizer only)."""
        try:
            meeting = Meeting.objects(id=self.meeting_id).first()
            if not meeting:
                await interaction.response.send_message("會議不存在", ephemeral=True)
                return
            
            # Check if user is organizer
            if interaction.user.id != meeting.organizer_id:
                await interaction.response.send_message("只有會議發起人可以使用此功能", ephemeral=True)
                return
            
            # Import here to avoid circular import
            from .meeting_control_view import MeetingControlView
            
            # Create control panel view
            control_view = MeetingControlView(self.meeting_id, meeting.organizer_id)
            
            # Create embed for control panel
            embed = discord.Embed(
                title="🎛️ 會議控制面板",
                description=f"**{meeting.title}**\n\n請選擇要執行的操作：",
                color=0x007AFF
            )
            embed.add_field(
                name="📅 會議時間",
                value=f"<t:{int(meeting.scheduled_time.timestamp())}:F>",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, view=control_view, ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message("無法開啟控制面板，請稍後再試", ephemeral=True) 
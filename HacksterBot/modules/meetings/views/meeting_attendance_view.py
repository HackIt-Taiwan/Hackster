"""
Meeting attendance view for users to respond to meeting invitations.
"""

import discord
from core.models import Meeting


class MeetingAttendanceView(discord.ui.View):
    """View for meeting attendance responses."""
    
    def __init__(self, meeting_id: str):
        super().__init__(timeout=None)  # Persistent view
        self.meeting_id = meeting_id
    
    @discord.ui.button(label="✅ 我會參加", style=discord.ButtonStyle.green, emoji="✅")
    async def attend_meeting(self, interaction: discord.Interaction, 
                           button: discord.ui.Button):
        """Mark user as attending."""
        await self._update_attendance(interaction, 'attending')
    
    @discord.ui.button(label="❌ 無法參加", style=discord.ButtonStyle.red, emoji="❌")
    async def decline_meeting(self, interaction: discord.Interaction, 
                            button: discord.ui.Button):
        """Mark user as not attending."""
        await self._update_attendance(interaction, 'not_attending')
    
    @discord.ui.button(label="❓ 可能參加", style=discord.ButtonStyle.secondary, emoji="❓")
    async def maybe_meeting(self, interaction: discord.Interaction, 
                          button: discord.ui.Button):
        """Mark user as maybe attending."""
        await self._update_attendance(interaction, 'maybe')
    
    @discord.ui.button(label="📋 查看出席名單", style=discord.ButtonStyle.primary, emoji="📋")
    async def view_attendees(self, interaction: discord.Interaction, 
                           button: discord.ui.Button):
        """Show attendee list."""
        try:
            meeting = Meeting.objects(id=self.meeting_id).first()
            if not meeting:
                await interaction.response.send_message(
                    "❌ 找不到該會議。", ephemeral=True
                )
                return
            
            embed = await self._create_attendee_list_embed(meeting, interaction.guild)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(
                "❌ 查看出席名單時發生錯誤。", ephemeral=True
            )
    
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
                'not_attending': '❌ 已標記為無法參加',
                'maybe': '❓ 已標記為可能參加'
            }
            
            embed = discord.Embed(
                title=status_text[status],
                description=f"您已回應會議：**{meeting.title}**",
                color=self._get_status_color(status)
            )
            
            # Add meeting info
            embed.add_field(
                name="⏰ 會議時間",
                value=meeting.scheduled_time.strftime('%Y年%m月%d日 %H:%M'),
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
    
    async def _create_attendee_list_embed(self, meeting: Meeting, 
                                        guild: discord.Guild) -> discord.Embed:
        """Create embed showing attendee list."""
        embed = discord.Embed(
            title="📋 會議出席名單",
            description=f"**{meeting.title}**",
            color=discord.Color.blue()
        )
        
        # Categorize attendees
        attending = []
        not_attending = []
        maybe = []
        
        for attendee in meeting.attendees:
            member = guild.get_member(attendee.user_id)
            display_name = member.display_name if member else attendee.username or "未知用戶"
            
            if attendee.status == 'attending':
                attending.append(f"• {display_name}")
            elif attendee.status == 'not_attending':
                not_attending.append(f"• {display_name}")
            elif attendee.status == 'maybe':
                maybe.append(f"• {display_name}")
        
        # Add fields for each category
        if attending:
            embed.add_field(
                name=f"✅ 確認參加 ({len(attending)})",
                value="\n".join(attending) or "無",
                inline=True
            )
        
        if maybe:
            embed.add_field(
                name=f"❓ 可能參加 ({len(maybe)})",
                value="\n".join(maybe) or "無",
                inline=True
            )
        
        if not_attending:
            embed.add_field(
                name=f"❌ 無法參加 ({len(not_attending)})",
                value="\n".join(not_attending) or "無",
                inline=True
            )
        
        # Add meeting info
        embed.add_field(
            name="⏰ 會議時間",
            value=meeting.scheduled_time.strftime('%Y年%m月%d日 %A %H:%M'),
            inline=False
        )
        
        if meeting.max_attendees:
            embed.add_field(
                name="👥 人數限制",
                value=f"{len(attending)}/{meeting.max_attendees} 人",
                inline=True
            )
        
        embed.set_footer(text=f"會議 ID: {meeting.id}")
        
        return embed
    
    async def _update_announcement_embed(self, interaction: discord.Interaction, 
                                       meeting: Meeting):
        """Update the original announcement message with new attendance counts."""
        if not meeting.announcement_message_id or not meeting.announcement_channel_id:
            return
        
        try:
            channel = interaction.guild.get_channel(meeting.announcement_channel_id)
            if not channel:
                return
            
            message = await channel.fetch_message(meeting.announcement_message_id)
            if not message:
                return
            
            # Get current embed and update attendance count
            if message.embeds:
                embed = message.embeds[0]
                
                # Update participant count field
                attending_count = meeting.get_attending_count()
                if meeting.max_attendees:
                    count_text = f"{attending_count}/{meeting.max_attendees} 人"
                else:
                    count_text = f"{attending_count} 人確認參加"
                
                # Find and update the participant field
                for i, field in enumerate(embed.fields):
                    if field.name == "👥 參與狀況":
                        embed.set_field_at(i, name="👥 參與狀況", 
                                         value=count_text, inline=True)
                        break
                
                await message.edit(embed=embed)
        
        except Exception:
            # Silently fail - not critical
            pass
    
    def _get_status_color(self, status: str) -> discord.Color:
        """Get color for attendance status."""
        colors = {
            'attending': discord.Color.green(),
            'not_attending': discord.Color.red(),
            'maybe': discord.Color.orange()
        }
        return colors.get(status, discord.Color.blue()) 
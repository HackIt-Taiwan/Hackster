"""
Meeting confirmation view for confirming or modifying meeting details.
"""

import discord
from typing import Dict, Any


class MeetingConfirmationView(discord.ui.View):
    """View for confirming meeting creation."""
    
    def __init__(self, scheduler, meeting_data: Dict[str, Any]):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.scheduler = scheduler
        self.meeting_data = meeting_data
    
    @discord.ui.button(label="✅ 確認建立會議", style=discord.ButtonStyle.green)
    async def confirm_meeting(self, interaction: discord.Interaction, 
                            button: discord.ui.Button):
        """Confirm and create the meeting."""
        try:
            await interaction.response.defer()
            
            # Create the meeting
            meeting = await self.scheduler.create_meeting(
                self.meeting_data, interaction
            )
            
            # Schedule reminders for the meeting
            if hasattr(self.scheduler.bot, 'modules') and 'meetings' in self.scheduler.bot.modules:
                meetings_module = self.scheduler.bot.modules['meetings']
                if meetings_module.reminder_service:
                    await meetings_module.reminder_service.schedule_meeting_reminders(meeting)
                    self.scheduler.logger.info(f"Reminders scheduled for meeting {meeting.id}")
            
            # Announce the meeting
            announcement_msg = await self.scheduler.announce_meeting(
                meeting, interaction
            )
            
            # Update confirmation message
            embed = discord.Embed(
                title="✅ 會議已建立！",
                description=f"會議 **{meeting.title}** 已成功建立並發布。",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="📅 會議 ID",
                value=f"`{meeting.id}`",
                inline=True
            )
            
            if announcement_msg:
                embed.add_field(
                    name="📢 公告訊息",
                    value=f"[點擊查看]({announcement_msg.jump_url})",
                    inline=True
                )
            
            embed.add_field(
                name="⏰ 提醒設置",
                value="系統將在會議前 24 小時和 5 分鐘自動發送提醒",
                inline=False
            )
            
            # Disable all buttons
            for item in self.children:
                item.disabled = True
            
            await interaction.edit_original_response(
                embed=embed, view=self
            )
            
        except Exception as e:
            self.scheduler.logger.error(f"Meeting creation failed: {e}")
            
            embed = discord.Embed(
                title="❌ 建立會議失敗",
                description="建立會議時發生錯誤，請稍後再試。",
                color=discord.Color.red()
            )
            
            if hasattr(e, 'message'):
                embed.set_footer(text=f"錯誤: {e.message}")
            
            await interaction.edit_original_response(embed=embed, view=None)
    
    @discord.ui.button(label="✏️ 修改時間", style=discord.ButtonStyle.secondary)
    async def modify_time(self, interaction: discord.Interaction, 
                         button: discord.ui.Button):
        """Show modal to modify meeting time."""
        modal = TimeModificationModal(self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="👥 查看參與者", style=discord.ButtonStyle.secondary)
    async def view_participants(self, interaction: discord.Interaction, 
                              button: discord.ui.Button):
        """Show detailed participant list."""
        participants = self.meeting_data.get('participants', [])
        
        if not participants:
            embed = discord.Embed(
                title="👥 參與者列表",
                description="🌐 這是一個公開會議，所有人都可以參加。",
                color=discord.Color.blue()
            )
        else:
            embed = discord.Embed(
                title="👥 參與者列表",
                description=f"共邀請了 {len(participants)} 位參與者：",
                color=discord.Color.blue()
            )
            
            participants_text = ""
            for i, participant in enumerate(participants, 1):
                participants_text += f"{i}. {participant.display_name} ({participant.mention})\n"
            
            if len(participants_text) > 1024:
                # Split into multiple fields if too long
                chunks = [participants_text[i:i+1024] 
                         for i in range(0, len(participants_text), 1024)]
                for i, chunk in enumerate(chunks):
                    field_name = "參與者" if i == 0 else f"參與者 (續 {i+1})"
                    embed.add_field(name=field_name, value=chunk, inline=False)
            else:
                embed.add_field(name="參與者", value=participants_text, inline=False)
        
        # Add organizer info
        organizer = self.meeting_data['organizer']
        embed.add_field(
            name="👤 會議發起人",
            value=f"{organizer.display_name} ({organizer.mention})",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.red)
    async def cancel_meeting(self, interaction: discord.Interaction, 
                           button: discord.ui.Button):
        """Cancel meeting creation."""
        embed = discord.Embed(
            title="❌ 已取消",
            description="會議建立已取消。",
            color=discord.Color.red()
        )
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def on_timeout(self):
        """Handle view timeout."""
        embed = discord.Embed(
            title="⏰ 操作逾時",
            description="會議確認已逾時，請重新執行 `/meet` 指令。",
            color=discord.Color.orange()
        )
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        # Try to edit the message (might fail if interaction is old)
        try:
            # Note: We need a way to get the original message
            # This is a limitation of discord.py views
            pass
        except:
            pass


class TimeModificationModal(discord.ui.Modal, title="修改會議時間"):
    """Modal for modifying meeting time."""
    
    def __init__(self, parent_view: MeetingConfirmationView):
        super().__init__()
        self.parent_view = parent_view
    
    new_time = discord.ui.TextInput(
        label="新的會議時間",
        placeholder="例如：明天下午3點，週五早上10點",
        default="",
        max_length=100,
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle time modification submission."""
        try:
            await interaction.response.defer()
            
            # Parse the new time
            time_result = await self.parent_view.scheduler.time_parser.parse_time(
                self.new_time.value,
                interaction.user.id,
                interaction.guild.id
            )
            
            if not time_result.get('parsed_time') or time_result.get('confidence', 0) < 50:
                # Time parsing failed
                embed = discord.Embed(
                    title="❌ 時間解析失敗",
                    description=f"無法解析時間：**{self.new_time.value}**",
                    color=discord.Color.red()
                )
                
                if time_result.get('confidence', 0) > 0:
                    embed.add_field(
                        name="🔍 解析結果",
                        value=f"信心度: {time_result['confidence']}%\n"
                              f"解釋為: {time_result.get('interpreted_as', '未知')}",
                        inline=False
                    )
                
                embed.add_field(
                    name="💡 建議格式",
                    value="• 明天下午2點\n• 週五早上10點\n• 1月25日晚上7點",
                    inline=False
                )
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Update meeting data
            self.parent_view.meeting_data.update({
                'time_str': self.new_time.value,
                'parsed_time': time_result['parsed_time'],
                'interpreted_as': time_result['interpreted_as'],
                'confidence': time_result['confidence'],
                'ambiguous': time_result.get('ambiguous', False),
                'suggestions': time_result.get('suggestions', [])
            })
            
            # Update the confirmation embed
            embed = self.parent_view.scheduler._create_confirmation_embed(
                self.parent_view.meeting_data
            )
            
            embed.add_field(
                name="✅ 時間已更新",
                value=f"會議時間已更新為：**{time_result['interpreted_as']}**",
                inline=False
            )
            
            await interaction.edit_original_response(embed=embed, view=self.parent_view)
            
        except Exception as e:
            self.parent_view.scheduler.logger.error(f"Time modification failed: {e}")
            
            embed = discord.Embed(
                title="❌ 修改失敗",
                description="修改會議時間時發生錯誤。",
                color=discord.Color.red()
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True) 
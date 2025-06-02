"""
Apple-style meeting control view for meeting organizers.
"""

import discord
from datetime import datetime, timedelta
from core.models import Meeting
from typing import Optional
from ..utils.timezone_utils import format_datetime_gmt8


class MeetingControlView(discord.ui.View):
    """Persistent view for meeting control by organizers only."""
    
    def __init__(self, meeting_id: str, organizer_id: int):
        super().__init__(timeout=None)  # Persistent view
        self.meeting_id = meeting_id
        self.organizer_id = organizer_id
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if user is the meeting organizer."""
        if interaction.user.id != self.organizer_id:
            await interaction.response.send_message(
                "只有會議發起人可以使用此功能", ephemeral=True
            )
            return False
        return True
    
    @discord.ui.button(label="新增與會人員", style=discord.ButtonStyle.primary, custom_id="add_attendees")
    async def add_attendees(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Add new attendees to the meeting."""
        # Update custom_id with meeting_id
        button.custom_id = f"add_attendees_{self.meeting_id}"
        
        modal = AddAttendeesModal(self.meeting_id)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="修改時間", style=discord.ButtonStyle.secondary, custom_id="reschedule")
    async def reschedule_meeting(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Reschedule the meeting."""
        # Update custom_id with meeting_id
        button.custom_id = f"reschedule_{self.meeting_id}"
        
        try:
            meeting = Meeting.objects(id=self.meeting_id).first()
            if not meeting:
                await interaction.response.send_message("會議不存在", ephemeral=True)
                return
            
            # Check if there are attendees who can't attend with available times
            unavailable_with_times = []
            for attendee in meeting.attendees:
                if attendee.status == 'not_attending' and attendee.available_times:
                    unavailable_with_times.append(attendee)
            
            # If there are unavailable attendees with alternative times, show AI recommendations
            if unavailable_with_times:
                await self._show_time_recommendations(interaction, meeting, unavailable_with_times)
            else:
                # No unavailable attendees or no alternative times provided, show normal modal
                modal = RescheduleMeetingModal(self.meeting_id)
                await interaction.response.send_modal(modal)
                
        except Exception as e:
            await interaction.response.send_message("系統錯誤，請稍後再試", ephemeral=True)
    
    @discord.ui.button(label="取消會議", style=discord.ButtonStyle.danger, custom_id="cancel_meeting")
    async def cancel_meeting(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel the meeting."""
        # Update custom_id with meeting_id
        button.custom_id = f"cancel_meeting_{self.meeting_id}"
        view = CancelConfirmationView(self.meeting_id)
        embed = discord.Embed(
            title="確認取消會議",
            description="確定要取消這個會議嗎？\n此操作無法撤銷，所有參與者將收到通知。",
            color=0xFF3B30
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    async def _show_time_recommendations(self, interaction: discord.Interaction, meeting, unavailable_attendees):
        """Show AI-recommended times based on unavailable attendees' availability."""
        # Send processing message
        processing_embed = discord.Embed(
            title="🤖 AI正在分析最佳時間...",
            description="正在根據無法出席用戶的有空時間推薦最合適的替代時間",
            color=0x8E8E93
        )
        await interaction.response.send_message(embed=processing_embed, ephemeral=True)
        
        try:
            # Get the meetings module to access the time advisor
            meetings_module = interaction.client.modules.get('meetings')
            if not meetings_module:
                await interaction.edit_original_response(
                    embed=discord.Embed(title="❌ 系統錯誤", description="找不到會議模組", color=0xFF3B30)
                )
                return
            
            # Initialize time advisor if needed
            if not hasattr(meetings_module, 'time_advisor'):
                from ..agents.meeting_time_advisor import MeetingTimeAdvisor
                meetings_module.time_advisor = MeetingTimeAdvisor(interaction.client, meetings_module.config)
                await meetings_module.time_advisor.initialize()
            
            # Get AI recommendations
            from datetime import datetime
            current_time = datetime.now()
            recommendations = await meetings_module.time_advisor.recommend_times(meeting, current_time)
            
            if not recommendations:
                # Fall back to manual input
                await interaction.edit_original_response(
                    embed=discord.Embed(
                        title="⚠️ 無法生成推薦時間",
                        description="AI無法分析最佳時間，請手動輸入新時間",
                        color=0xFF9500
                    )
                )
                
                # Show manual input modal after a delay
                import asyncio
                await asyncio.sleep(2)
                modal = RescheduleMeetingModal(self.meeting_id)
                await interaction.followup.send_modal(modal)
                return
            
            # Show unavailable attendees' times and AI recommendations
            embed = discord.Embed(
                title="📋 無法出席用戶的其他有空時間",
                description="🤖 AI正在分析以下時間安排，為您推薦最佳替代方案",
                color=0x007AFF
            )
            
            # Add unavailable attendees' available times in vertical layout
            for i, attendee in enumerate(unavailable_attendees[:5], 1):  # Show up to 5 users
                username = attendee.username or f"用戶{attendee.user_id}"
                available_times = attendee.available_times[:200] + ('...' if len(attendee.available_times) > 200 else '')
                
                embed.add_field(
                    name=f"🙋‍♂️ {username}",
                    value=f"```\n{available_times}\n```",
                    inline=False
                )
            
            if len(unavailable_attendees) > 5:
                embed.add_field(
                    name="📊 統計",
                    value=f"共有 **{len(unavailable_attendees)}** 位用戶提供了其他有空時間",
                    inline=False
                )
            
            # Add AI analysis
            if recommendations.get('analysis'):
                embed.add_field(
                    name="🤖 AI分析",
                    value=recommendations['analysis'],
                    inline=False
                )
            
            # Create view with recommendations
            view = TimeRecommendationView(self.meeting_id, recommendations)
            
            await interaction.edit_original_response(embed=embed, view=view)
            
        except Exception as e:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="❌ 分析失敗",
                    description="無法分析最佳時間，請手動輸入新時間",
                    color=0xFF3B30
                )
            )


class AddAttendeesModal(discord.ui.Modal):
    """Modal for adding attendees to a meeting."""
    
    def __init__(self, meeting_id: str):
        super().__init__(title="新增與會人員")
        self.meeting_id = meeting_id
        
        self.attendees_input = discord.ui.TextInput(
            label="與會人員",
            placeholder="請輸入用戶名稱或ID，用空格分隔",
            style=discord.TextStyle.long,
            max_length=1000,
            required=True
        )
        self.add_item(self.attendees_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Process the attendee addition."""
        try:
            meeting = Meeting.objects(id=self.meeting_id).first()
            if not meeting:
                await interaction.response.send_message("會議不存在", ephemeral=True)
                return
            
            # Parse attendees
            attendee_inputs = self.attendees_input.value.strip().split()
            added_count = 0
            failed_list = []
            
            for attendee_input in attendee_inputs:
                # Try to find member by mention, username, or ID
                member = None
                
                # Remove mention brackets if present
                if attendee_input.startswith('<@') and attendee_input.endswith('>'):
                    user_id = attendee_input.strip('<@!>')
                    try:
                        member = interaction.guild.get_member(int(user_id))
                    except ValueError:
                        pass
                else:
                    # Try by username or ID
                    try:
                        member = interaction.guild.get_member(int(attendee_input))
                    except ValueError:
                        # Search by username
                        for m in interaction.guild.members:
                            if (m.name.lower() == attendee_input.lower() or 
                                m.display_name.lower() == attendee_input.lower()):
                                member = m
                                break
                
                if member:
                    # Check if already added
                    existing = meeting.get_attendee(member.id)
                    if not existing:
                        meeting.add_attendee(member.id, member.display_name, 'pending')
                        added_count += 1
                else:
                    failed_list.append(attendee_input)
            
            if added_count > 0:
                meeting.save()
            
            # Create response
            embed = discord.Embed(color=0x34C759 if added_count > 0 else 0xFF3B30)
            
            if added_count > 0:
                embed.description = f"✓ 成功新增 {added_count} 位與會人員"
            
            if failed_list:
                if added_count > 0:
                    embed.description += f"\n\n找不到以下用戶：\n{', '.join(failed_list)}"
                else:
                    embed.description = f"找不到指定的用戶：\n{', '.join(failed_list)}"
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # Update announcement message if attendees were added
            if added_count > 0:
                await self._update_announcement(interaction, meeting)
            
        except Exception as e:
            await interaction.response.send_message("新增失敗，請稍後再試", ephemeral=True)
    
    async def _update_announcement(self, interaction: discord.Interaction, meeting: Meeting):
        """Update the announcement message with new attendees."""
        try:
            if not meeting.announcement_message_id or not meeting.announcement_channel_id:
                return
            
            channel = interaction.guild.get_channel(meeting.announcement_channel_id)
            if not channel:
                return
            
            message = await channel.fetch_message(meeting.announcement_message_id)
            if not message or not message.embeds:
                return
            
            # Import here to avoid circular import
            from .meeting_attendance_view import MeetingAttendanceView
            view = MeetingAttendanceView(str(meeting.id))
            
            # Update attendance display
            await view._update_announcement_embed(interaction, meeting)
            
        except Exception:
            pass


class RescheduleMeetingModal(discord.ui.Modal):
    """Modal for rescheduling a meeting."""
    
    def __init__(self, meeting_id: str):
        super().__init__(title="修改會議時間")
        self.meeting_id = meeting_id
        
        self.time_input = discord.ui.TextInput(
            label="新的會議時間",
            placeholder="例如：明天下午2點、2024/12/25 14:30、下週五晚上8點",
            style=discord.TextStyle.short,
            max_length=200,
            required=True
        )
        self.add_item(self.time_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Process the meeting rescheduling."""
        try:
            meeting = Meeting.objects(id=self.meeting_id).first()
            if not meeting:
                await interaction.response.send_message("會議不存在", ephemeral=True)
                return
            
            # Send initial "processing" message
            processing_embed = discord.Embed(
                title="⏳ 正在處理中...",
                description="正在解析時間並更新會議，請稍候",
                color=0x8E8E93
            )
            await interaction.response.send_message(embed=processing_embed, ephemeral=True)
            
            # Parse the new time using the AI time parser
            try:
                # Get the meetings module to access the time parser
                meetings_module = interaction.client.modules.get('meetings')
                if not meetings_module:
                    # Delete processing message and show error
                    await interaction.delete_original_response()
                    await interaction.followup.send("系統錯誤：找不到會議模組", ephemeral=True)
                    return
                
                # Use the scheduler's time parser
                time_parser = await meetings_module.scheduler._get_time_parser()
                if not time_parser:
                    # Delete processing message and show error
                    await interaction.delete_original_response()
                    await interaction.followup.send("AI 時間解析服務不可用", ephemeral=True)
                    return
                
                # Parse the time expression
                parsed_result = await time_parser.parse_time(
                    self.time_input.value,
                    interaction.user.id,
                    interaction.guild.id
                )
                
                # Check if parsing was successful
                if not parsed_result.get('parsed_time') or parsed_result.get('confidence', 0) < 50:
                    error_msg = "無法解析時間格式，請使用更明確的時間表達"
                    if parsed_result.get('error'):
                        error_msg += f"\n錯誤詳情：{parsed_result['error']}"
                    
                    embed = discord.Embed(
                        title="⚠️ 時間解析失敗",
                        description=error_msg,
                        color=0xFF3B30
                    )
                    embed.add_field(
                        name="建議格式",
                        value="• 明天下午2點\n• 週五早上10點\n• 12/25 14:30\n• 下週三晚上7點",
                        inline=False
                    )
                    
                    # Delete processing message and show error
                    await interaction.delete_original_response()
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                # Parse the datetime string
                from datetime import datetime
                new_time = datetime.fromisoformat(parsed_result['parsed_time'])
                
                # Check if new time is in the future
                from datetime import datetime
                import pytz
                
                # Get timezone from config
                tz = pytz.timezone(meetings_module.config.meetings.default_timezone)
                now = datetime.now(tz)
                
                # Convert new_time to timezone-aware if needed
                if new_time.tzinfo is None:
                    new_time = tz.localize(new_time)
                
                if new_time <= now:
                    # Delete processing message and show error
                    await interaction.delete_original_response()
                    await interaction.followup.send(
                        "⚠️ 會議時間必須在未來", ephemeral=True
                    )
                    return
                
                # Save old time and update meeting
                old_time = meeting.scheduled_time
                meeting.scheduled_time = new_time
                meeting.save()
                
                # Create success response and replace processing message
                embed = discord.Embed(
                    title="✓ 會議時間已更新",
                    color=0x34C759
                )
                embed.add_field(
                    name="原時間",
                    value=f"**{old_time.strftime('%Y/%m/%d %H:%M')}**",
                    inline=False
                )
                embed.add_field(
                    name="新時間", 
                    value=f"**{new_time.strftime('%Y/%m/%d %H:%M')}**",
                    inline=False
                )
                
                if parsed_result.get('confidence', 0) < 90:
                    embed.add_field(
                        name="📝 解析說明",
                        value=f"AI 解析：{parsed_result.get('interpreted_as', '時間已更新')} (信心度: {parsed_result.get('confidence', 0)}%)",
                        inline=False
                    )
                
                # Edit the processing message to show success, then auto-delete after 3 seconds
                await interaction.edit_original_response(embed=embed)
                
                # Auto-delete the success message after 3 seconds
                import asyncio
                await asyncio.sleep(3)
                try:
                    await interaction.delete_original_response()
                except:
                    pass  # Ignore if already deleted
                
                # Notify attendees and update announcement
                await self._notify_reschedule(interaction, meeting, old_time, new_time)
                
            except Exception as e:
                error_embed = discord.Embed(
                    title="❌ 時間解析失敗",
                    description="請使用更明確的時間格式，例如：\n• 明天下午2點\n• 12/25 14:30\n• 下週五晚上8點",
                    color=0xFF3B30
                )
                error_embed.set_footer(text=f"錯誤詳情：{str(e)}")
                
                # Delete processing message and show error
                await interaction.delete_original_response()
                await interaction.followup.send(embed=error_embed, ephemeral=True)
                
        except Exception as e:
            # Fallback error message
            try:
                await interaction.delete_original_response()
                await interaction.followup.send("修改失敗，請稍後再試", ephemeral=True)
            except:
                pass
    
    async def _notify_reschedule(self, interaction: discord.Interaction, meeting: Meeting, old_time: datetime, new_time: datetime):
        """Notify attendees about the reschedule."""
        try:
            # Update announcement message
            if meeting.announcement_message_id and meeting.announcement_channel_id:
                channel = interaction.guild.get_channel(meeting.announcement_channel_id)
                if channel:
                    try:
                        message = await channel.fetch_message(meeting.announcement_message_id)
                        if message and message.embeds:
                            embed = message.embeds[0]
                            
                            # Update time field
                            for i, field in enumerate(embed.fields):
                                if "時間" in field.name:
                                    embed.set_field_at(
                                        i, 
                                        name=field.name,
                                        value=f"**{new_time.strftime('%Y/%m/%d %H:%M')}**",
                                        inline=field.inline
                                    )
                                    break
                            
                            await message.edit(embed=embed)
                    except Exception:
                        pass
            
            # Send notification message
            notify_embed = discord.Embed(
                title="⏰ 會議時間已更改",
                description=f"**{meeting.title}** 的時間已被更改",
                color=0xFF9500
            )
            notify_embed.add_field(
                name="原時間",
                value=f"**{old_time.strftime('%Y/%m/%d %H:%M')}**",
                inline=True
            )
            notify_embed.add_field(
                name="新時間",
                value=f"**{new_time.strftime('%Y/%m/%d %H:%M')}**",
                inline=True
            )
            
            if meeting.announcement_channel_id:
                channel = interaction.guild.get_channel(meeting.announcement_channel_id)
                if channel:
                    await channel.send(embed=notify_embed)
            
        except Exception:
            pass


class CancelConfirmationView(discord.ui.View):
    """Confirmation view for meeting cancellation."""
    
    def __init__(self, meeting_id: str):
        super().__init__(timeout=60)  # 1 minute timeout
        self.meeting_id = meeting_id
    
    @discord.ui.button(label="確認取消", style=discord.ButtonStyle.red)
    async def confirm_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Confirm meeting cancellation."""
        try:
            # Get meeting manager from the meetings module
            meetings_module = interaction.client.modules.get('meetings')
            if not meetings_module:
                await interaction.response.send_message("系統錯誤", ephemeral=True)
                return
            
            success = await meetings_module.meeting_manager.cancel_meeting(
                self.meeting_id, interaction.user.id
            )
            
            if success:
                embed = discord.Embed(
                    description="✓ 會議已取消",
                    color=0xFF3B30
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
                # Disable all buttons
                for item in self.children:
                    item.disabled = True
                await interaction.edit_original_response(view=self)
            else:
                await interaction.response.send_message("取消失敗，請稍後再試", ephemeral=True)
                
        except Exception as e:
            await interaction.response.send_message("取消失敗，請稍後再試", ephemeral=True)
    
    @discord.ui.button(label="保持會議", style=discord.ButtonStyle.secondary)
    async def keep_meeting(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Keep the meeting (cancel the cancellation)."""
        embed = discord.Embed(
            description="會議保持不變",
            color=0x8E8E93
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        # Delete the confirmation message
        try:
            await interaction.delete_original_response()
        except:
            pass


class TimeRecommendationView(discord.ui.View):
    """View for showing AI-recommended meeting times."""
    
    def __init__(self, meeting_id: str, recommendations: dict):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.meeting_id = meeting_id
        self.recommendations = recommendations
        
        # Add select menu for recommendations
        if recommendations.get('recommendations'):
            self.add_item(TimeRecommendationSelect(meeting_id, recommendations['recommendations']))
        
        # Add "Other Time" button
        self.add_item(CustomTimeButton(meeting_id))
    
    async def on_timeout(self):
        """Disable all items when view times out."""
        for item in self.children:
            item.disabled = True


class TimeRecommendationSelect(discord.ui.Select):
    """Select menu for AI-recommended meeting times."""
    
    def __init__(self, meeting_id: str, recommendations: list):
        self.meeting_id = meeting_id
        
        # Create options from recommendations
        options = []
        weekdays = ['週一', '週二', '週三', '週四', '週五', '週六', '週日']
        
        for i, rec in enumerate(recommendations, 1):
            try:
                dt = datetime.fromisoformat(rec['datetime'])
                # Convert to GMT+8 for display
                gmt8_dt = format_datetime_gmt8(dt, "%Y/%m/%d %H:%M")
                weekday = weekdays[dt.weekday()]
                confidence = rec.get('confidence', 0)
                reason = rec['reason'][:10]  # Limit to 10 characters as requested
                
                options.append(discord.SelectOption(
                    label=f"{gmt8_dt} ({weekday})",
                    value=rec['datetime'],
                    description=reason,
                    emoji="⭐"
                ))
            except:
                continue
        
        super().__init__(
            placeholder="選擇AI推薦的會議時間...",
            options=options,
            custom_id=f"time_recommendation_select_{meeting_id}"
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle time selection."""
        try:
            selected_time = self.values[0]
            
            # Process the time update
            await self._update_meeting_time(interaction, selected_time)
            
        except Exception as e:
            await interaction.response.send_message("時間更新失敗，請稍後再試", ephemeral=True)
    
    async def _update_meeting_time(self, interaction: discord.Interaction, new_time_str: str):
        """Update the meeting time and notify attendees."""
        try:
            meeting = Meeting.objects(id=self.meeting_id).first()
            if not meeting:
                await interaction.response.send_message("會議不存在", ephemeral=True)
                return
            
            # Parse new time
            from datetime import datetime
            import pytz
            new_time = datetime.fromisoformat(new_time_str)
            
            # Ensure timezone aware
            meetings_module = interaction.client.modules.get('meetings')
            if meetings_module:
                tz = pytz.timezone(meetings_module.config.meetings.default_timezone)
                if new_time.tzinfo is None:
                    new_time = tz.localize(new_time)
            
            # Save old time and update
            old_time = meeting.scheduled_time
            meeting.scheduled_time = new_time
            meeting.save()
            
            # Create success response
            embed = discord.Embed(
                title="✅ 會議時間已更新",
                description="根據AI推薦，會議時間已成功更新",
                color=0x34C759
            )
            embed.add_field(
                name="原時間",
                value=f"**{old_time.strftime('%Y/%m/%d %H:%M')}**",
                inline=True
            )
            embed.add_field(
                name="新時間",
                value=f"**{new_time.strftime('%Y/%m/%d %H:%M')}**",
                inline=True
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # Clean up the recommendation message
            try:
                await interaction.delete_original_response()
            except:
                pass
            
            # Notify attendees
            await self._notify_reschedule(interaction, meeting, old_time, new_time)
            
        except Exception as e:
            await interaction.response.send_message("時間更新失敗，請稍後再試", ephemeral=True)
    
    async def _notify_reschedule(self, interaction: discord.Interaction, meeting: Meeting, old_time: datetime, new_time: datetime):
        """Notify attendees about the reschedule (same as in RescheduleMeetingModal)."""
        try:
            # Update announcement message
            if meeting.announcement_message_id and meeting.announcement_channel_id:
                channel = interaction.guild.get_channel(meeting.announcement_channel_id)
                if channel:
                    try:
                        message = await channel.fetch_message(meeting.announcement_message_id)
                        if message and message.embeds:
                            embed = message.embeds[0]
                            
                            # Update time field
                            for i, field in enumerate(embed.fields):
                                if "時間" in field.name:
                                    embed.set_field_at(
                                        i, 
                                        name=field.name,
                                        value=f"**{new_time.strftime('%Y/%m/%d %H:%M')}**",
                                        inline=field.inline
                                    )
                                    break
                            
                            await message.edit(embed=embed)
                    except Exception:
                        pass
            
            # Send notification message
            notify_embed = discord.Embed(
                title="⏰ 會議時間已更改",
                description=f"**{meeting.title}** 的時間已根據AI推薦更改",
                color=0xFF9500
            )
            notify_embed.add_field(
                name="原時間",
                value=f"**{old_time.strftime('%Y/%m/%d %H:%M')}**",
                inline=True
            )
            notify_embed.add_field(
                name="新時間",
                value=f"**{new_time.strftime('%Y/%m/%d %H:%M')}**",
                inline=True
            )
            
            if meeting.announcement_channel_id:
                channel = interaction.guild.get_channel(meeting.announcement_channel_id)
                if channel:
                    await channel.send(embed=notify_embed)
            
        except Exception:
            pass


class CustomTimeButton(discord.ui.Button):
    """Button for manual time input."""
    
    def __init__(self, meeting_id: str):
        super().__init__(
            label="其他時間",
            style=discord.ButtonStyle.secondary,
            custom_id=f"custom_time_{meeting_id}",
            emoji="⏰"
        )
        self.meeting_id = meeting_id
    
    async def callback(self, interaction: discord.Interaction):
        """Show manual time input modal."""
        modal = RescheduleMeetingModal(self.meeting_id)
        await interaction.response.send_modal(modal) 
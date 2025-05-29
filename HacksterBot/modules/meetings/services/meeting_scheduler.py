"""
Meeting scheduler service for handling meeting requests and creating meetings.
"""

import re
from datetime import datetime, timedelta
from typing import List, Optional
import discord
import pytz
from discord.ext import commands
from core.models import Meeting, MeetingAttendee
from ..views.meeting_confirmation_view import MeetingConfirmationView


class MeetingScheduler:
    """Service for scheduling meetings."""
    
    def __init__(self, bot, config, time_parser):
        self.bot = bot
        self.config = config
        self.time_parser = time_parser
        self.logger = bot.logger
        self.timezone = pytz.timezone(config.meetings.default_timezone)
        
    async def handle_meeting_request(self, interaction: discord.Interaction,
                                   time_str: str, participants_str: str,
                                   title: str = None, description: str = None,
                                   max_attendees: int = None):
        """
        Handle a meeting scheduling request.
        
        Args:
            interaction: Discord interaction
            time_str: Natural language time expression
            participants_str: Participants string (mentions or "公開")
            title: Meeting title (optional)
            description: Meeting description (optional)
            max_attendees: Maximum number of attendees (optional)
        """
        await interaction.response.defer()
        
        try:
            # Parse time expression
            time_result = await self.time_parser.parse_time(
                time_str, interaction.user.id, interaction.guild.id
            )
            
            if not time_result.get('parsed_time') or time_result.get('confidence', 0) < 50:
                await self._handle_time_parse_failure(interaction, time_result)
                return
            
            # Parse participants
            participants = await self._parse_participants(interaction, participants_str)
            
            # Generate title if not provided
            if not title:
                title = await self._generate_meeting_title(interaction, participants)
            
            # Create meeting confirmation
            meeting_data = {
                'time_str': time_str,
                'parsed_time': time_result['parsed_time'],
                'interpreted_as': time_result['interpreted_as'],
                'confidence': time_result['confidence'],
                'ambiguous': time_result.get('ambiguous', False),
                'suggestions': time_result.get('suggestions', []),
                'participants': participants,
                'title': title,
                'description': description,
                'max_attendees': max_attendees,
                'organizer': interaction.user
            }
            
            # Show confirmation view
            view = MeetingConfirmationView(self, meeting_data)
            embed = self._create_confirmation_embed(meeting_data)
            
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            self.logger.error(f"Meeting request handling failed: {e}")
            await interaction.followup.send(
                "❌ 處理會議請求時發生錯誤，請稍後再試。",
                ephemeral=True
            )
    
    async def _handle_time_parse_failure(self, interaction: discord.Interaction, 
                                       time_result: dict):
        """Handle failed time parsing."""
        confidence = time_result.get('confidence', 0)
        error = time_result.get('error', '')
        
        if confidence > 0:
            # Low confidence, show suggestions
            embed = discord.Embed(
                title="🤔 時間解析信心度較低",
                description=f"我對您輸入的時間 **{time_result.get('interpreted_as', '未知')}** 的理解信心度只有 {confidence}%",
                color=discord.Color.orange()
            )
            
            if time_result.get('suggestions'):
                suggestions_text = "\n".join([
                    f"• {self._format_datetime(s)}" 
                    for s in time_result['suggestions'][:3]
                ])
                embed.add_field(
                    name="💡 可能的選項",
                    value=suggestions_text,
                    inline=False
                )
        else:
            # Complete failure
            embed = discord.Embed(
                title="❌ 無法解析時間",
                description="抱歉，我無法理解您輸入的時間格式。",
                color=discord.Color.red()
            )
        
        embed.add_field(
            name="📝 建議格式",
            value="• 明天下午2點\n• 週五早上10點\n• 1月25日晚上7點\n• 後天中午12點",
            inline=False
        )
        
        if error:
            embed.set_footer(text=f"錯誤詳情: {error}")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def _parse_participants(self, interaction: discord.Interaction, 
                                participants_str: str) -> List[discord.Member]:
        """Parse participants from string."""
        participants = []
        
        # Check for public meeting
        if participants_str.lower() in ['公開', 'public', '所有人', 'everyone']:
            return []  # Empty list means public meeting
        
        # Extract mentions
        mention_pattern = r'<@!?(\d+)>'
        user_ids = re.findall(mention_pattern, participants_str)
        
        for user_id in user_ids:
            try:
                member = interaction.guild.get_member(int(user_id))
                if member and member != interaction.user:  # Don't include organizer
                    participants.append(member)
            except:
                continue
        
        return participants
    
    async def _generate_meeting_title(self, interaction: discord.Interaction,
                                    participants: List[discord.Member]) -> str:
        """Generate a meeting title based on participants."""
        if not participants:
            return f"{interaction.user.display_name} 的公開會議"
        
        if len(participants) == 1:
            return f"{interaction.user.display_name} 與 {participants[0].display_name} 的會議"
        elif len(participants) <= 3:
            names = [p.display_name for p in participants]
            return f"{interaction.user.display_name} 與 {', '.join(names)} 的會議"
        else:
            return f"{interaction.user.display_name} 的小組會議 ({len(participants)+1} 人)"
    
    def _create_confirmation_embed(self, meeting_data: dict) -> discord.Embed:
        """Create meeting confirmation embed."""
        embed = discord.Embed(
            title="📅 會議確認",
            description="請確認以下會議資訊：",
            color=discord.Color.blue()
        )
        
        # Time information
        time_text = f"**{meeting_data['interpreted_as']}**"
        if meeting_data['confidence'] < 90:
            time_text += f" (信心度: {meeting_data['confidence']}%)"
        
        embed.add_field(
            name="⏰ 時間",
            value=time_text,
            inline=True
        )
        
        # Participants
        participants = meeting_data['participants']
        if not participants:
            participants_text = "🌐 公開會議"
        elif len(participants) <= 5:
            participants_text = "\n".join([f"• {p.display_name}" for p in participants])
        else:
            participants_text = f"• {len(participants)} 位參與者\n（點擊查看詳情按鈕查看完整列表）"
        
        embed.add_field(
            name="👥 參與者",
            value=participants_text,
            inline=True
        )
        
        # Meeting details
        embed.add_field(
            name="📝 標題",
            value=meeting_data['title'],
            inline=False
        )
        
        if meeting_data['description']:
            embed.add_field(
                name="📋 描述",
                value=meeting_data['description'],
                inline=False
            )
        
        if meeting_data['max_attendees']:
            embed.add_field(
                name="👥 最大人數",
                value=f"{meeting_data['max_attendees']} 人",
                inline=True
            )
        
        # Organizer
        organizer = meeting_data['organizer']
        embed.set_footer(
            text=f"會議發起人: {organizer.display_name}",
            icon_url=organizer.display_avatar.url
        )
        
        # Warnings for ambiguous time
        if meeting_data.get('ambiguous'):
            embed.add_field(
                name="⚠️ 注意",
                value="時間可能有多種解釋，請仔細確認",
                inline=False
            )
        
        return embed
    
    async def create_meeting(self, meeting_data: dict, 
                           interaction: discord.Interaction) -> Meeting:
        """
        Create a confirmed meeting.
        
        Args:
            meeting_data: Meeting information
            interaction: Discord interaction
            
        Returns:
            Created Meeting object
        """
        try:
            # Parse scheduled time
            scheduled_time = datetime.fromisoformat(meeting_data['parsed_time'])
            
            # Create meeting document
            meeting = Meeting(
                guild_id=interaction.guild.id,
                organizer_id=interaction.user.id,
                title=meeting_data['title'],
                description=meeting_data.get('description'),
                scheduled_time=scheduled_time,
                timezone=self.config.meetings.default_timezone,
                max_attendees=meeting_data.get('max_attendees'),
                recording_enabled=self.config.meetings.auto_start_recording
            )
            
            # Add organizer as attendee
            meeting.add_attendee(
                interaction.user.id, 
                interaction.user.display_name, 
                'attending'
            )
            
            # Add invited participants
            participants = meeting_data.get('participants', [])
            for participant in participants:
                meeting.add_attendee(
                    participant.id,
                    participant.display_name,
                    'pending'
                )
            
            # Save meeting
            meeting.save()
            
            self.logger.info(f"Meeting created: {meeting.id} by {interaction.user.id}")
            
            return meeting
            
        except Exception as e:
            self.logger.error(f"Failed to create meeting: {e}")
            raise
    
    async def announce_meeting(self, meeting: Meeting, 
                             interaction: discord.Interaction) -> discord.Message:
        """
        Announce the meeting in the designated channel.
        
        Args:
            meeting: Meeting object
            interaction: Discord interaction
            
        Returns:
            Announcement message
        """
        try:
            # Determine announcement channel
            if self.config.meetings.announcement_channel_id:
                channel = interaction.guild.get_channel(
                    self.config.meetings.announcement_channel_id
                )
            else:
                channel = interaction.channel
            
            if not channel:
                channel = interaction.channel
            
            # Create announcement embed
            embed = self._create_announcement_embed(meeting, interaction.guild)
            
            # Create announcement view (for attendance)
            from ..views.meeting_attendance_view import MeetingAttendanceView
            view = MeetingAttendanceView(meeting.id)
            
            # Send announcement
            message = await channel.send(embed=embed, view=view)
            
            # Update meeting with announcement info
            meeting.announcement_message_id = message.id
            meeting.announcement_channel_id = channel.id
            meeting.save()
            
            self.logger.info(f"Meeting announced: {meeting.id} in {channel.id}")
            
            return message
            
        except Exception as e:
            self.logger.error(f"Failed to announce meeting: {e}")
            raise
    
    def _create_announcement_embed(self, meeting: Meeting, 
                                 guild: discord.Guild) -> discord.Embed:
        """Create meeting announcement embed."""
        embed = discord.Embed(
            title="📅 新會議邀請",
            description=f"**{meeting.title}**",
            color=discord.Color.green()
        )
        
        # Time information
        local_time = meeting.scheduled_time.replace(
            tzinfo=pytz.timezone(meeting.timezone)
        )
        time_str = local_time.strftime('%Y年%m月%d日 %A %H:%M')
        
        embed.add_field(
            name="⏰ 時間",
            value=time_str,
            inline=True
        )
        
        # Organizer
        organizer = guild.get_member(meeting.organizer_id)
        organizer_name = organizer.display_name if organizer else "未知用戶"
        
        embed.add_field(
            name="👤 發起人",
            value=organizer_name,
            inline=True
        )
        
        # Attendee count
        attending_count = meeting.get_attending_count()
        total_invited = len(meeting.attendees)
        
        if meeting.max_attendees:
            count_text = f"{attending_count}/{meeting.max_attendees} 人"
        else:
            count_text = f"{attending_count} 人確認參加"
        
        embed.add_field(
            name="👥 參與狀況",
            value=count_text,
            inline=True
        )
        
        # Description
        if meeting.description:
            embed.add_field(
                name="📋 描述",
                value=meeting.description,
                inline=False
            )
        
        # Meeting ID for reference
        embed.set_footer(text=f"會議 ID: {meeting.id}")
        
        return embed
    
    def _format_datetime(self, datetime_str: str) -> str:
        """Format datetime string for display."""
        try:
            dt = datetime.fromisoformat(datetime_str)
            return dt.strftime('%Y年%m月%d日 %H:%M')
        except:
            return datetime_str 
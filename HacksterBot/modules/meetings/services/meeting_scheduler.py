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
from ..views.meeting_attendance_view import MeetingAttendanceView
from ..utils.timezone_utils import format_datetime_gmt8


class MeetingScheduler:
    """Service for scheduling meetings."""
    
    def __init__(self, bot, config):
        self.bot = bot
        self.config = config
        self.time_parser = None  # Will be initialized when needed
        self.logger = bot.logger
        self.timezone = pytz.timezone(config.meetings.default_timezone)
        
    async def _get_time_parser(self):
        """Get or create time parser agent."""
        if not self.time_parser:
            from ..agents.time_parser import TimeParserAgent
            
            # Create time parser with correct parameters
            self.time_parser = TimeParserAgent(self.bot, self.config)
            
            # Initialize the time parser
            await self.time_parser.initialize()
        
        return self.time_parser
    
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
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Parse time expression
            time_parser = await self._get_time_parser()
            if not time_parser:
                await interaction.followup.send(
                    "❌ AI時間解析服務不可用，請稍後再試。",
                    ephemeral=True
                )
                return
                
            time_result = await time_parser.parse_time(
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
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
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
        
        # Time information - use parsed time instead of interpreted_as to avoid encoding issues
        try:
            parsed_time = datetime.fromisoformat(meeting_data['parsed_time'])
            time_text = f"**{format_datetime_gmt8(parsed_time)}**"
        except:
            # Fallback to interpreted_as if parsing fails
            time_text = f"**{meeting_data.get('interpreted_as', '時間解析錯誤')}**"
            
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
            self.logger.debug(f"Creating meeting with data: {meeting_data}")
            
            # Parse scheduled time
            scheduled_time = datetime.fromisoformat(meeting_data['parsed_time'])
            self.logger.debug(f"Parsed scheduled time: {scheduled_time}")
            
            # Create meeting document
            self.logger.debug("Creating Meeting object...")
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
            self.logger.debug("Meeting object created successfully")
            
            # Add organizer as attendee
            self.logger.debug("Adding organizer as attendee...")
            meeting.add_attendee(
                interaction.user.id, 
                interaction.user.display_name, 
                'attending'  # Organizer is attending by default
            )
            self.logger.debug("Organizer added successfully")
            
            # Add invited participants as pending
            participants = meeting_data.get('participants', [])
            self.logger.debug(f"Adding {len(participants)} participants...")
            for participant in participants:
                meeting.add_attendee(
                    participant.id,
                    participant.display_name,
                    'pending'  # All invited participants default to pending
                )
            self.logger.debug("All participants added successfully")
            
            # Save meeting
            self.logger.debug("Saving meeting to database...")
            meeting.save()
            self.logger.debug(f"Meeting saved successfully with ID: {meeting.id}")
            
            # Log meeting creation
            self.logger.info(f"Meeting created: {meeting.id} by {interaction.user.id}")
            
            return meeting
            
        except Exception as e:
            self.logger.error(f"Failed to create meeting: {e}")
            self.logger.error(f"Meeting data: {meeting_data}")
            raise
    
    async def announce_meeting(self, meeting: Meeting, 
                             interaction: discord.Interaction) -> discord.Message:
        """
        Announce the meeting with Apple-style design and dual views.
        
        Args:
            meeting: Meeting object to announce
            interaction: Discord interaction
            
        Returns:
            The announcement message
        """
        try:
            self.logger.debug(f"Starting meeting announcement for meeting {meeting.id}")
            
            # Determine announcement channel
            if self.config.meetings.announcement_channel_id:
                channel = interaction.guild.get_channel(
                    self.config.meetings.announcement_channel_id
                )
            else:
                channel = interaction.channel
            
            if not channel:
                channel = interaction.channel
            
            self.logger.debug(f"Announcement channel determined: {channel.id}")
            
            # Create the announcement embed
            embed = discord.Embed(
                title=f"📅 {meeting.title}",
                description=meeting.description or "點擊下方按鈕來回應出席狀況",
                color=0x007AFF
            )
            
            embed.add_field(
                name="🕐 時間",
                value=f"**{format_datetime_gmt8(meeting.scheduled_time)}**",
                inline=True
            )
            
            embed.add_field(
                name="👤 發起人",
                value=f"<@{meeting.organizer_id}>",
                inline=True
            )
            
            # Only show location if the meeting has this attribute
            if hasattr(meeting, 'location') and meeting.location:
                embed.add_field(
                    name="📍 地點", 
                    value=meeting.location,
                    inline=True
                )
            else:
                # Add empty field to force new line
                embed.add_field(
                    name="\u200b",  # Invisible character
                    value="\u200b",
                    inline=True
                )
            
            # Add initial attendance status - simplified three-column format
            # Count attendees by status
            attending_count = 0
            pending_count = 0
            declined_count = 0
            
            attending_list = []
            pending_list = []
            
            for attendee in meeting.attendees:
                mention = f"<@{attendee.user_id}>"
                if attendee.status == 'attending':
                    attending_count += 1
                    attending_list.append(mention)
                elif attendee.status == 'pending':
                    pending_count += 1
                    pending_list.append(mention)
                elif attendee.status == 'not_attending':
                    declined_count += 1
            
            # Add three fields in a row for attendance
            embed.add_field(
                name=f"出席 ({attending_count})",
                value="\n".join(attending_list) if attending_list else "無",
                inline=True
            )
            
            embed.add_field(
                name=f"無法出席 ({declined_count})",
                value="無",
                inline=True
            )
            
            embed.add_field(
                name=f"待定 ({pending_count})",
                value="\n".join(pending_list) if pending_list else "無",
                inline=True
            )
            
            # Create attendance view
            view = MeetingAttendanceView(str(meeting.id))
            
            # Send the announcement
            announcement_msg = await channel.send(embed=embed, view=view)
            
            # Store announcement message info
            meeting.announcement_channel_id = channel.id
            meeting.announcement_message_id = announcement_msg.id
            meeting.save()
            
            self.logger.info(f"Meeting announcement published: {meeting.title}")
            return announcement_msg
            
        except Exception as e:
            self.logger.error(f"Failed to publish meeting announcement: {e}")
            return None
    
    def _format_datetime(self, datetime_str: str) -> str:
        """Format datetime string for display."""
        try:
            dt = datetime.fromisoformat(datetime_str)
            return format_datetime_gmt8(dt)
        except:
            return datetime_str 
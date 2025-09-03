"""
MongoEngine models for HacksterBot.
Contains all database models used across different modules.
"""
from datetime import datetime
from mongoengine import (
    Document, EmbeddedDocument, 
    IntField, StringField, ListField, DateTimeField, 
    BooleanField, DictField, FloatField,
    EmbeddedDocumentField
)


class WelcomedMember(Document):
    """
    Model for tracking welcomed members.
    """
    user_id = IntField(required=True)
    guild_id = IntField(required=True)
    username = StringField(required=True, max_length=200)
    join_count = IntField(default=1)
    first_welcomed_at = DateTimeField(default=datetime.utcnow)
    welcome_status = StringField(max_length=20, default='pending', 
                                choices=['pending', 'success', 'failed'])
    retry_count = IntField(default=0)
    last_retry_at = DateTimeField()
    
    meta = {
        'collection': 'welcomed_members',
        'indexes': [
            ('user_id', 'guild_id'),
            'welcome_status',
            'last_retry_at'
        ]
    }
    
    def __str__(self):
        return f"WelcomedMember(user_id={self.user_id}, guild_id={self.guild_id}, status={self.welcome_status})"


class User(Document):
    """
    Model for tracking user information across guilds.
    """
    user_id = IntField(required=True)
    guild_id = IntField(required=True)
    username = StringField(max_length=200)
    first_seen = DateTimeField(default=datetime.utcnow)
    last_violation = DateTimeField()
    
    meta = {
        'collection': 'users',
        'indexes': [
            ('user_id', 'guild_id'),
            'last_violation'
        ]
    }
    
    def __str__(self):
        return f"User(user_id={self.user_id}, guild_id={self.guild_id}, username={self.username})"


class Violation(Document):
    """
    Model for storing moderation violations.
    """
    user_id = IntField(required=True)
    guild_id = IntField(required=True)
    content = StringField()
    violation_categories = ListField(StringField(max_length=100))
    details = DictField()
    created_at = DateTimeField(default=datetime.utcnow)
    
    meta = {
        'collection': 'violations',
        'indexes': [
            ('user_id', 'guild_id'),
            'created_at',
            'violation_categories'
        ]
    }
    
    def __str__(self):
        return f"Violation(user_id={self.user_id}, guild_id={self.guild_id}, categories={self.violation_categories})"


class Mute(Document):
    """
    Model for tracking user mutes.
    """
    user_id = IntField(required=True)
    guild_id = IntField(required=True)
    violation_count = IntField(required=True)
    duration_minutes = IntField()
    started_at = DateTimeField(default=datetime.utcnow)
    expires_at = DateTimeField()
    is_active = BooleanField(default=True)
    deactivated_at = DateTimeField()
    
    meta = {
        'collection': 'mutes',
        'indexes': [
            ('user_id', 'guild_id'),
            'is_active',
            'expires_at',
            'started_at'
        ]
    }
    
    def __str__(self):
        return f"Mute(user_id={self.user_id}, guild_id={self.guild_id}, active={self.is_active})"


class URLBlacklist(Document):
    """
    Model for URL blacklist entries.
    """
    url = StringField(required=True, unique=True, max_length=500)
    domain = StringField(required=True, max_length=200)
    threat_level = FloatField(default=0.0)
    threat_types = ListField(StringField(max_length=100))
    first_detected = DateTimeField(default=datetime.utcnow)
    last_updated = DateTimeField(default=datetime.utcnow)
    detection_count = IntField(default=1)
    is_active = BooleanField(default=True)
    
    meta = {
        'collection': 'url_blacklist',
        'indexes': [
            'url',
            'domain',
            'threat_level',
            'is_active',
            'last_updated'
        ]
    }
    
    def __str__(self):
        return f"URLBlacklist(domain={self.domain}, threat_level={self.threat_level})"


class AIInteraction(Document):
    """
    Model for tracking AI interactions (for analytics and debugging).
    """
    user_id = IntField(required=True)
    guild_id = IntField(required=True)
    channel_id = IntField(required=True)
    module_name = StringField(required=True, max_length=50)
    interaction_type = StringField(required=True, max_length=50)
    prompt = StringField()
    response = StringField()
    model_used = StringField(max_length=100)
    processing_time = FloatField()
    success = BooleanField(default=True)
    error_message = StringField()
    created_at = DateTimeField(default=datetime.utcnow)
    
    meta = {
        'collection': 'ai_interactions',
        'indexes': [
            ('user_id', 'guild_id'),
            'module_name',
            'interaction_type',
            'created_at',
            'success'
        ]
    }
    
    def __str__(self):
        return f"AIInteraction(module={self.module_name}, type={self.interaction_type}, success={self.success})"


class TicketInfo(Document):
    """
    Model for storing ticket information (for backup and analytics).
    """
    channel_id = IntField(required=True, unique=True)
    guild_id = IntField(required=True)
    creator_id = IntField(required=True)
    category = StringField(max_length=100)
    event_name = StringField(max_length=200)
    initial_question = StringField()
    status = StringField(max_length=20, default='open', 
                        choices=['open', 'closed', 'archived'])
    created_at = DateTimeField(default=datetime.utcnow)
    closed_at = DateTimeField()
    messages_count = IntField(default=0)
    participants = ListField(IntField())
    
    meta = {
        'collection': 'tickets',
        'indexes': [
            'channel_id',
            'guild_id',
            'creator_id',
            'status',
            'created_at',
            'category'
        ]
    }
    
    def __str__(self):
        return f"TicketInfo(channel_id={self.channel_id}, category={self.category}, status={self.status})"


class GameStatistics(Document):
    """
    Model for tracking game statistics across different game types.
    """
    user_id = IntField(required=True)
    game_type = StringField(required=True, max_length=50)  # e.g., 'blackjack', 'poker', etc.
    games_played = IntField(default=0)
    games_won = IntField(default=0)
    games_tied = IntField(default=0)
    total_score = IntField(default=0)
    current_streak = IntField(default=0)
    best_streak = IntField(default=0)
    win_rate = FloatField(default=0.0)
    last_played = DateTimeField()
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)
    
    meta = {
        'collection': 'game_statistics',
        'indexes': [
            ('user_id', 'game_type'),
            'total_score',
            'win_rate',
            'games_played',
            'last_played'
        ]
    }
    
    def save(self, *args, **kwargs):
        """Override save to update the updated_at timestamp."""
        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)
    
    def __str__(self):
        return f"GameStatistics(user_id={self.user_id}, game_type={self.game_type}, score={self.total_score})"


class InviteRecord(Document):
    """
    Model for tracking Discord invite usage and statistics.
    """
    invite_code = StringField(required=True, max_length=20)
    guild_id = IntField(required=True)
    inviter_id = IntField(required=True)  # User who created the invite
    invited_user_id = IntField()  # User who joined through this invite
    invited_user_name = StringField(max_length=200)
    joined_at = DateTimeField(default=datetime.utcnow)
    left_at = DateTimeField()  # Set when user leaves
    is_active = BooleanField(default=True)  # False if user left
    invite_created_at = DateTimeField()
    invite_expires_at = DateTimeField()
    invite_max_uses = IntField()
    invite_uses = IntField(default=0)
    
    meta = {
        'collection': 'invite_records',
        'indexes': [
            'invite_code',
            'guild_id',
            ('inviter_id', 'guild_id'),
            'invited_user_id',
            'is_active',
            'joined_at'
        ]
    }
    
    def __str__(self):
        return f"InviteRecord(code={self.invite_code}, inviter={self.inviter_id}, invited={self.invited_user_id})"


class InviteStatistics(Document):
    """
    Model for tracking user invitation statistics.
    """
    user_id = IntField(required=True)
    guild_id = IntField(required=True)
    total_invites = IntField(default=0)  # Total people invited
    active_invites = IntField(default=0)  # People currently in server through their invites
    left_invites = IntField(default=0)   # People who left after being invited
    first_invite_at = DateTimeField()
    last_invite_at = DateTimeField()
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)
    
    meta = {
        'collection': 'invite_statistics',
        'indexes': [
            ('user_id', 'guild_id'),
            'total_invites',
            'active_invites',
            'last_invite_at'
        ]
    }
    
    def save(self, *args, **kwargs):
        """Override save to update timestamp."""
        self.updated_at = datetime.utcnow()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"InviteStatistics(user_id={self.user_id}, total={self.total_invites}, active={self.active_invites})"


class EventTicket(Document):
    """
    Model for tracking event tickets earned through activities.
    """
    user_id = IntField(required=True)
    guild_id = IntField(required=True)
    ticket_type = StringField(required=True, max_length=50)  # e.g., 'invite', 'event', 'special'
    ticket_source = StringField(max_length=100)  # Description of how ticket was earned
    event_name = StringField(max_length=200)  # Associated event name
    earned_at = DateTimeField(default=datetime.utcnow)
    metadata = DictField()  # Additional data about the ticket
    
    meta = {
        'collection': 'event_tickets',
        'indexes': [
            ('user_id', 'guild_id'),
            'ticket_type',
            'event_name',
            'earned_at'
        ]
    }
    
    def __str__(self):
        return f"EventTicket(user_id={self.user_id}, type={self.ticket_type}, event={self.event_name})"


class DailyNotification(Document):
    """
    Model for tracking daily DM notifications to prevent spam.
    """
    user_id = IntField(required=True)
    guild_id = IntField(required=True)
    notification_type = StringField(required=True, max_length=50)  # e.g., 'ticket_reward'
    date = StringField(required=True, max_length=10)  # YYYY-MM-DD format
    count = IntField(default=1)
    last_sent_at = DateTimeField(default=datetime.utcnow)
    
    meta = {
        'collection': 'daily_notifications',
        'indexes': [
            ('user_id', 'guild_id', 'notification_type', 'date'),
            'last_sent_at'
        ]
    }
    
    def __str__(self):
        return f"DailyNotification(user={self.user_id}, type={self.notification_type}, date={self.date})"


class MeetingAttendee(EmbeddedDocument):
    """
    Embedded document for meeting attendees with their status.
    """
    user_id = IntField(required=True)
    username = StringField(max_length=200)
    status = StringField(max_length=20, default='pending',
                        choices=['pending', 'attending', 'not_attending'])
    responded_at = DateTimeField()
    
    def __str__(self):
        return f"Attendee(user_id={self.user_id}, status={self.status})"


class Meeting(Document):
    """
    Model for scheduled meetings.
    """
    guild_id = IntField(required=True)
    organizer_id = IntField(required=True)
    title = StringField(required=True, max_length=200)
    description = StringField(max_length=1000)
    
    # Scheduling information
    scheduled_time = DateTimeField(required=True)
    timezone = StringField(max_length=50, default='Asia/Taipei')
    duration_minutes = IntField(default=60)
    
    # Channel information
    announcement_message_id = IntField()
    announcement_channel_id = IntField()
    
    # Status and management
    status = StringField(max_length=20, default='scheduled',
                        choices=['scheduled', 'ended', 'cancelled', 'rescheduled'])
    
    # Attendees
    attendees = ListField(EmbeddedDocumentField(MeetingAttendee))
    max_attendees = IntField()
    
    # Recording information removed - meetings are reminder-only
    
    # Reminder tracking
    reminder_24h_sent = BooleanField(default=False)
    reminder_5min_sent = BooleanField(default=False)
    
    # Timestamps
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)
    ended_at = DateTimeField()
    cancelled_at = DateTimeField()
    
    # Original meeting reference for rescheduled meetings
    original_meeting_id = StringField()
    
    meta = {
        'collection': 'meetings',
        'indexes': [
            'guild_id',
            'organizer_id',
            'scheduled_time',
            'status',
            'created_at',
            ('guild_id', 'status'),
            ('scheduled_time', 'status'),
            'announcement_message_id'
        ]
    }
    
    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        super().save(*args, **kwargs)
    
    def add_attendee(self, user_id: int, username: str = None, status: str = 'pending'):
        """Add an attendee to the meeting."""
        # Check if attendee already exists
        for attendee in self.attendees:
            if attendee.user_id == user_id:
                attendee.status = status
                attendee.responded_at = datetime.utcnow()
                if username:
                    attendee.username = username
                return
        
        # Add new attendee
        new_attendee = MeetingAttendee(
            user_id=user_id,
            username=username,
            status=status,
            responded_at=datetime.utcnow()
        )
        self.attendees.append(new_attendee)
    
    def get_attendee(self, user_id: int):
        """Get attendee by user ID."""
        for attendee in self.attendees:
            if attendee.user_id == user_id:
                return attendee
        return None
    
    def get_attending_count(self):
        """Get count of users marked as attending."""
        return sum(1 for attendee in self.attendees if attendee.status == 'attending')
    
    def is_full(self):
        """Check if meeting is full."""
        if not self.max_attendees:
            return False
        return self.get_attending_count() >= self.max_attendees
    
    def __str__(self):
        return f"Meeting(title={self.title}, organizer={self.organizer_id}, time={self.scheduled_time}, status={self.status})"


class MeetingReminder(Document):
    """
    Model for tracking meeting reminders.
    """
    meeting_id = StringField(required=True)
    reminder_type = StringField(required=True, max_length=20, 
                               choices=['24h', '5min', 'custom'])
    scheduled_time = DateTimeField(required=True)
    sent_at = DateTimeField()
    is_sent = BooleanField(default=False)
    error_message = StringField()
    retry_count = IntField(default=0)
    
    meta = {
        'collection': 'meeting_reminders',
        'indexes': [
            'meeting_id',
            'scheduled_time',
            'is_sent',
            ('scheduled_time', 'is_sent')
        ]
    }
    
    def __str__(self):
        return f"MeetingReminder(meeting={self.meeting_id}, type={self.reminder_type}, sent={self.is_sent})"


class MeetingParseLog(Document):
    """
    Model for tracking meeting parsing attempts and AI performance.
    """
    user_id = IntField(required=True)
    guild_id = IntField(required=True)
    original_text = StringField(required=True)
    parsed_time = DateTimeField()
    parsed_title = StringField()
    mentioned_users = ListField(IntField())
    ai_model_used = StringField(max_length=100)
    processing_time = FloatField()
    success = BooleanField(default=True)
    error_message = StringField()
    confidence_score = FloatField()
    created_at = DateTimeField(default=datetime.utcnow)
    
    meta = {
        'collection': 'meeting_parse_logs',
        'indexes': [
            ('user_id', 'guild_id'),
            'success',
            'ai_model_used',
            'created_at',
            'confidence_score'
        ]
    }
    
    def __str__(self):
        return f"MeetingParseLog(user={self.user_id}, success={self.success}, model={self.ai_model_used})"


class BridgeResponse(EmbeddedDocument):
    """User response for bridge time sessions."""
    user_id = IntField(required=True)
    username = StringField(max_length=200)
    content = StringField()
    responded_at = DateTimeField(default=datetime.utcnow)


class BridgeSession(Document):
    """Session for collecting available meeting times from multiple users."""
    organizer_id = IntField(required=True)
    guild_id = IntField(required=True)
    channel_id = IntField(required=True)
    message_id = IntField(required=True)
    participant_ids = ListField(IntField())
    responses = ListField(EmbeddedDocumentField(BridgeResponse))
    completed = BooleanField(default=False)
    created_at = DateTimeField(default=datetime.utcnow)
    completed_at = DateTimeField()

    meta = {
        'collection': 'bridge_sessions',
        'indexes': [
            'guild_id',
            'channel_id',
            'message_id',
            'completed'
        ]
    }

    def get_response(self, user_id: int):
        for resp in self.responses:
            if resp.user_id == user_id:
                return resp
        return None


class RegisteredUser(Document):
    """Model for storing user registration information."""

    user_id = IntField(required=True)
    guild_id = IntField(required=True)
    real_name = StringField(required=True, max_length=100)
    email = StringField(required=True, max_length=200)
    source = StringField(max_length=200)
    education_stage = StringField(max_length=50)
    avatar_base64 = StringField()  # Base64 encoded user avatar
    registered_at = DateTimeField(default=datetime.utcnow)

    meta = {
        'collection': 'registered_users',
        'indexes': [
            ('user_id', 'guild_id'),
            'email',
        ]
    }

    def __str__(self):
        return f"RegisteredUser(user_id={self.user_id}, email={self.email})"

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


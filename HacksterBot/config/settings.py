"""
Settings and constants for HacksterBot.
"""
import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = os.getenv("DATA_DIR", "data")
LOGS_DIR = os.getenv("LOGS_DIR", "logs")

# Database paths
MODERATION_DB_PATH = os.path.join(DATA_DIR, "moderation.db")
WELCOME_DB_PATH = os.path.join(DATA_DIR, "welcomed_members.db")
INVITE_DB_PATH = os.path.join(DATA_DIR, "invites.db")

# URL Safety severity levels
URL_SAFETY_SEVERITY_LEVELS = {
    'PHISHING': 5,
    'MALWARE': 4,
    'SCAM': 3,
    'SUSPICIOUS': 2,
    'UNKNOWN': 1
}

# Mute durations (in minutes) based on violation count
MUTE_DURATIONS = {
    1: 5,      # First violation: 5 minutes
    2: 720,    # Second violation: 12 hours
    3: 10080,  # Third violation: 7 days
    4: 10080,  # Fourth violation: 7 days
    5: 40320   # Fifth+ violation: 28 days
}

# Content moderation thresholds
MODERATION_THRESHOLDS = {
    'harassment': 0.8,
    'hate_speech': 0.8,
    'graphic_content': 0.7,
    'self_harm': 0.9,
    'sexual': 0.8,
    'violence': 0.7
}

# Role names and IDs
DEFAULT_MUTE_ROLE_NAME = "Muted"
DEFAULT_STAFF_ROLES = ["Admin", "Moderator", "Staff"]

# Message limits
MAX_MESSAGE_LENGTH = 2000
MAX_EMBED_DESCRIPTION_LENGTH = 4096
MAX_EMBED_FIELD_VALUE_LENGTH = 1024

# File paths
URL_BLACKLIST_FILE = os.path.join(DATA_DIR, "url_blacklist.json")
FAQ_CACHE_FILE = os.path.join(DATA_DIR, "faq_cache.json")

# API rate limits
OPENAI_RATE_LIMIT_REQUESTS_PER_MINUTE = 3500
GEMINI_RATE_LIMIT_REQUESTS_PER_MINUTE = 60
VIRUSTOTAL_RATE_LIMIT_REQUESTS_PER_MINUTE = 4

# Logging configuration
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Discord limits
DISCORD_MAX_EMBED_FIELDS = 25
DISCORD_MAX_EMBEDS_PER_MESSAGE = 10
DISCORD_MAX_COMPONENTS_PER_ROW = 5
DISCORD_MAX_ROWS_PER_MESSAGE = 5

# Ticket system
TICKET_INACTIVITY_HOURS = 48
MAX_TICKETS_PER_USER = 3

# Welcome system - 基於 AIHacker 的配置
WELCOME_MESSAGE_TEMPLATE = "歡迎 {member} 加入我們的伺服器！✨"
WELCOME_MAX_RETRIES = 3
WELCOME_RETRY_INTERVAL_MINUTES = 5

# Invite tracking
INVITE_EXPIRY_DAYS = 30
MAX_INVITES_PER_USER = 10

# Search settings
SEARCH_RESULTS_LIMIT = 5
SEARCH_TIMEOUT_SECONDS = 10

# Cache settings
CACHE_EXPIRY_MINUTES = 30
MAX_CACHE_SIZE = 1000

# Bot information
BOT_NAME = "HacksterBot"
BOT_VERSION = "1.0.0"
BOT_DESCRIPTION = "Modular Discord bot for the HackIt community"

# Rate limiting
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX_MESSAGES = 10

# AI constants
MESSAGE_TYPES = {
    'CHAT': 'chat',
    'SEARCH': 'search', 
    'GENERAL': 'general',
    'UNKNOWN': 'unknown'
}

AI_MAX_RETRIES = 3
AI_RETRY_DELAY = 2  # seconds

# Chat history
CHAT_HISTORY_TARGET_CHARS = 2000
CHAT_HISTORY_MAX_MESSAGES = 10

# URL safety configuration
URL_SAFETY_CHECK_API = os.getenv("URL_SAFETY_CHECK_API", "virustotal").lower()
URL_SAFETY_API_KEY = os.getenv("URL_SAFETY_API_KEY", "")
URL_SAFETY_THRESHOLD = float(os.getenv("URL_SAFETY_THRESHOLD", "0.1"))  # 10% threshold
URL_SAFETY_MAX_RETRIES = int(os.getenv("URL_SAFETY_MAX_RETRIES", "5"))
URL_SAFETY_RETRY_DELAY = int(os.getenv("URL_SAFETY_RETRY_DELAY", "3"))  # seconds
URL_SAFETY_REQUEST_TIMEOUT = int(float(os.getenv("URL_SAFETY_REQUEST_TIMEOUT", "30")))
URL_SAFETY_MAX_URLS = int(os.getenv("URL_SAFETY_MAX_URLS", "10"))

# URL unshortening configuration
URL_UNSHORTEN_ENABLED = os.getenv("URL_UNSHORTEN_ENABLED", "true").lower() == "true"
URL_UNSHORTEN_TIMEOUT = int(os.getenv("URL_UNSHORTEN_TIMEOUT", "15"))
URL_UNSHORTEN_MAX_REDIRECTS = int(os.getenv("URL_UNSHORTEN_MAX_REDIRECTS", "10"))
URL_UNSHORTEN_RETRY_COUNT = int(os.getenv("URL_UNSHORTEN_RETRY_COUNT", "3"))

# URL blacklist configuration
URL_BLACKLIST_ENABLED = os.getenv("URL_BLACKLIST_ENABLED", "true").lower() == "true"
URL_BLACKLIST_FILE = os.path.join(DATA_DIR, "url_blacklist.json")
URL_BLACKLIST_AUTO_DOMAIN = os.getenv("URL_BLACKLIST_AUTO_DOMAIN", "auto-detected")

URL_SAFETY_SEVERITY_LEVELS = {
    'PHISHING': 9,
    'MALWARE': 8,
    'SCAM': 7,
    'SUSPICIOUS': 5,
    'SPAM': 3,
    'BLACKLISTED': 8,
    'UNKNOWN': 5
}

# File paths
EVENTS_CONFIG_FILE = "data/events.json"
USER_DATA_PATH = os.path.join(DATA_DIR, "userdata/")  # For ticket user data files

# Embed colors (in hex)
EMBED_COLORS = {
    'SUCCESS': 0x00FF00,
    'ERROR': 0xFF0000,
    'WARNING': 0xFFFF00,
    'INFO': 0x0099FF,
    'PURPLE': 0x9932CC,
    'ORANGE': 0xFF8C00
}

# FAQ and Question Management
QUESTION_CHANNEL_ID = 0  # Configure in environment variables
QUESTION_RESOLVER_ROLES = []  # Configure in environment variables
QUESTION_EMOJI = "❓"
QUESTION_RESOLVED_EMOJI = "✅"
QUESTION_FAQ_FOUND_EMOJI = "💡"
QUESTION_FAQ_PENDING_EMOJI = "⏳"

# Ticket categories
TICKET_CATEGORIES = [
    {
        "label": "活動諮詢",
        "emoji": "🎯",
        "description": "關於 HackIt 目前/過去舉辦的活動，包括報名問題等"
    },
    {
        "label": "提案活動", 
        "emoji": "💡",
        "description": "向 HackIt 提出你的瘋狂願景，讓我們協助您實現"
    },
    {
        "label": "加入我們",
        "emoji": "🚀", 
        "description": "想加入 HackIt 團隊或成為志工"
    },
    {
        "label": "資源需求",
        "emoji": "🔧",
        "description": "尋求技術支援、教學資源、場地或其他資源協助"
    },
    {
        "label": "贊助合作",
        "emoji": "🤝",
        "description": "企業或組織希望與 HackIt 進行贊助或合作"
    },
    {
        "label": "反饋投訴",
        "emoji": "📝",
        "description": "對 HackIt 活動或服務提出反饋或投訴"
    },
    {
        "label": "其他問題",
        "emoji": "❓",
        "description": "任何其他類別的問題或需求"
    }
]

# Ticket System Configuration
TICKET_CUSTOMER_ID = int(os.getenv("TICKET_CUSTOMER_ID", "1070698736910614559"))
TICKET_DEVELOPER_ID = int(os.getenv("TICKET_DEVELOPER_ID", "1070698621030375504"))
TICKET_ADMIN_ID = int(os.getenv("TICKET_ADMIN_ID", "933349161452044378"))
TICKET_LOG_CHANNEL_ID = int(os.getenv("TICKET_LOG_CHANNEL_ID", "0"))
EVENTS_CONFIG_PATH = os.getenv("EVENTS_CONFIG_PATH", "data/events.json") 
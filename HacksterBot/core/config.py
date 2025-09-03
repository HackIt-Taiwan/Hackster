"""
Configuration management for HacksterBot.
"""
import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

from .exceptions import ConfigError

# Load environment variables
load_dotenv()


@dataclass
class DiscordConfig:
    """Discord-related configuration."""
    token: str
    command_prefix: str = "!"
    intents_message_content: bool = True
    intents_guilds: bool = True
    intents_members: bool = True


@dataclass
class DatabaseConfig:
    """Database configuration."""
    # Legacy SQLite support (deprecated)
    url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///data/hacksterbot.db"))
    echo: bool = field(default_factory=lambda: os.getenv("DATABASE_ECHO", "false").lower() == "true")
    pool_size: int = 5
    max_overflow: int = 10
    
    # MongoDB configuration
    mongodb_uri: str = field(default_factory=lambda: os.getenv("MONGODB_URI", "mongodb://localhost:27017/hacksterbot"))
    mongodb_database: str = field(default_factory=lambda: os.getenv("MONGODB_DATABASE", "hacksterbot"))


@dataclass
class AIConfig:
    """AI service configuration."""
    # Primary model (for main AI features like chat, complex reasoning)
    primary_provider: str = field(default_factory=lambda: os.getenv("PRIMARY_MODEL_PROVIDER", "gemini"))
    primary_model: str = field(default_factory=lambda: os.getenv("PRIMARY_MODEL_NAME", "gemini-2.0-flash"))
    
    # Secondary model (for classification, moderation, simple tasks)
    secondary_provider: str = field(default_factory=lambda: os.getenv("SECONDARY_MODEL_PROVIDER", "gemini"))
    secondary_model: str = field(default_factory=lambda: os.getenv("SECONDARY_MODEL_NAME", "gemini-2.0-flash"))
    
    # Tools configuration
    tools_enabled: bool = field(default_factory=lambda: os.getenv("AGENT_TOOLS_ENABLED", "true").lower() == "true")
    allow_image_generation: bool = field(default_factory=lambda: os.getenv("AGENT_ALLOW_IMAGE_GENERATION", "true").lower() == "true")
    
    # Image generation configuration
    image_generation_enabled: bool = field(default_factory=lambda: os.getenv("IMAGE_GENERATION_ENABLED", "true").lower() == "true")
    image_generation_provider: str = field(default_factory=lambda: os.getenv("IMAGE_GENERATION_PROVIDER", "gemini"))
    image_generation_model: str = field(default_factory=lambda: os.getenv("IMAGE_GENERATION_MODEL", "gemini-2.0-flash"))
    
    # Azure OpenAI
    azure_api_key: Optional[str] = field(default_factory=lambda: os.getenv("AZURE_OPENAI_API_KEY"))
    azure_endpoint: Optional[str] = field(default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT"))
    azure_api_version: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"))
    
    # Google Gemini
    gemini_api_key: Optional[str] = field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))
    
    # OpenAI
    openai_api_key: Optional[str] = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    
    # Anthropic
    anthropic_api_key: Optional[str] = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))


@dataclass
class ModerationConfig:
    """Content moderation configuration."""
    enabled: bool = field(default_factory=lambda: os.getenv("CONTENT_MODERATION_ENABLED", "true").lower() == "true")
    notification_timeout: int = field(default_factory=lambda: int(os.getenv("CONTENT_MODERATION_NOTIFICATION_TIMEOUT", "10")))
    bypass_roles: List[str] = field(default_factory=lambda: os.getenv("CONTENT_MODERATION_BYPASS_ROLES", "").split(",") if os.getenv("CONTENT_MODERATION_BYPASS_ROLES") else [])
    mute_role_name: str = field(default_factory=lambda: os.getenv("MUTE_ROLE_NAME", "Muted"))
    mute_role_id: int = field(default_factory=lambda: int(os.getenv("MUTE_ROLE_ID", "0")))
    
    # AI review configuration
    review_enabled: bool = field(default_factory=lambda: os.getenv("MODERATION_REVIEW_ENABLED", "true").lower() == "true")
    review_ai_service: str = field(default_factory=lambda: os.getenv("MODERATION_REVIEW_AI_SERVICE", os.getenv("SECONDARY_MODEL_PROVIDER", "gemini")))
    review_model: str = field(default_factory=lambda: os.getenv("MODERATION_REVIEW_MODEL", os.getenv("SECONDARY_MODEL_NAME", "gemini-2.0-flash")))
    backup_review_ai_service: str = field(default_factory=lambda: os.getenv("MODERATION_BACKUP_REVIEW_AI_SERVICE", os.getenv("PRIMARY_MODEL_PROVIDER", "gemini")))
    backup_review_model: str = field(default_factory=lambda: os.getenv("MODERATION_BACKUP_REVIEW_MODEL", os.getenv("PRIMARY_MODEL_NAME", "gemini-2.0-flash")))
    review_context_messages: int = field(default_factory=lambda: int(os.getenv("MODERATION_REVIEW_CONTEXT_MESSAGES", "3")))
    
    # Queue configuration
    queue_enabled: bool = field(default_factory=lambda: os.getenv("MODERATION_QUEUE_ENABLED", "true").lower() == "true")
    queue_max_concurrent: int = field(default_factory=lambda: int(os.getenv("MODERATION_QUEUE_MAX_CONCURRENT", "3")))
    queue_check_interval: float = field(default_factory=lambda: float(os.getenv("MODERATION_QUEUE_CHECK_INTERVAL", "1.0")))
    queue_retry_interval: float = field(default_factory=lambda: float(os.getenv("MODERATION_QUEUE_RETRY_INTERVAL", "5.0")))
    queue_max_retries: int = field(default_factory=lambda: int(os.getenv("MODERATION_QUEUE_MAX_RETRIES", "5")))


@dataclass
class URLSafetyConfig:
    """URL safety checking configuration."""
    enabled: bool = field(default_factory=lambda: os.getenv("URL_SAFETY_CHECK_ENABLED", "true").lower() == "true")
    api: str = field(default_factory=lambda: os.getenv("URL_SAFETY_CHECK_API", "virustotal"))
    api_key: str = field(default_factory=lambda: os.getenv("URL_SAFETY_API_KEY", ""))
    threshold: float = field(default_factory=lambda: float(os.getenv("URL_SAFETY_THRESHOLD", "0.3")))
    max_retries: int = field(default_factory=lambda: int(os.getenv("URL_SAFETY_MAX_RETRIES", "3")))
    retry_delay: int = field(default_factory=lambda: int(os.getenv("URL_SAFETY_RETRY_DELAY", "2")))
    request_timeout: float = field(default_factory=lambda: float(os.getenv("URL_SAFETY_REQUEST_TIMEOUT", "5.0")))
    max_urls: int = 10
    
    # Unshortener
    unshorten_enabled: bool = True
    unshorten_timeout: int = 10
    unshorten_max_redirects: int = 10
    unshorten_retry_count: int = 3
    
    # Blacklist
    blacklist_enabled: bool = True
    blacklist_file: str = "data/url_blacklist.json"
    blacklist_auto_domain: bool = True
    
    # Impersonation domains
    impersonation_domains: List[str] = field(default_factory=lambda: os.getenv("URL_SAFETY_IMPERSONATION_DOMAINS", "").split(",") if os.getenv("URL_SAFETY_IMPERSONATION_DOMAINS") else [])


@dataclass
class WelcomeConfig:
    """Welcome system configuration."""
    enabled: bool = field(default_factory=lambda: os.getenv("WELCOME_ENABLED", "true").lower() == "true")
    channel_ids: List[str] = field(default_factory=lambda: os.getenv("WELCOME_CHANNEL_IDS", "").split(",") if os.getenv("WELCOME_CHANNEL_IDS") else [])
    default_message: str = field(default_factory=lambda: os.getenv("DEFAULT_WELCOME_MESSAGE", "歡迎 {member} 加入我們的伺服器！✨"))
    use_ai: bool = field(default_factory=lambda: os.getenv("WELCOME_USE_AI", "true").lower() == "true")
    max_retries: int = field(default_factory=lambda: int(os.getenv("WELCOME_MAX_RETRIES", "3")))
    retry_interval_minutes: int = field(default_factory=lambda: int(os.getenv("WELCOME_RETRY_INTERVAL_MINUTES", "5")))


@dataclass
class TicketConfig:
    """Ticket system configuration."""
    enabled: bool = field(default_factory=lambda: os.getenv("TICKET_ENABLED", "true").lower() == "true")
    category_name: str = field(default_factory=lambda: os.getenv("TICKET_CATEGORY_NAME", "Tickets"))
    transcript_channel: int = field(default_factory=lambda: int(os.getenv("TICKET_TRANSCRIPT_CHANNEL", "0")))
    staff_roles: List[str] = field(default_factory=lambda: os.getenv("TICKET_STAFF_ROLES", "").split(",") if os.getenv("TICKET_STAFF_ROLES") else [])


@dataclass
class SearchConfig:
    """Search service configuration."""
    tavily_api_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))
    tavily_max_results: int = field(default_factory=lambda: int(os.getenv("TAVILY_SEARCH_MAX_RESULTS", "5")))


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_path: str = "logs/hacksterbot.log"
    max_bytes: int = 10485760  # 10MB
    backup_count: int = 5


@dataclass
class Config:
    """Main configuration class containing all subsystem configurations."""
    discord: DiscordConfig
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    moderation: ModerationConfig = field(default_factory=ModerationConfig)
    url_safety: URLSafetyConfig = field(default_factory=URLSafetyConfig)
    welcome: WelcomeConfig = field(default_factory=WelcomeConfig)
    ticket: TicketConfig = field(default_factory=TicketConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    # General settings
    debug: bool = field(default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true")
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", "data"))
    logs_dir: str = field(default_factory=lambda: os.getenv("LOGS_DIR", "logs"))


def load_config() -> Config:
    """
    Load configuration from environment variables.
    
    Returns:
        Config: The loaded configuration
        
    Raises:
        ConfigError: If required configuration is missing
    """
    # Check for required environment variables
    discord_token = os.getenv("DISCORD_TOKEN")
    if not discord_token:
        raise ConfigError("DISCORD_TOKEN environment variable is required")
    
    # Helper function to parse comma-separated lists
    def parse_list(value: Optional[str]) -> List[str]:
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]
    
    def parse_int_list(value: Optional[str]) -> List[int]:
        if not value:
            return []
        try:
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        except ValueError:
            return []
    
    # Build configuration
    config = Config(
        discord=DiscordConfig(
            token=discord_token,
            command_prefix=os.getenv("COMMAND_PREFIX", "!")
        ),
        
        database=DatabaseConfig(
            url=os.getenv("DATABASE_URL", "sqlite:///data/hacksterbot.db"),
            echo=os.getenv("DATABASE_ECHO", "false").lower() == "true"
        ),
        
        ai=AIConfig(),
        
        moderation=ModerationConfig(),
        
        url_safety=URLSafetyConfig(),
        welcome=WelcomeConfig(),
        ticket=TicketConfig(),
        search=SearchConfig(),
        logging=LoggingConfig(),
        
        debug=os.getenv("DEBUG", "false").lower() == "true",
        data_dir=os.getenv("DATA_DIR", "data"),
        logs_dir=os.getenv("LOGS_DIR", "logs")
    )
    
    # Create necessary directories
    Path(config.data_dir).mkdir(exist_ok=True)
    Path(config.logs_dir).mkdir(exist_ok=True)
    
    return config 
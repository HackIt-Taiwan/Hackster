"""
Custom exceptions for HacksterBot.
"""


class BotError(Exception):
    """Base exception for all bot-related errors."""
    pass


class ModuleError(BotError):
    """Exception raised when module operations fail."""
    pass


class ConfigError(BotError):
    """Exception raised when configuration is invalid."""
    pass


class DatabaseError(BotError):
    """Exception raised when database operations fail."""
    pass


class APIError(BotError):
    """Exception raised when external API calls fail."""
    pass


class ValidationError(BotError):
    """Exception raised when data validation fails."""
    pass 
"""
Core module for HacksterBot.
Contains the fundamental components of the bot system.
"""

__version__ = "1.0.0"
__author__ = "HackIt Team"

from .bot import HacksterBot
from .config import Config, load_config
from .database import DatabaseManager
from .exceptions import BotError, ModuleError, ConfigError

__all__ = [
    "HacksterBot",
    "Config", 
    "load_config",
    "DatabaseManager",
    "BotError",
    "ModuleError", 
    "ConfigError"
] 
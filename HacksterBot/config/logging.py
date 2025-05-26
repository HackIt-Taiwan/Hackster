"""
Logging configuration for HacksterBot.
"""
import logging
import logging.handlers
import os
from pathlib import Path


def setup_logging() -> None:
    """Setup logging configuration for the bot."""
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Get log level from environment
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    simple_formatter = logging.Formatter(
        fmt="%(levelname)s - %(message)s"
    )
    
    # Create handlers
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)
    
    # File handler with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_dir / "hacksterbot.log",
        mode="a",
        maxBytes=10485760,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    
    # Error file handler
    error_handler = logging.handlers.RotatingFileHandler(
        filename=log_dir / "error.log",
        mode="a",
        maxBytes=5242880,  # 5MB
        backupCount=3,
        encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Add handlers
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    
    # Configure discord.py logging
    discord_logger = logging.getLogger("discord")
    discord_logger.setLevel(logging.WARNING)
    
    # Configure httpx logging (used by pydantic-ai)
    httpx_logger = logging.getLogger("httpx")
    httpx_logger.setLevel(logging.WARNING)
    
    # Configure aiohttp logging
    aiohttp_logger = logging.getLogger("aiohttp")
    aiohttp_logger.setLevel(logging.WARNING)
    
    logging.info("Logging configuration complete") 
#!/usr/bin/env python3
"""
HacksterBot - Modular Discord Bot
Main entry point for the bot application.
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from core.bot import HacksterBot
from core.config import load_config
from config.logging import setup_logging


async def main():
    """Main function to start the bot."""
    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)
    
    try:
        # Load configuration
        config = load_config()
        
        # Create and start the bot
        bot = HacksterBot(config)
        
        # Load all modules
        await bot.load_modules()
        
        # Start the bot
        logger.info("Starting HacksterBot...")
        await bot.start(config.discord.token)
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise
    finally:
        # Cleanup
        if 'bot' in locals():
            await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Critical error: {e}")
        sys.exit(1) 
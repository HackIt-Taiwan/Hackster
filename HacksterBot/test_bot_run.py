#!/usr/bin/env python3
"""
Test bot startup and keep it running for a short time.
"""
import asyncio
import logging
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from core.bot import HacksterBot
from core.config import load_config
from config.logging import setup_logging


async def test_bot():
    """Test bot startup."""
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
        logger.info("Starting HacksterBot for testing...")
        
        # Create a task to run the bot
        bot_task = asyncio.create_task(bot.start(config.discord.token))
        
        # Wait for 30 seconds to see if it starts properly
        try:
            await asyncio.wait_for(bot_task, timeout=30.0)
        except asyncio.TimeoutError:
            logger.info("Bot has been running for 30 seconds - test successful!")
            bot_task.cancel()
            await bot.close()
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        # Cleanup
        if 'bot' in locals():
            await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(test_bot())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Critical error: {e}")
        sys.exit(1) 
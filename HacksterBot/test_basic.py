#!/usr/bin/env python3
"""
Basic test script for HacksterBot core architecture.
This script tests the basic functionality without requiring Discord token.
"""
import asyncio
import logging
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from core.config import Config, DiscordConfig
from core.bot import HacksterBot
from config.logging import setup_logging


async def test_basic_functionality():
    """Test basic bot functionality without starting Discord connection."""
    
    print("🧪 Testing HacksterBot basic functionality...")
    
    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)
    
    try:
        # Create a test configuration
        test_config = Config(
            discord=DiscordConfig(token="test_token"),
            debug=True
        )
        
        # Create bot instance
        bot = HacksterBot(test_config)
        logger.info("✅ Bot instance created successfully")
        
        # Test database manager
        assert bot.db_manager is not None
        logger.info("✅ Database manager initialized")
        
        # Test module discovery (without loading)
        modules_path = Path(__file__).parent / "modules"
        if modules_path.exists():
            module_count = len(list(modules_path.iterdir()))
            logger.info(f"✅ Found {module_count} potential modules")
        else:
            logger.warning("⚠️ Modules directory not found")
        
        # Test configuration
        assert test_config.discord.token == "test_token"
        assert test_config.debug is True
        logger.info("✅ Configuration system working")
        
        # Test module enable/disable logic
        ai_enabled = bot._is_module_enabled('ai')
        moderation_enabled = bot._is_module_enabled('moderation')
        logger.info(f"✅ Module enable logic: AI={ai_enabled}, Moderation={moderation_enabled}")
        
        print("\n🎉 All basic tests passed!")
        print("📋 Summary:")
        print("   ✅ Core architecture initialized")
        print("   ✅ Configuration system working")
        print("   ✅ Database manager ready")
        print("   ✅ Module discovery functional")
        print("\n💡 Next steps:")
        print("   1. Set up your .env file with Discord token")
        print("   2. Install missing dependencies if any")
        print("   3. Run 'python main.py' to start the bot")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        print(f"\n💥 Test failed: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_basic_functionality())
    sys.exit(0 if success else 1) 
#!/usr/bin/env python3
"""
Module loading and functionality test for HacksterBot.
Tests all modules independently and together.
"""
import asyncio
import logging
import sys
import traceback
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path('.').absolute()))

# Configure logging for testing
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

async def test_module_imports():
    """Test that all modules can be imported."""
    print("🧪 Testing module imports...")
    
    modules_to_test = [
        'core.config',
        'core.bot', 
        'core.database',
        'core.exceptions',
        'modules.ai',
        'modules.moderation',
        'modules.welcome',


        'modules.tickets'
    ]
    
    imported_modules = []
    failed_modules = []
    
    for module_name in modules_to_test:
        try:
            __import__(module_name)
            imported_modules.append(module_name)
            print(f"   ✅ {module_name}")
        except Exception as e:
            failed_modules.append((module_name, str(e)))
            print(f"   ❌ {module_name}: {e}")
    
    print(f"\n📊 Import Results: {len(imported_modules)}/{len(modules_to_test)} successful")
    
    if failed_modules:
        print("❌ Failed imports:")
        for module, error in failed_modules:
            print(f"   - {module}: {error}")
        return False
    
    return True


async def test_config_loading():
    """Test configuration loading."""
    print("\n🧪 Testing configuration loading...")
    
    try:
        from core.config import load_config
        config = load_config()
        
        print(f"   ✅ Configuration loaded successfully")
        print(f"   ✅ AI enabled: {hasattr(config, 'ai')}")
        print(f"   ✅ Moderation enabled: {config.moderation.enabled}")
        print(f"   ✅ URL Safety enabled: {config.url_safety.enabled}")
        print(f"   ✅ Welcome enabled: {config.welcome.enabled}")


        print(f"   ✅ Ticket enabled: {config.ticket.enabled}")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Configuration loading failed: {e}")
        traceback.print_exc()
        return False


async def test_bot_initialization():
    """Test bot initialization."""
    print("\n🧪 Testing bot initialization...")
    
    try:
        from core.config import load_config
        from core.bot import HacksterBot
        
        config = load_config()
        bot = HacksterBot(config)
        
        print(f"   ✅ Bot initialized successfully")
        print(f"   ✅ Bot has {len(bot.modules)} loaded modules")
        print(f"   ✅ Database manager: {bot.db_manager is not None}")
        
        # Clean up
        await bot.close()
        
        return True
        
    except Exception as e:
        print(f"   ❌ Bot initialization failed: {e}")
        traceback.print_exc()
        return False


async def test_module_loading():
    """Test module loading process."""
    print("\n🧪 Testing module loading...")
    
    try:
        from core.config import load_config
        from core.bot import HacksterBot
        
        config = load_config()
        bot = HacksterBot(config)
        
        print("   📦 Loading modules...")
        await bot.load_modules()
        
        loaded_modules = bot.list_modules()
        print(f"   ✅ Loaded {len(loaded_modules)} modules:")
        for module_name in loaded_modules:
            module = bot.get_module(module_name)
            status = "initialized" if module.is_initialized else "not initialized"
            print(f"      - {module_name} ({status})")
        
        # Test module functionality
        print("\n   🔧 Testing module functionality...")
        
        # Test AI module
        ai_module = bot.get_module('ai')
        if ai_module:
            print(f"      ✅ AI module loaded and {ai_module.is_initialized}")
        
        # Test tickets module 
        tickets_module = bot.get_module('tickets')
        if tickets_module:
            print(f"      ✅ Tickets module loaded with events: {len(tickets_module.events_config.get('events', []))}")
        
        # Clean up
        await bot.close()
        
        return len(loaded_modules) > 0
        
    except Exception as e:
        print(f"   ❌ Module loading failed: {e}")
        traceback.print_exc()
        return False


async def test_database_operations():
    """Test database operations."""
    print("\n🧪 Testing database operations...")
    
    try:
        from core.database import create_database_manager
        from core.config import load_config
        
        config = load_config()
        db_manager = create_database_manager(config)
        
        print("   ✅ Database manager created")
        print(f"   ✅ Database URL: {config.database.url}")
        
        # Test tickets database
        print("   📋 Testing tickets database...")
        # Tickets module uses file-based storage, no database class needed
        print("   ✅ Tickets module uses file-based storage")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Database operations failed: {e}")
        traceback.print_exc()
        return False


async def test_events_configuration():
    """Test events configuration loading."""
    print("\n🧪 Testing events configuration...")
    
    try:
        import json
        import os
        
        events_path = "data/events.json"
        if os.path.exists(events_path):
            with open(events_path, 'r', encoding='utf-8') as f:
                events_config = json.load(f)
            
            events = events_config.get('events', [])
            active_events = [e for e in events if e.get('active', True)]
            
            print(f"   ✅ Events configuration loaded")
            print(f"   ✅ Total events: {len(events)}")
            print(f"   ✅ Active events: {len(active_events)}")
            
            for event in active_events:
                print(f"      - {event['name']} (ID: {event['id']})")
            
            return True
        else:
            print(f"   ❌ Events configuration file not found: {events_path}")
            return False
        
    except Exception as e:
        print(f"   ❌ Events configuration test failed: {e}")
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("🚀 Starting HacksterBot comprehensive module tests...\n")
    
    tests = [
        ("Module Imports", test_module_imports),
        ("Configuration Loading", test_config_loading),
        ("Bot Initialization", test_bot_initialization),
        ("Module Loading", test_module_loading),
        ("Database Operations", test_database_operations),
        ("Events Configuration", test_events_configuration),
    ]
    
    passed_tests = 0
    total_tests = len(tests)
    
    for test_name, test_func in tests:
        try:
            result = await test_func()
            if result:
                passed_tests += 1
                print(f"✅ {test_name}: PASSED\n")
            else:
                print(f"❌ {test_name}: FAILED\n")
        except Exception as e:
            print(f"❌ {test_name}: CRASHED - {e}\n")
            traceback.print_exc()
            print()
    
    print("=" * 60)
    print(f"🎯 Test Results: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("🎉 All tests passed! The bot is ready for deployment.")
        print("\n💡 Next steps:")
        print("   1. Set your real Discord token in .env")
        print("   2. Configure API keys for AI services")
        print("   3. Update role IDs for your Discord server")
        print("   4. Run 'python main.py' to start the bot")
    else:
        print("⚠️  Some tests failed. Please check the errors above.")
        print("   Fix the issues before running the bot.")
    
    return passed_tests == total_tests


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1) 
#!/usr/bin/env python3
"""
Simple startup script for HacksterBot.
This script demonstrates how to run the bot with basic configuration.
"""
import asyncio
import os
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from main import main


async def start_bot():
    """Start the HacksterBot with basic configuration."""
    print("🚀 Starting HacksterBot...")
    
    # Check for .env file
    env_file = project_root / ".env"
    if not env_file.exists():
        print("⚠️  Warning: .env file not found!")
        print("📝 Please create a .env file based on .env.example")
        print("🔑 Make sure to set your DISCORD_TOKEN")
        return
    
    # Check for Discord token
    from dotenv import load_dotenv
    load_dotenv()
    
    if not os.getenv("DISCORD_TOKEN"):
        print("❌ Error: DISCORD_TOKEN not found in environment variables!")
        print("📝 Please set your Discord bot token in the .env file")
        return
    
    try:
        await main()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(start_bot()) 
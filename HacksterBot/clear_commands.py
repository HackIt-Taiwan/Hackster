#!/usr/bin/env python3
"""
Clear Discord application commands to fix sync issues.
"""
import asyncio
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def clear_commands():
    """Clear all application commands."""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN not found in environment variables")
        return
    
    # Setup Discord intents
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.members = True
    
    # Create bot instance
    bot = commands.Bot(command_prefix="!", intents=intents)
    
    @bot.event
    async def on_ready():
        print(f"🤖 Bot logged in as {bot.user}")
        
        try:
            # Clear global commands
            print("🧹 Clearing global commands...")
            bot.tree.clear_commands(guild=None)
            await bot.tree.sync()
            print("✅ Global commands cleared")
            
            # Clear guild-specific commands for all guilds
            for guild in bot.guilds:
                print(f"🧹 Clearing commands for guild: {guild.name} ({guild.id})")
                bot.tree.clear_commands(guild=guild)
                await bot.tree.sync(guild=guild)
                print(f"✅ Commands cleared for {guild.name}")
            
            print("🎉 All commands cleared successfully!")
            
        except Exception as e:
            print(f"❌ Error clearing commands: {e}")
        
        finally:
            await bot.close()
    
    # Start the bot
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(clear_commands()) 
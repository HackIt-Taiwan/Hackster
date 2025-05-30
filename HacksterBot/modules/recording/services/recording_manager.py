"""
Recording Manager - Manages multiple recording bots and meeting recordings.

Converted from HackMeet-DiscordBot to work with discord.py instead of py-cord.
"""

import asyncio
import logging
import time
from typing import List, Dict, Optional

import discord
from discord.ext import commands

from .recording_bot import RecordingBot
from .meeting_recorder import MeetingRecorder
from .forum_manager import ForumManager


class RecordingManager:
    """Manages multiple recording bot instances and handles recording scheduling."""
    
    def __init__(self, bot_tokens: List[str], main_bot, config):
        self.bot_tokens = bot_tokens
        self.main_bot = main_bot
        self.config = config
        self.recording_bots: List[RecordingBot] = []
        self.meetings_in_progress: List[int] = []
        self.logger = logging.getLogger(__name__)
        self.forum_manager = ForumManager(config)
        
    async def initialize(self):
        """Initialize all recording bots."""
        for token in self.bot_tokens:
            bot = RecordingBot(token, self, self.config)
            self.recording_bots.append(bot)
            
        # Start all recording bots in background tasks
        for bot in self.recording_bots:
            asyncio.create_task(bot.start(bot.bot_token))
            
        self.logger.info(f"Initialized {len(self.recording_bots)} recording bots")
        
    async def shutdown(self):
        """Shutdown all recording bots."""
        for bot in self.recording_bots:
            if not bot.is_closed():
                await bot.close()
                
    def finish_meeting(self, voice_channel_id: int):
        """Remove a finished meeting from the in-progress list."""
        if voice_channel_id in self.meetings_in_progress:
            self.meetings_in_progress.remove(voice_channel_id)
            self.logger.info(f"Meeting {voice_channel_id} removed from in-progress list")
            
    async def handle_new_meeting(self, voice_channel_id: int):
        """Called when a new meeting is created."""
        self.meetings_in_progress.append(voice_channel_id)
        await self.schedule_bots()
        
    async def schedule_bots(self):
        """Schedule free bots to record ongoing meetings."""
        self.logger.info("Scheduling bots for meetings...")
        
        # Find bots already recording
        used_bot_ids = set()
        for bot in self.recording_bots:
            for vc_id, vc_info in bot.meeting_voice_channel_info.items():
                if vc_id in self.meetings_in_progress:
                    if vc_info.get("recording_task") is not None:
                        if bot.user:
                            used_bot_ids.add(bot.user.id)
                            
        # Find free bots
        free_bots = [
            bot for bot in self.recording_bots
            if bot.user and bot.user.id not in used_bot_ids and bot.is_ready()
        ]
        
        # Assign bots to meetings
        for vc_id in self.meetings_in_progress:
            self.logger.info(f"Checking if meeting {vc_id} already has a bot...")
            already_has_bot = False
            
            # Check if any bot is already recording
            for bot in self.recording_bots:
                vc_info = bot.meeting_voice_channel_info.get(vc_id)
                if vc_info and vc_info.get("recording_task") is not None:
                    already_has_bot = True
                    break
                    
            if not already_has_bot and free_bots:
                chosen_bot = free_bots.pop(0)
                self.logger.info(f"Assigning bot {chosen_bot.user.name} to record meeting {vc_id}")
                
                # Sync meeting info from origin bot
                origin_bot = next((b for b in self.recording_bots if vc_id in b.meeting_voice_channel_info), None)
                if origin_bot is not None:
                    origin_info = origin_bot.meeting_voice_channel_info.get(vc_id, {})
                    chosen_bot.meeting_voice_channel_info[vc_id] = dict(origin_info)
                else:
                    chosen_bot.meeting_voice_channel_info[vc_id] = {}
                    
                guild = chosen_bot.guilds[0] if chosen_bot.guilds else None
                if not guild:
                    self.logger.error(f"Bot {chosen_bot.user.name} not in any guild. Cannot record.")
                    continue
                    
                voice_channel = guild.get_channel(vc_id)
                if voice_channel:
                    try:
                        recorder = MeetingRecorder(chosen_bot, self.config)
                        recording_task = asyncio.create_task(
                            recorder.record_meeting_audio(vc_id)
                        )
                        chosen_bot.meeting_voice_channel_info[vc_id]["recording_task"] = recording_task
                        chosen_bot.meeting_voice_channel_info[vc_id]["recorder"] = recorder
                        
                        self.logger.info(f"Assigned bot {chosen_bot.user.name} to record voice channel {voice_channel.name}")
                    except Exception as error:
                        self.logger.error(f"Failed to assign bot to meeting: {error}")
                        
    def assign_bot_for_meeting(self) -> Optional['RecordingBot']:
        """Try to assign a free bot for a new meeting."""
        # Find all bots currently recording
        used_bot_ids = set()
        for bot in self.recording_bots:
            for vc_id, vc_info in bot.meeting_voice_channel_info.items():
                if vc_info.get("recording_task") is not None:
                    if bot.user:
                        used_bot_ids.add(bot.user.id)
                        
        free_bots = [
            bot for bot in self.recording_bots
            if bot.user and bot.user.id not in used_bot_ids and bot.is_ready()
        ]
        
        if not free_bots:
            self.logger.warning("No free bots available to create a new meeting")
            return None
            
        # Choose the first free bot
        chosen_bot = free_bots[0]
        self.logger.info(f"Assigned bot {chosen_bot.user.name} to create new meeting room")
        return chosen_bot
        
    async def create_meeting_room(self, member, category, base_channel_name="會議室"):
        """Create a meeting room with an available bot."""
        assigned_bot = self.assign_bot_for_meeting()
        if not assigned_bot:
            self.logger.error("No available bot to create meeting room")
            return None
            
        return await assigned_bot.create_meeting_room(member, category, base_channel_name)
        
    async def start_recording(self, voice_channel_id: int) -> bool:
        """Start recording for a voice channel."""
        await self.handle_new_meeting(voice_channel_id)
        return True
        
    async def stop_recording(self, voice_channel_id: int) -> bool:
        """Stop recording for a voice channel."""
        # Find the bot recording this channel
        for bot in self.recording_bots:
            vc_info = bot.meeting_voice_channel_info.get(voice_channel_id)
            if vc_info and vc_info.get("recording_task") is not None:
                recording_task = vc_info["recording_task"]
                if not recording_task.done():
                    recording_task.cancel()
                    self.logger.info(f"Stopped recording for channel {voice_channel_id}")
                    return True
                    
        self.logger.warning(f"No active recording found for channel {voice_channel_id}")
        return False 
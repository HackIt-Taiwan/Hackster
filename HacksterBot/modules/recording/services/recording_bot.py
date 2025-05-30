"""
Recording Bot - Individual bot instance for meeting recording.

Converted from HackMeet-DiscordBot to work with discord.py instead of py-cord.
"""

import asyncio
import logging
import time
from datetime import timedelta
from typing import Dict

import discord
from discord.ext import commands

from .meeting_utils import generate_meeting_room_name
from .forum_manager import ForumManager


class RecordingBot(commands.Bot):
    """A single bot instance for meeting recording."""
    
    def __init__(self, bot_token: str, manager, config):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        
        self.bot_token = bot_token
        self.manager = manager
        self.config = config
        self.meeting_voice_channel_info: Dict[int, dict] = {}
        self.meeting_forum_thread_info: Dict[int, discord.Thread] = {}
        self.forum_manager = ForumManager(config)
        self.logger = logging.getLogger(__name__)
        
    def _process_template(self, template: str) -> str:
        """Process template string to convert literal \\n to actual newlines."""
        # Convert literal \\n strings to actual newline characters
        return template.replace('\\n', '\n')
        
    async def on_ready(self):
        """Called when the bot is ready."""
        self.logger.info(f"Recording bot {self.user} started. ID: {self.user.id}")
        
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Handle voice state updates for meeting management."""
        # Ignore if it's a bot
        if member.bot:
            return
            
        # User joins a voice channel
        if after.channel and (not before.channel or before.channel.id != after.channel.id):
            # Check if user joined the trigger channel
            trigger_channel_name = getattr(self.config.recording, 'trigger_channel_name', '會議室')
            if trigger_channel_name == after.channel.name:
                # Check if this bot is assigned for this meeting
                assigned_bot = self.manager.assign_bot_for_meeting()
                if assigned_bot is not self:
                    return
                    
                # Create new meeting room
                await self._create_new_meeting_room(member, after.channel)
                
            # User joins an existing meeting channel
            elif after.channel and after.channel.id in self.meeting_voice_channel_info:
                await self._handle_user_join_meeting(member, after.channel)
                
        # User leaves a voice channel
        if before.channel and (not after.channel or before.channel.id != after.channel.id):
            if before.channel.id in self.meeting_voice_channel_info:
                await self._handle_user_leave_meeting(member, before.channel)
                
    async def _create_new_meeting_room(self, member: discord.Member, trigger_channel: discord.VoiceChannel):
        """Create a new meeting room for the member."""
        category = trigger_channel.category
        new_channel_name = generate_meeting_room_name()
        
        try:
            # Copy permissions from trigger channel
            original_overwrites = trigger_channel.overwrites
            
            # Create new voice channel with same permissions
            meeting_channel = await category.create_voice_channel(
                name=new_channel_name,
                overwrites=original_overwrites
            )
            await member.move_to(meeting_channel)
            
            # Create forum thread if forum channel exists
            forum_channel = None
            forum_channel_name = getattr(self.config.recording, 'forum_channel_name', '會議記錄')
            for ch in category.channels:
                if isinstance(ch, discord.ForumChannel) and ch.name == forum_channel_name:
                    forum_channel = ch
                    break
                    
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            thread = None
            if forum_channel:
                content_template = getattr(
                    self.config.recording, 
                    'forum_content_template',
                    "**會議記錄**\n\n會議發起人: {initiator}\n會議開始時間: {time}\n會議頻道: {channel}\n\n參與者 {initiator} 加入了會議"
                )
                content = self._process_template(content_template).format(
                    initiator=member.mention,
                    time=now_str,
                    channel=meeting_channel.mention
                )
                thread = await self.forum_manager.create_forum_post(
                    forum_channel=forum_channel,
                    title=new_channel_name,
                    content=content
                )
                
            # Store meeting information
            self.meeting_voice_channel_info[meeting_channel.id] = {
                "start_time": time.time(),
                "active_participants": {member.id},
                "all_participants": {member.id},
                "forum_thread_id": thread.id if thread else None,
                "summary_message_id": None,
                "recording_task": None,
                "user_join_time": {member.id: time.time()},
                "user_leave_time": {},
                "user_recording_status": {member.id: True},
            }
            
            if thread:
                self.meeting_forum_thread_info[thread.id] = thread
                
            self.logger.info(f"Created new meeting room: {new_channel_name}")
            await self.manager.handle_new_meeting(meeting_channel.id)
            
        except Exception as error:
            self.logger.error(f"Failed to create new meeting room: {error}")
            
    async def _handle_user_join_meeting(self, member: discord.Member, voice_channel: discord.VoiceChannel):
        """Handle user joining an existing meeting."""
        info = self.meeting_voice_channel_info[voice_channel.id]
        current_time = time.time()
        
        info["active_participants"].add(member.id)
        info["all_participants"].add(member.id)
        
        # Track join time for audio synchronization
        if member.id not in info["user_join_time"]:
            info["user_join_time"][member.id] = current_time
            # First time joining - audio sink handles this automatically
        else:
            # User rejoining after leaving
            info["user_join_time"][member.id] = current_time
            # Get audio sink from recorder for rejoin tracking
            recorder = info.get("recorder")
            if recorder and hasattr(recorder, "audio_sink") and recorder.audio_sink:
                recorder.audio_sink.mark_user_rejoin(member.id, current_time)
                self.logger.info(f"User {member.display_name} rejoined, audio sync enabled")
                
        # Update recording status
        info["user_recording_status"][member.id] = True
        if member.id in info["user_leave_time"]:
            del info["user_leave_time"][member.id]
                    
        # Update forum thread
        thread_id = info["forum_thread_id"]
        if thread_id:
            thread = self.meeting_forum_thread_info.get(thread_id)
            if thread:
                try:
                    join_message_template = getattr(
                        self.config.recording,
                        'join_message_template',
                        "{member} 加入會議"
                    )
                    await thread.send(self._process_template(join_message_template).format(member=member.mention))
                except Exception as exc:
                    self.logger.error(f"Cannot update forum thread (join): {exc}")
                    
    async def _handle_user_leave_meeting(self, member: discord.Member, voice_channel: discord.VoiceChannel):
        """Handle user leaving a meeting."""
        info = self.meeting_voice_channel_info[voice_channel.id]
        current_time = time.time()
        
        if member.id in info["active_participants"]:
            info["active_participants"].remove(member.id)
            info["user_leave_time"][member.id] = current_time
            info["user_recording_status"][member.id] = False
            
            # Notify audio sink about user leaving for gap tracking
            recorder = info.get("recorder")
            if recorder and hasattr(recorder, "audio_sink") and recorder.audio_sink:
                recorder.audio_sink.mark_user_leave(member.id, current_time)
                self.logger.info(f"User {member.display_name} left, audio gap tracking enabled")
            
        # Update forum thread
        thread_id = info.get("forum_thread_id")
        if thread_id:
            thread = self.meeting_forum_thread_info.get(thread_id)
            if thread:
                try:
                    leave_message_template = getattr(
                        self.config.recording,
                        'leave_message_template',
                        "{member} 離開會議"
                    )
                    await thread.send(self._process_template(leave_message_template).format(member=member.mention))
                except Exception as exc:
                    self.logger.error(f"Cannot update forum thread (leave): {exc}")
                    
        # Close meeting if no human participants left
        if not any(m for m in voice_channel.members if not m.bot):
            self.logger.info(f"Channel {voice_channel.name} has no human participants. Will close in 5 seconds.")
            await self.close_meeting_after_delay(voice_channel.id, delay_seconds=5)
            
    async def close_meeting_after_delay(self, channel_id: int, delay_seconds: int = 5):
        """Wait and then close meeting if no users remain."""
        await asyncio.sleep(delay_seconds)
        guild = self.guilds[0] if self.guilds else None
        if not guild:
            return
            
        voice_channel = guild.get_channel(channel_id)
        if not voice_channel:
            return
            
        # If still no human participants, close the meeting
        if not any(m for m in voice_channel.members if not m.bot):
            info = self.meeting_voice_channel_info.get(channel_id)
            if not info:
                return
                
            start_time_ts = info["start_time"]
            all_participants = info["all_participants"]
            thread_id = info["forum_thread_id"]
            thread = self.meeting_forum_thread_info.get(thread_id) if thread_id else None
            
            end_time = time.time()
            duration_sec = end_time - start_time_ts
            duration_str = str(timedelta(seconds=int(duration_sec)))
            
            # Stop recording task
            recording_task = info.get("recording_task")
            if recording_task and not recording_task.done():
                recording_task.cancel()
                self.logger.info("Recording task stopped")
                
            # Send meeting ended message to forum thread
            if thread:
                try:
                    ended_message_template = getattr(
                        self.config.recording,
                        'ended_message_template',
                        "**會議結束**\n會議持續時間: {duration}\n參與者: {participants}\n"
                    )
                    # Get participant mentions
                    participant_mentions = []
                    if guild:
                        for user_id in all_participants:
                            member = guild.get_member(user_id)
                            if member:
                                participant_mentions.append(member.mention)
                                
                    await thread.send(self._process_template(ended_message_template).format(
                        duration=duration_str,
                        participants=", ".join(participant_mentions)
                    ))
                except Exception as error:
                    self.logger.error(f"Failed to send meeting ended message: {error}")
                    
            # Delete voice channel
            try:
                await voice_channel.delete(reason="Meeting ended")
            except Exception as error:
                self.logger.error(f"Failed to delete voice channel: {error}")
                
            # Clean up meeting information
            if channel_id in self.meeting_voice_channel_info:
                del self.meeting_voice_channel_info[channel_id]
            if thread_id in self.meeting_forum_thread_info:
                del self.meeting_forum_thread_info[thread_id]
                
            self.manager.finish_meeting(channel_id)
            await self.manager.schedule_bots()
        else:
            self.logger.info(f"Channel {voice_channel.name} had new participants within {delay_seconds} seconds. Cancel closing.")
            
    async def create_meeting_room(self, member, category, base_channel_name="會議室"):
        """Create a meeting room for external callers."""
        # Find trigger channel in the category
        trigger_channel = None
        for channel in category.voice_channels:
            if channel.name == base_channel_name:
                trigger_channel = channel
                break
                
        if trigger_channel:
            await self._create_new_meeting_room(member, trigger_channel)
            return True
        else:
            self.logger.error(f"Trigger channel '{base_channel_name}' not found in category")
            return False 
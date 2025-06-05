import asyncio
import logging
import os
import time
import wave
from datetime import datetime
from typing import Optional

import discord

try:
    from discord.ext import voice_recv
    from discord import opus
    VOICE_RECV_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    VOICE_RECV_AVAILABLE = False
    voice_recv = None


class SingleTrackRecordingSink(voice_recv.AudioSink if VOICE_RECV_AVAILABLE else object):
    """Audio sink that mixes all users into a single track recording."""

    def __init__(self, folder: str) -> None:
        if VOICE_RECV_AVAILABLE:
            super().__init__()
        self.folder = folder
        self.sample_rate = 48000
        self.channels = 2
        self.sample_width = 2
        self.decoder = None
        self.logger = logging.getLogger(__name__)
        
        # Create output directory
        os.makedirs(folder, exist_ok=True)
        
        # Create single WAV file for the entire meeting
        self.output_file = os.path.join(folder, "meeting_recording.wav")
        self.wav_file = wave.open(self.output_file, "wb")
        self.wav_file.setnchannels(self.channels)
        self.wav_file.setsampwidth(self.sample_width)
        self.wav_file.setframerate(self.sample_rate)
        
        self.start_time = time.time()
        self.is_closed = False
        
        self.logger.info(f"Starting single-track recording: {self.output_file}")

    def wants_opus(self) -> bool:
        """Indicate that we want to receive Opus data."""
        return False  # Use PCM for simpler mixing

    def write(self, user: discord.User, voice_data) -> None:
        """Write audio data from any user to the single track."""
        if not voice_data or not VOICE_RECV_AVAILABLE or self.is_closed:
            return

        try:
            # Get PCM data directly
            pcm_data = getattr(voice_data, "pcm", None)
            if not pcm_data:
                return

            # Write the PCM data directly to the single WAV file
            # Discord automatically mixes all audio sources, so we just record the mixed output
            self.wav_file.writeframes(pcm_data)
            
        except Exception as e:
            self.logger.error(f"Error writing audio data: {e}")

    def cleanup(self) -> None:
        """Clean up the recording sink."""
        if not self.is_closed:
            try:
                self.wav_file.close()
                self.is_closed = True
                
                # Check if file was created successfully
                if os.path.exists(self.output_file):
                    file_size = os.path.getsize(self.output_file)
                    duration = time.time() - self.start_time
                    self.logger.info(f"Recording completed: {self.output_file} ({file_size} bytes, {duration:.1f}s)")
                else:
                    self.logger.warning("Recording file was not created")
                    
            except Exception as e:
                self.logger.error(f"Error closing WAV file: {e}")


class MeetingRecorder:
    """Manage recording of a Discord voice channel with single-track output."""

    def __init__(self, bot, config) -> None:
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.audio_sink: Optional[SingleTrackRecordingSink] = None
        self.recording_task: Optional[asyncio.Task] = None

    async def record_meeting_audio(self, voice_channel_id: int) -> None:
        """Start recording audio from a voice channel to a single track."""
        if not VOICE_RECV_AVAILABLE:
            self.logger.error("discord-ext-voice-recv not installed - recording disabled")
            return

        # Get guild and voice channel
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if not guild:
            self.logger.error("Guild not found for recording")
            return

        voice_channel = guild.get_channel(voice_channel_id)
        if not isinstance(voice_channel, discord.VoiceChannel):
            self.logger.error(f"Voice channel {voice_channel_id} not found")
            return

        try:
            # Connect to voice channel
            voice_client = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
            
            # Create recording folder with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            folder = os.path.join("recordings", f"recording_{voice_channel_id}_{timestamp}")
            
            # Initialize single-track recording sink
            self.audio_sink = SingleTrackRecordingSink(folder)
            voice_client.listen(self.audio_sink)

            # Update meeting info for other modules
            meeting_info = self.bot.meeting_voice_channel_info.get(voice_channel_id, {})
            meeting_info.update({
                "recording_folder": folder,
                "recording_start_time": time.time(),
                "voice_client": voice_client,
                "audio_sink": self.audio_sink,
            })

            self.logger.info(f"Started single-track recording for voice channel: {voice_channel.name}")
            
            # Monitor the voice channel - stop when empty
            try:
                while voice_client.is_connected():
                    await asyncio.sleep(5)
                    
                    # Check if channel still exists and has non-bot members
                    channel = guild.get_channel(voice_channel_id)
                    if not channel or not any(member for member in channel.members if not member.bot):
                        self.logger.info("Voice channel empty - stopping recording")
                        break
                        
            except asyncio.CancelledError:
                self.logger.info("Recording cancelled")
            finally:
                await self._stop_and_cleanup(voice_client)
                
        except Exception as e:
            self.logger.error(f"Error during recording: {e}")
            if self.audio_sink:
                self.audio_sink.cleanup()

    async def _stop_and_cleanup(self, voice_client) -> None:
        """Stop recording and clean up resources."""
        try:
            # Stop listening and disconnect
            if voice_client and voice_client.is_connected():
                if hasattr(voice_client, "stop_listening"):
                    voice_client.stop_listening()
                await voice_client.disconnect()
                
        except Exception as e:
            self.logger.error(f"Error disconnecting voice client: {e}")

        # Clean up audio sink
        if self.audio_sink:
            self.audio_sink.cleanup()
            self.audio_sink = None

    async def stop_recording(self, voice_channel_id: int) -> bool:
        """Stop recording for a specific voice channel."""
        meeting_info = self.bot.meeting_voice_channel_info.get(voice_channel_id, {})
        voice_client = meeting_info.get("voice_client")
        
        if not voice_client:
            self.logger.warning(f"No active recording found for channel {voice_channel_id}")
            return False

        try:
            # Stop the recording task if it exists
            if self.recording_task and not self.recording_task.done():
                self.recording_task.cancel()
                
            # Stop listening
            if hasattr(voice_client, "stop_listening"):
                voice_client.stop_listening()
                
            self.logger.info(f"Recording stopped for voice channel {voice_channel_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error stopping recording: {e}")
            return False

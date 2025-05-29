"""
Meeting Recording Service with Advanced Audio Capture

Real audio recording with individual track separation using discord-ext-voice-recv.
Provides high-quality audio recording with per-user track isolation and real-time processing.

Features:
- Individual user track separation with discord-ext-voice-recv
- High-quality 48kHz 16-bit stereo WAV files  
- Real-time audio packet processing
- Comprehensive metadata generation
- Automatic monitoring and cleanup
"""

import asyncio
import logging
import os
import time
import wave
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
from collections import defaultdict

import discord

# Try to import voice receive extension
try:
    from discord.ext import voice_recv
    VOICE_RECV_AVAILABLE = True
except ImportError:
    VOICE_RECV_AVAILABLE = False
    voice_recv = None


class AdvancedMultiTrackSink(voice_recv.AudioSink if VOICE_RECV_AVAILABLE else object):
    """
    Advanced audio sink for individual track recording using discord-ext-voice-recv.
    Records each user to a separate high-quality WAV file with real-time processing.
    """
    
    def __init__(self, output_folder: str):
        if VOICE_RECV_AVAILABLE:
            super().__init__()
        self.output_folder = output_folder
        self.start_time = time.time()
        self.logger = logging.getLogger(__name__)
        self.user_files: Dict[int, wave.Wave_write] = {}
        self.user_info: Dict[int, Dict[str, Any]] = {}
        self.user_data_count: Dict[int, int] = defaultdict(int)
        self.total_packets = 0
        
        os.makedirs(output_folder, exist_ok=True)
        self.logger.info(f"Initialized advanced multi-track sink: {output_folder}")
        
    def wants_opus(self) -> bool:
        """Returns False to receive decoded PCM audio data."""
        return False
        
    def write(self, source, voice_data):
        """
        Process voice data from discord-ext-voice-recv.
        New API: write(self, source, voice_data)
        - source: The user who spoke
        - voice_data: The audio data object
        """
        try:
            if not voice_data:
                return
                
            # In the new API, source is the user and voice_data contains the audio
            user = source
            if not user:
                return
                
            # Try to get PCM data with error handling
            pcm_data = None
            if hasattr(voice_data, 'pcm'):
                pcm_data = voice_data.pcm
            elif hasattr(voice_data, 'data'):
                # Fallback to raw data if PCM is not available
                pcm_data = voice_data.data
            else:
                self.logger.debug("Voice data has no pcm or data attribute")
                return
                
            if not pcm_data:
                return
                
            user_id = user.id
            self.total_packets += 1
            
            # Initialize user recording if not exists
            if user_id not in self.user_files:
                self._init_user_recording(user)
                
            # Write PCM data to user's WAV file with additional error handling
            if user_id in self.user_files and self.user_files[user_id]:
                try:
                    self.user_files[user_id].writeframes(pcm_data)
                    self.user_data_count[user_id] += len(pcm_data)
                    
                    # Update user info
                    self.user_info[user_id].update({
                        'last_packet_time': time.time(),
                        'total_data': self.user_data_count[user_id]
                    })
                except Exception as write_error:
                    self.logger.debug(f"Error writing audio frames for user {user_id}: {write_error}")
                    # Continue processing other users even if one fails
                    
        except Exception as e:
            # More specific error handling for common Discord voice issues
            error_str = str(e).lower()
            if 'aead_xchacha20_poly1305' in error_str:
                self.logger.debug("Discord audio decryption error (expected with some packets)")
            elif 'rtpsize' in error_str:
                self.logger.debug("RTP packet size error (expected with some packets)")
            else:
                self.logger.warning(f"Unexpected voice data processing error: {e}")
            # Don't let individual packet errors stop the entire recording
            
    def _init_user_recording(self, user):
        """Initialize recording for a new user."""
        try:
            user_id = user.id
            username = user.display_name or user.name or f"user_{user_id}"
            # Clean filename for Windows compatibility
            clean_username = "".join(c for c in username if c.isalnum() or c in (' ', '-', '_')).strip()
            filename = f"user_{user_id}_{clean_username}.wav"
            filepath = os.path.join(self.output_folder, filename)
            
            # Create WAV file for this user
            wav_file = wave.open(filepath, 'wb')
            wav_file.setnchannels(2)      # Stereo
            wav_file.setsampwidth(2)      # 16-bit
            wav_file.setframerate(48000)  # 48kHz
            
            self.user_files[user_id] = wav_file
            self.user_info[user_id] = {
                'username': clean_username,
                'filename': filename,
                'filepath': filepath,
                'start_time': time.time(),
                'total_data': 0,
                'last_packet_time': time.time()
            }
            
            self.logger.info(f"Started recording for user {clean_username} ({user_id})")
            
        except Exception as e:
            self.logger.error(f"Error initializing user recording: {e}")
            
    def cleanup(self):
        """Close all user recording files and generate metadata."""
        try:
            # Close all WAV files
            for user_id, wav_file in self.user_files.items():
                if wav_file:
                    wav_file.close()
                    
            self.logger.info(f"Closed {len(self.user_files)} user recording files")
            
            # Generate comprehensive metadata
            self._generate_metadata()
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            
    def _generate_metadata(self):
        """Generate detailed recording metadata."""
        try:
            metadata_file = os.path.join(self.output_folder, "advanced_recording_metadata.txt")
            with open(metadata_file, "w", encoding="utf-8") as f:
                f.write("Advanced Multi-Track Recording Metadata\n")
                f.write("=" * 42 + "\n\n")
                
                f.write(f"Recording Method: Advanced (discord-ext-voice-recv)\n")
                f.write(f"Start Time: {datetime.fromtimestamp(self.start_time)}\n")
                f.write(f"End Time: {datetime.now()}\n")
                f.write(f"Duration: {time.time() - self.start_time:.2f} seconds\n")
                f.write(f"Total Packets Processed: {self.total_packets}\n")
                f.write(f"Users Recorded: {len(self.user_files)}\n\n")
                
                f.write("Audio Settings:\n")
                f.write("- Format: WAV\n")
                f.write("- Sample Rate: 48000 Hz\n")
                f.write("- Channels: 2 (Stereo)\n")
                f.write("- Bit Depth: 16-bit\n")
                f.write("- Track Separation: Individual per user\n\n")
                
                f.write("User Recording Details:\n")
                for user_id, info in self.user_info.items():
                    duration = info['last_packet_time'] - info['start_time']
                    data_mb = info['total_data'] / (1024 * 1024)
                    f.write(f"- {info['username']} (ID: {user_id})\n")
                    f.write(f"  File: {info['filename']}\n")
                    f.write(f"  Duration: {duration:.2f} seconds\n")
                    f.write(f"  Data: {data_mb:.2f} MB\n\n")
                    
            self.logger.info(f"Generated advanced recording metadata: {metadata_file}")
            
        except Exception as e:
            self.logger.error(f"Error generating metadata: {e}")


class MeetingRecorder:
    """
    Advanced meeting recorder with high-quality audio capture and individual track separation.
    
    Features:
    - Real-time audio capture using discord-ext-voice-recv
    - Individual user track separation (each user gets their own WAV file)
    - High-quality 48kHz 16-bit stereo recording
    - Real-time monitoring and automatic stop conditions
    - Comprehensive metadata generation
    """
    
    def __init__(self, bot, config):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.audio_sink: Optional[AdvancedMultiTrackSink] = None
        self.recording_method = "none"
        
        # Log available recording methods
        self.logger.info(f"discord-ext-voice-recv available: {VOICE_RECV_AVAILABLE}")
        self.logger.info(f"discord.py version: {discord.__version__}")
        
        if not VOICE_RECV_AVAILABLE:
            self.logger.error("discord-ext-voice-recv not available! Advanced recording will not work.")
            self.logger.error("Please install: pip install discord-ext-voice-recv")
        
    async def record_meeting_audio(self, voice_channel_id: int):
        """
        Record meeting audio with individual track separation.
        """
        if not VOICE_RECV_AVAILABLE:
            self.logger.error("Cannot start recording: discord-ext-voice-recv not available")
            return
            
        meeting_info = self.bot.meeting_voice_channel_info.get(voice_channel_id, {})
        
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if not guild:
            self.logger.error("Guild not found for recording")
            return
            
        voice_channel = guild.get_channel(voice_channel_id)
        if not voice_channel or not isinstance(voice_channel, discord.VoiceChannel):
            self.logger.error(f"Voice channel {voice_channel_id} not found or invalid type")
            return
            
        # Disconnect any existing voice client
        for vc in self.bot.voice_clients:
            if vc.guild == guild:
                try:
                    await vc.disconnect(force=True)
                except Exception as e:
                    self.logger.error(f"Error disconnecting existing voice client: {e}")
                    
        # Connect using VoiceRecvClient for advanced recording
        try:
            self.logger.info(f"Attempting to connect to voice channel: {voice_channel.name}")
            voice_client = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
            self.recording_method = "advanced"
            self.logger.info(f"Successfully connected using VoiceRecvClient to {voice_channel.name}")
                
        except discord.errors.ConnectionClosed as conn_error:
            self.logger.error(f"Discord connection closed during voice connect: {conn_error}")
            self.logger.error("This may be due to Discord rate limiting or network issues")
            return
        except Exception as error:
            self.logger.error(f"Failed to connect to {voice_channel.name}: {error}")
            self.logger.error("Retrying with standard voice client as fallback...")
            
            # Fallback to standard voice client if VoiceRecvClient fails
            try:
                voice_client = await voice_channel.connect()
                self.recording_method = "basic_fallback"
                self.logger.warning("Connected with basic voice client - no recording capabilities")
                return  # Exit early as basic client can't record
            except Exception as fallback_error:
                self.logger.error(f"Fallback connection also failed: {fallback_error}")
                return
            
        # Create output folder with timestamp
        current_time = datetime.now()
        folder_name = f"recording_{voice_channel_id}_{current_time.strftime('%Y%m%d_%H%M%S')}_advanced"
        output_folder = os.path.join("recordings", folder_name)
        
        try:
            # Start advanced recording
            await self._start_advanced_recording(voice_client, output_folder, voice_channel)
            
            # Store recording info
            meeting_info.update({
                "recording_folder": output_folder,
                "recording_start_time": time.time(),
                "voice_client": voice_client,
                "audio_sink": self.audio_sink,
                "recording_method": self.recording_method
            })
            
            self.logger.info(f"Started advanced recording for {voice_channel.name}")
            self.logger.info(f"Recording to folder: {output_folder}")
            
            # Monitor recording
            await self._monitor_recording(voice_channel_id, voice_channel, guild)
            
        except asyncio.CancelledError:
            self.logger.info(f"Recording cancelled for channel {voice_channel.name}")
        except Exception as error:
            self.logger.error(f"Error during recording: {error}")
        finally:
            # Stop recording and cleanup
            await self._stop_and_cleanup(voice_client, output_folder, voice_channel_id, meeting_info)
            
    async def _start_advanced_recording(self, voice_client, output_folder: str, voice_channel):
        """Start advanced recording with individual track separation."""
        
        try:
            # Create advanced multi-track sink
            self.audio_sink = AdvancedMultiTrackSink(output_folder)
            
            # Start listening with the sink and error handling
            self.logger.info("Starting voice listening with advanced sink...")
            voice_client.listen(self.audio_sink)
            
            self.logger.info("Successfully started advanced recording with individual track separation")
            self.logger.info("Each user will be recorded to a separate high-quality WAV file")
            self.logger.info("Note: Some Discord audio decryption warnings are normal and expected")
            
        except Exception as e:
            self.logger.error(f"Error starting advanced recording: {e}")
            self.logger.error("Recording may not capture audio properly")
            raise  # Re-raise to be handled by caller
        
    async def _monitor_recording(self, voice_channel_id: int, voice_channel, guild):
        """Monitor recording and handle automatic stop conditions."""
        
        while True:
            await asyncio.sleep(5)  # Check every 5 seconds
            
            # Check if channel still exists
            current_channel = guild.get_channel(voice_channel_id)
            if not current_channel:
                self.logger.info(f"Voice channel {voice_channel_id} no longer exists, stopping recording")
                break
                
            # Check if there are any non-bot members
            human_members = [m for m in current_channel.members if not m.bot]
            if not human_members:
                self.logger.info(f"No human participants in {voice_channel.name}, stopping recording")
                break
                
            # Log recording status
            if self.audio_sink and hasattr(self.audio_sink, 'user_info'):
                active_users = len(self.audio_sink.user_info)
                total_packets = self.audio_sink.total_packets
                self.logger.debug(f"Recording: {active_users} users, {total_packets} packets processed")
                
    async def _stop_and_cleanup(self, voice_client, output_folder: str, voice_channel_id: int, meeting_info: Dict[str, Any]):
        """Stop recording and perform cleanup."""
        
        try:
            # Stop recording
            if voice_client and voice_client.is_connected():
                if hasattr(voice_client, 'stop_listening'):
                    voice_client.stop_listening()
                    self.logger.info("Stopped voice listening")
                    
                await voice_client.disconnect()
                self.logger.info("Disconnected from voice channel")
                
            # Cleanup audio sink
            if self.audio_sink and hasattr(self.audio_sink, 'cleanup'):
                self.audio_sink.cleanup()
                self.logger.info("Completed audio sink cleanup")
                
        except Exception as e:
            self.logger.error(f"Error during recording cleanup: {e}")
            
        # Process recording end
        await self._finish_recording(voice_channel_id, meeting_info)
    
    async def _finish_recording(self, channel_id: int, meeting_info: Dict[str, Any]):
        """Process recording completion and verify files."""
        
        try:
            recording_folder = meeting_info.get("recording_folder")
            if not recording_folder:
                return
                
            # Create session summary
            metadata = {
                "channel_id": channel_id,
                "recording_method": self.recording_method,
                "start_time": meeting_info.get("recording_start_time"),
                "end_time": time.time(),
                "participants": list(meeting_info.get("all_participants", [])),
                "forum_thread_id": meeting_info.get("forum_thread_id"),
                "recording_format": "WAV",
                "sample_rate": "48000 Hz",
                "channels": "2 (Stereo)",
                "bit_depth": "16-bit",
                "track_separation": "Individual user tracks",
                "quality": "Excellent",
                "voice_recv_available": VOICE_RECV_AVAILABLE,
                "discord_py_version": discord.__version__
            }
            
            # Save session summary
            summary_file = os.path.join(recording_folder, "session_summary.txt")
            with open(summary_file, "w", encoding="utf-8") as f:
                f.write("Advanced Meeting Recording Session Summary\n")
                f.write("=" * 45 + "\n\n")
                
                for key, value in metadata.items():
                    f.write(f"{key}: {value}\n")
                    
                duration = metadata["end_time"] - metadata["start_time"]
                f.write(f"\nTotal Recording Duration: {duration:.2f} seconds\n")
                
                f.write(f"\nQuality Assessment:\n")
                f.write("- Excellent: Individual track separation with high quality\n")
                f.write("- Real-time packet processing with discord-ext-voice-recv\n")
                f.write("- 48kHz 16-bit stereo WAV files for optimal post-processing\n")
                f.write("- Each participant recorded to separate audio file\n")
                    
            self.logger.info(f"Saved session summary to {summary_file}")
            
            # Verify recorded files
            if os.path.exists(recording_folder):
                recorded_files = [f for f in os.listdir(recording_folder) if f.endswith('.wav')]
                self.logger.info(f"Recording completed successfully:")
                self.logger.info(f"  Method: Advanced (individual track separation)")
                self.logger.info(f"  WAV files: {len(recorded_files)}")
                self.logger.info(f"  Folder: {recording_folder}")
                
                # Verify file sizes
                total_size = 0
                for file in recorded_files:
                    file_path = os.path.join(recording_folder, file)
                    if os.path.exists(file_path):
                        file_size = os.path.getsize(file_path) / (1024 * 1024)  # MB
                        total_size += file_size
                        self.logger.info(f"    - {file}: {file_size:.2f} MB")
                    
                self.logger.info(f"  Total size: {total_size:.2f} MB")
                
                if len(recorded_files) == 0:
                    self.logger.warning("No audio files were created - check if users were speaking")
                
            else:
                self.logger.error(f"Recording folder {recording_folder} not found")
                
        except Exception as e:
            self.logger.error(f"Error finishing recording: {e}")
            
    async def stop_recording(self, voice_channel_id: int) -> bool:
        """Manually stop recording for a channel."""
        
        meeting_info = self.bot.meeting_voice_channel_info.get(voice_channel_id, {})
        voice_client = meeting_info.get("voice_client")
        
        if not voice_client:
            self.logger.warning(f"No active recording found for channel {voice_channel_id}")
            return False
            
        try:
            if hasattr(voice_client, 'stop_listening'):
                voice_client.stop_listening()
                
            self.logger.info(f"Manually stopped advanced recording for channel {voice_channel_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error stopping recording: {e}")
            return False 
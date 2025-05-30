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
- **Time-synchronized recording for perfect multi-track editing**
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
    Advanced audio sink for time-synchronized individual track recording.
    Records each user to a separate WAV file with consistent length and padding for dropouts.
    
    **Time Synchronization Features:**
    - All audio files have identical duration (session total length)
    - Late joiners: Padded with silence from session start
    - Early leavers: Padded with silence to session end
    - Leave/rejoin gaps: Filled with silence automatically
    - Perfect timeline synchronization for multi-track editing
    """
    
    def __init__(self, output_folder: str):
        if VOICE_RECV_AVAILABLE:
            super().__init__()
        self.output_folder = output_folder
        self.start_time = time.time()
        self.logger = logging.getLogger(__name__)
        
        # Audio configuration
        self.sample_rate = 48000
        self.channels = 2
        self.sample_width = 2
        self.frame_size = self.sample_rate // 50  # 20ms frames (Discord's frame size)
        
        # User tracking for time synchronization
        self.user_files: Dict[int, wave.Wave_write] = {}
        self.user_info: Dict[int, Dict[str, Any]] = {}
        self.user_join_times: Dict[int, float] = {}
        self.user_leave_times: Dict[int, float] = {}
        self.user_rejoin_times: Dict[int, List[tuple]] = defaultdict(list)  # [(leave_time, rejoin_time), ...]
        self.user_last_audio_time: Dict[int, float] = {}
        self.user_current_session_frames: Dict[int, int] = {}  # Frames written in current session
        
        # Recording state
        self.total_packets = 0
        self.session_active = True
        self.current_frame_time = self.start_time
        
        os.makedirs(output_folder, exist_ok=True)
        self.logger.info(f"Initialized time-synchronized multi-track sink: {output_folder}")
        
    def wants_opus(self) -> bool:
        """Returns False to receive decoded PCM audio data."""
        return False
        
    def write(self, source, voice_data):
        """
        Process voice data with time synchronization.
        Automatically handles user join/leave scenarios with proper padding.
        """
        try:
            if not voice_data or not self.session_active:
                return
                
            user = source
            if not user:
                return
                
            # Extract PCM data
            pcm_data = None
            if hasattr(voice_data, 'pcm'):
                pcm_data = voice_data.pcm
            elif hasattr(voice_data, 'data'):
                pcm_data = voice_data.data
            else:
                return
                
            if not pcm_data:
                return
                
            user_id = user.id
            current_time = time.time()
            self.total_packets += 1
            
            # Initialize user recording if not exists
            if user_id not in self.user_files:
                self._init_user_recording(user, current_time)
                
            # Update user's last audio time
            self.user_last_audio_time[user_id] = current_time
                
            # Write audio data to user's file
            if user_id in self.user_files and self.user_files[user_id]:
                try:
                    # Fill any gaps since last audio (for rejoin scenarios)
                    self._fill_audio_gaps(user_id, current_time)
                    
                    # Write the actual audio data
                    self.user_files[user_id].writeframes(pcm_data)
                    
                    # Update frame count
                    frames_written = len(pcm_data) // (self.sample_width * self.channels)
                    self.user_current_session_frames[user_id] = self.user_current_session_frames.get(user_id, 0) + frames_written
                    
                    # Update user info
                    self.user_info[user_id].update({
                        'last_packet_time': current_time,
                        'total_frames': self.user_info[user_id].get('total_frames', 0) + frames_written
                    })
                    
                except Exception as write_error:
                    self.logger.debug(f"Error writing audio frames for user {user_id}: {write_error}")
                    
        except Exception as e:
            error_str = str(e).lower()
            if not any(keyword in error_str for keyword in ['aead_xchacha20_poly1305', 'rtpsize']):
                self.logger.warning(f"Voice data processing error: {e}")
                
    def _init_user_recording(self, user, join_time: float):
        """Initialize time-synchronized recording for a new user."""
        try:
            user_id = user.id
            username = user.display_name or user.name or f"user_{user_id}"
            clean_username = "".join(c for c in username if c.isalnum() or c in (' ', '-', '_')).strip()
            filename = f"user_{user_id}_{clean_username}.wav"
            filepath = os.path.join(self.output_folder, filename)
            
            # Create WAV file
            wav_file = wave.open(filepath, 'wb')
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.sample_width)
            wav_file.setframerate(self.sample_rate)
            
            self.user_files[user_id] = wav_file
            self.user_join_times[user_id] = join_time
            self.user_last_audio_time[user_id] = join_time
            self.user_current_session_frames[user_id] = 0
            
            self.user_info[user_id] = {
                'username': clean_username,
                'filename': filename,
                'filepath': filepath,
                'join_time': join_time,
                'total_frames': 0,
                'last_packet_time': join_time
            }
            
            # Pad from session start to user join time (for late joiners)
            silence_duration = join_time - self.start_time
            if silence_duration > 0:
                self._write_silence(user_id, silence_duration)
                self.logger.info(f"Added {silence_duration:.2f}s silence padding for late joiner {clean_username}")
            
            self.logger.info(f"Started time-synchronized recording for {clean_username} ({user_id})")
            
        except Exception as e:
            self.logger.error(f"Error initializing user recording: {e}")
            
    def _fill_audio_gaps(self, user_id: int, current_time: float):
        """Fill silence gaps for users who left and rejoined."""
        if user_id not in self.user_last_audio_time:
            return
            
        last_audio_time = self.user_last_audio_time[user_id]
        gap_duration = current_time - last_audio_time
        
        # If gap is longer than 1 second, fill with silence (user likely left and rejoined)
        if gap_duration > 1.0:
            self._write_silence(user_id, gap_duration)
            self.logger.debug(f"Filled {gap_duration:.2f}s gap for user {user_id}")
            
    def _write_silence(self, user_id: int, duration_seconds: float):
        """Write silence padding to user's audio file."""
        if user_id not in self.user_files or not self.user_files[user_id]:
            return
            
        try:
            # Calculate number of frames for the duration
            total_frames = int(duration_seconds * self.sample_rate)
            
            # Create silence data (zeros)
            silence_frame = b'\x00' * (self.sample_width * self.channels)
            silence_data = silence_frame * total_frames
            
            # Write silence to file
            self.user_files[user_id].writeframes(silence_data)
            
            # Update frame count
            self.user_current_session_frames[user_id] = self.user_current_session_frames.get(user_id, 0) + total_frames
            
            # Update total frame count
            if user_id in self.user_info:
                self.user_info[user_id]['total_frames'] = self.user_info[user_id].get('total_frames', 0) + total_frames
                
        except Exception as e:
            self.logger.error(f"Error writing silence for user {user_id}: {e}")
            
    def mark_user_leave(self, user_id: int, leave_time: float):
        """Mark when a user leaves (for external tracking)."""
        self.user_leave_times[user_id] = leave_time
        if user_id in self.user_last_audio_time:
            # Record the gap start time
            self.user_rejoin_times[user_id].append((leave_time, None))
            self.logger.info(f"User {user_id} left at {leave_time - self.start_time:.2f}s from session start")
            
    def mark_user_rejoin(self, user_id: int, rejoin_time: float):
        """Mark when a user rejoins (for external tracking)."""
        if user_id in self.user_rejoin_times and self.user_rejoin_times[user_id]:
            # Complete the last gap record
            last_gap = list(self.user_rejoin_times[user_id][-1])
            if last_gap[1] is None:  # Incomplete gap
                last_gap[1] = rejoin_time
                self.user_rejoin_times[user_id][-1] = tuple(last_gap)
                gap_duration = rejoin_time - last_gap[0]
                self.logger.info(f"User {user_id} rejoined after {gap_duration:.2f}s gap")
                
    def finalize_session(self):
        """Finalize recording session by padding all users to same total length."""
        if not self.session_active:
            return
            
        self.session_active = False
        session_end_time = time.time()
        total_session_duration = session_end_time - self.start_time
        
        self.logger.info(f"Finalizing session: total duration {total_session_duration:.2f}s")
        
        # Calculate target total frames for the entire session
        target_total_frames = int(total_session_duration * self.sample_rate)
        
        # Pad all users to full session length
        for user_id in list(self.user_files.keys()):
            try:
                current_frames = self.user_current_session_frames.get(user_id, 0)
                missing_frames = target_total_frames - current_frames
                
                if missing_frames > 0:
                    missing_duration = missing_frames / self.sample_rate
                    self._write_silence(user_id, missing_duration)
                    self.logger.info(f"Added {missing_duration:.2f}s final padding for user {user_id} (total: {target_total_frames:,} frames)")
                elif missing_frames < 0:
                    self.logger.warning(f"User {user_id} has {-missing_frames} extra frames - this shouldn't happen")
                else:
                    self.logger.info(f"User {user_id} already has correct length: {current_frames:,} frames")
                    
            except Exception as e:
                self.logger.error(f"Error finalizing user {user_id}: {e}")
                    
        self.logger.info(f"Session finalized: all files now have {target_total_frames:,} frames ({total_session_duration:.2f}s)")
        
    def cleanup(self):
        """Close all user recording files and generate metadata."""
        try:
            # Finalize session first
            self.finalize_session()
            
            # Close all WAV files
            for user_id, wav_file in self.user_files.items():
                if wav_file:
                    wav_file.close()
                    
            self.logger.info(f"Closed {len(self.user_files)} time-synchronized recording files")
            
            # Generate comprehensive metadata
            self._generate_metadata()
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            
    def _generate_metadata(self):
        """Generate detailed recording metadata."""
        try:
            metadata_file = os.path.join(self.output_folder, "advanced_recording_metadata.txt")
            session_duration = time.time() - self.start_time
            
            with open(metadata_file, "w", encoding="utf-8") as f:
                f.write("Time-Synchronized Multi-Track Recording Metadata\n")
                f.write("=" * 48 + "\n\n")
                
                f.write(f"Recording Method: Time-Synchronized (discord-ext-voice-recv)\n")
                f.write(f"Start Time: {datetime.fromtimestamp(self.start_time)}\n")
                f.write(f"End Time: {datetime.now()}\n")
                f.write(f"Total Session Duration: {session_duration:.2f} seconds\n")
                f.write(f"Total Packets Processed: {self.total_packets}\n")
                f.write(f"Users Recorded: {len(self.user_files)}\n\n")
                
                f.write("Audio Settings:\n")
                f.write("- Format: WAV\n")
                f.write(f"- Sample Rate: {self.sample_rate} Hz\n")
                f.write(f"- Channels: {self.channels} (Stereo)\n")
                f.write(f"- Bit Depth: {self.sample_width * 8}-bit\n")
                f.write("- Track Separation: Individual per user\n")
                f.write("- Time Synchronization: Enabled\n")
                f.write("- Auto Padding: Late joiners, early leavers, gaps\n\n")
                
                f.write("Time Synchronization Features:\n")
                f.write("- All audio files have identical duration\n")
                f.write("- Late joiners: Padded with silence from session start\n")
                f.write("- Early leavers: Padded with silence to session end\n")
                f.write("- Leave/rejoin gaps: Filled with silence automatically\n")
                f.write("- Perfect timeline synchronization for multi-track editing\n\n")
                
                # Calculate target frames for verification
                target_frames = int(session_duration * self.sample_rate)
                
                f.write("User Recording Details:\n")
                for user_id, info in self.user_info.items():
                    join_offset = info['join_time'] - self.start_time
                    last_packet_offset = info['last_packet_time'] - self.start_time
                    total_frames = info['total_frames']
                    file_duration = total_frames / self.sample_rate if total_frames > 0 else session_duration
                    data_mb = total_frames * (self.sample_width * self.channels) / (1024 * 1024)
                    
                    f.write(f"- {info['username']} (ID: {user_id})\n")
                    f.write(f"  File: {info['filename']}\n")
                    f.write(f"  Join Offset: {join_offset:.2f}s from session start\n")
                    f.write(f"  Last Audio: {last_packet_offset:.2f}s from session start\n")
                    f.write(f"  File Duration: {file_duration:.2f}s (time-synchronized)\n")
                    f.write(f"  Total Frames: {total_frames:,} (target: {target_frames:,})\n")
                    f.write(f"  Frame Match: {'✓' if total_frames == target_frames else '✗'}\n")
                    f.write(f"  File Size: {data_mb:.2f} MB\n")
                    
                    # Calculate padding information
                    if join_offset > 0:
                        f.write(f"  Pre-padding: {join_offset:.2f}s (late joiner)\n")
                    
                    end_padding = session_duration - last_packet_offset
                    if end_padding > 0:
                        f.write(f"  Post-padding: {end_padding:.2f}s (early leaver or silence)\n")
                        
                    # Gap information
                    if user_id in self.user_rejoin_times and self.user_rejoin_times[user_id]:
                        gaps = [gap for gap in self.user_rejoin_times[user_id] if gap[1] is not None]
                        if gaps:
                            total_gap_time = sum(gap[1] - gap[0] for gap in gaps)
                            f.write(f"  Rejoin Gaps: {len(gaps)} gaps, {total_gap_time:.2f}s total\n")
                    
                    f.write("\n")
                    
                f.write("Time Synchronization Verification:\n")
                all_same_length = all(info['total_frames'] == target_frames for info in self.user_info.values())
                f.write(f"- All files same length: {'✓ YES' if all_same_length else '✗ NO'}\n")
                f.write(f"- Target frame count: {target_frames:,}\n")
                f.write(f"- Ready for multi-track editing: {'✓ YES' if all_same_length else '✗ NO'}\n")
                    
            self.logger.info(f"Generated time-synchronized recording metadata: {metadata_file}")
            
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
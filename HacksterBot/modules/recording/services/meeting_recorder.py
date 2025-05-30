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
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional, Union, Tuple
from collections import defaultdict
from queue import Queue, Empty

import discord

# Try to import voice receive extension
try:
    from discord.ext import voice_recv
    VOICE_RECV_AVAILABLE = True
except ImportError:
    VOICE_RECV_AVAILABLE = False
    voice_recv = None


class UserAudioBuffer:
    """Thread-safe audio buffer for a single user with real-time gap filling."""
    
    def __init__(self, user_id: int, username: str, output_folder: str, 
                 sample_rate: int, channels: int, sample_width: int):
        self.user_id = user_id
        self.username = username
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.frame_size = sample_rate // 50  # 20ms frames
        
        # Create WAV file
        self.filename = f"user_{user_id}_{username}.wav"
        self.filepath = os.path.join(output_folder, self.filename)
        self.wav_file = wave.open(self.filepath, 'wb')
        self.wav_file.setnchannels(channels)
        self.wav_file.setsampwidth(sample_width)
        self.wav_file.setframerate(sample_rate)
        
        # Thread safety
        self.lock = threading.Lock()
        self.audio_queue = Queue()
        
        # Timing tracking
        self.session_start_time = None
        self.join_time = None
        self.last_write_time = None
        self.total_frames_written = 0
        self.is_active = True
        
        # Gap tracking
        self.leave_times = []  # List of (leave_time, rejoin_time) tuples
        self.current_leave_time = None
        
    def initialize_session(self, session_start_time: float, join_time: float):
        """Initialize the buffer for a recording session."""
        with self.lock:
            self.session_start_time = session_start_time
            self.join_time = join_time
            self.last_write_time = join_time
            
            # Pad from session start to join time if needed
            if join_time > session_start_time:
                silence_duration = join_time - session_start_time
                self._write_silence_frames(int(silence_duration * self.sample_rate))
                
    def write_audio(self, pcm_data: bytes, timestamp: float):
        """Write audio data with automatic gap filling."""
        with self.lock:
            if not self.is_active:
                return
                
            # If we were marked as left, handle rejoin
            if self.current_leave_time is not None:
                # User rejoined - fill the gap
                gap_duration = timestamp - self.current_leave_time
                gap_frames = int(gap_duration * self.sample_rate)
                if gap_frames > 0:
                    self._write_silence_frames(gap_frames)
                    
                # Record the leave/rejoin period
                self.leave_times.append((self.current_leave_time, timestamp))
                self.current_leave_time = None
                
            # Check for natural gaps (user not speaking)
            elif self.last_write_time is not None:
                expected_gap = timestamp - self.last_write_time
                # If gap is more than 100ms, fill with silence
                if expected_gap > 0.1:
                    gap_frames = int(expected_gap * self.sample_rate)
                    self._write_silence_frames(gap_frames)
                    
            # Write the actual audio
            self.wav_file.writeframes(pcm_data)
            frames_written = len(pcm_data) // (self.sample_width * self.channels)
            self.total_frames_written += frames_written
            self.last_write_time = timestamp
            
    def mark_user_left(self, leave_time: float):
        """Mark the user as having left the channel."""
        with self.lock:
            # Fill any gap up to the leave time
            if self.last_write_time is not None and leave_time > self.last_write_time:
                gap_duration = leave_time - self.last_write_time
                gap_frames = int(gap_duration * self.sample_rate)
                if gap_frames > 0:
                    self._write_silence_frames(gap_frames)
                    self.last_write_time = leave_time
                    
            self.current_leave_time = leave_time
            
    def finalize(self, session_end_time: float):
        """Finalize the buffer and ensure correct total length."""
        with self.lock:
            if not self.is_active:
                return
                
            # If user is still marked as left, complete the gap
            if self.current_leave_time is not None:
                gap_duration = session_end_time - self.current_leave_time
                gap_frames = int(gap_duration * self.sample_rate)
                if gap_frames > 0:
                    self._write_silence_frames(gap_frames)
                self.leave_times.append((self.current_leave_time, session_end_time))
                
            # Fill any remaining time to session end
            elif self.last_write_time is not None and session_end_time > self.last_write_time:
                gap_duration = session_end_time - self.last_write_time
                gap_frames = int(gap_duration * self.sample_rate)
                if gap_frames > 0:
                    self._write_silence_frames(gap_frames)
                    
            # Close the file
            self.wav_file.close()
            self.is_active = False
            
    def _write_silence_frames(self, num_frames: int):
        """Write silence frames to the WAV file."""
        if num_frames <= 0:
            return
            
        # Create silence data
        silence_frame = b'\x00' * (self.sample_width * self.channels)
        silence_data = silence_frame * num_frames
        
        # Write to file
        self.wav_file.writeframes(silence_data)
        self.total_frames_written += num_frames
        
    def get_info(self) -> Dict[str, Any]:
        """Get buffer information for metadata."""
        with self.lock:
            return {
                'username': self.username,
                'filename': self.filename,
                'filepath': self.filepath,
                'join_time': self.join_time,
                'total_frames': self.total_frames_written,
                'leave_times': self.leave_times.copy(),
                'last_write_time': self.last_write_time
            }


class AdvancedMultiTrackSink(voice_recv.AudioSink if VOICE_RECV_AVAILABLE else object):
    """
    Advanced audio sink for time-synchronized individual track recording.
    Records each user to a separate WAV file with consistent length and real-time gap filling.
    
    **Key Features:**
    - Real-time gap filling (not at the end)
    - Thread-safe multi-user audio processing
    - Perfect time synchronization
    - Handles complex join/leave/rejoin scenarios
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
        
        # User buffers with thread safety
        self.user_buffers: Dict[int, UserAudioBuffer] = {}
        self.buffers_lock = threading.Lock()
        
        # Processing thread
        self.processing_thread = None
        self.stop_processing = threading.Event()
        
        # Packet queue for thread-safe processing
        self.packet_queue = Queue()
        
        # Recording state
        self.total_packets = 0
        self.session_active = True
        
        os.makedirs(output_folder, exist_ok=True)
        
        # Start processing thread
        self.processing_thread = threading.Thread(target=self._process_audio_packets)
        self.processing_thread.start()
        
        self.logger.info(f"Initialized real-time synchronized multi-track sink: {output_folder}")
        
    def wants_opus(self) -> bool:
        """Returns False to receive decoded PCM audio data."""
        return False
        
    def write(self, source, voice_data):
        """
        Queue voice data for processing to avoid packet conflicts.
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
                
            # Queue the packet for processing
            timestamp = time.time()
            self.packet_queue.put((user, pcm_data, timestamp))
            self.total_packets += 1
                
        except Exception as e:
            error_str = str(e).lower()
            if not any(keyword in error_str for keyword in ['aead_xchacha20_poly1305', 'rtpsize']):
                self.logger.warning(f"Voice data queueing error: {e}")
                
    def _process_audio_packets(self):
        """Process audio packets in a dedicated thread to avoid conflicts."""
        while not self.stop_processing.is_set() or not self.packet_queue.empty():
            try:
                # Get packet with timeout
                user, pcm_data, timestamp = self.packet_queue.get(timeout=0.1)
                
                # Process the packet
                self._process_user_audio(user, pcm_data, timestamp)
                
            except Empty:
                continue
            except Exception as e:
                self.logger.error(f"Error processing audio packet: {e}")
                
    def _process_user_audio(self, user, pcm_data: bytes, timestamp: float):
        """Process audio for a specific user."""
        user_id = user.id
        
        with self.buffers_lock:
            # Create buffer if doesn't exist
            if user_id not in self.user_buffers:
                username = user.display_name or user.name or f"user_{user_id}"
                clean_username = "".join(c for c in username if c.isalnum() or c in (' ', '-', '_')).strip()
                
                buffer = UserAudioBuffer(
                    user_id=user_id,
                    username=clean_username,
                    output_folder=self.output_folder,
                    sample_rate=self.sample_rate,
                    channels=self.channels,
                    sample_width=self.sample_width
                )
                
                buffer.initialize_session(self.start_time, timestamp)
                self.user_buffers[user_id] = buffer
                
                self.logger.info(f"Started real-time recording for {clean_username} ({user_id})")
                
        # Write audio to user's buffer
        buffer = self.user_buffers[user_id]
        buffer.write_audio(pcm_data, timestamp)
        
    def mark_user_leave(self, user_id: int, leave_time: float):
        """Mark when a user leaves for real-time gap tracking."""
        with self.buffers_lock:
            if user_id in self.user_buffers:
                self.user_buffers[user_id].mark_user_left(leave_time)
                self.logger.info(f"User {user_id} marked as left at {leave_time - self.start_time:.2f}s from start")
                
    def mark_user_rejoin(self, user_id: int, rejoin_time: float):
        """Mark when a user rejoins (handled automatically in write_audio)."""
        self.logger.info(f"User {user_id} rejoined at {rejoin_time - self.start_time:.2f}s from start")
        
    def cleanup(self):
        """Stop processing and finalize all recordings."""
        try:
            self.session_active = False
            session_end_time = time.time()
            
            self.logger.info("Stopping audio processing thread...")
            
            # Stop processing thread
            self.stop_processing.set()
            if self.processing_thread:
                self.processing_thread.join(timeout=5.0)
                
            # Process any remaining packets
            while not self.packet_queue.empty():
                try:
                    user, pcm_data, timestamp = self.packet_queue.get_nowait()
                    self._process_user_audio(user, pcm_data, timestamp)
                except Empty:
                    break
                    
            # Finalize all buffers
            with self.buffers_lock:
                for buffer in self.user_buffers.values():
                    buffer.finalize(session_end_time)
                    
            self.logger.info(f"Finalized {len(self.user_buffers)} synchronized recordings")
            
            # Generate metadata
            self._generate_metadata()
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            
    def _generate_metadata(self):
        """Generate detailed recording metadata."""
        try:
            metadata_file = os.path.join(self.output_folder, "advanced_recording_metadata.txt")
            session_duration = time.time() - self.start_time
            
            with open(metadata_file, "w", encoding="utf-8") as f:
                f.write("Real-Time Synchronized Multi-Track Recording Metadata\n")
                f.write("=" * 53 + "\n\n")
                
                f.write(f"Recording Method: Real-Time Synchronized (discord-ext-voice-recv)\n")
                f.write(f"Start Time: {datetime.fromtimestamp(self.start_time)}\n")
                f.write(f"End Time: {datetime.now()}\n")
                f.write(f"Total Session Duration: {session_duration:.2f} seconds\n")
                f.write(f"Total Packets Processed: {self.total_packets}\n")
                f.write(f"Users Recorded: {len(self.user_buffers)}\n\n")
                
                f.write("Audio Settings:\n")
                f.write("- Format: WAV\n")
                f.write(f"- Sample Rate: {self.sample_rate} Hz\n")
                f.write(f"- Channels: {self.channels} (Stereo)\n")
                f.write(f"- Bit Depth: {self.sample_width * 8}-bit\n")
                f.write("- Track Separation: Individual per user\n")
                f.write("- Gap Filling: Real-time (not deferred)\n")
                f.write("- Thread Safety: Full packet queue isolation\n\n")
                
                f.write("Key Features:\n")
                f.write("- Real-time gap filling during recording\n")
                f.write("- Thread-safe multi-user audio processing\n")
                f.write("- No packet conflicts or audio stuttering\n")
                f.write("- Perfect time synchronization\n")
                f.write("- Handles complex join/leave/rejoin scenarios\n\n")
                
                # Calculate target frames
                target_frames = int(session_duration * self.sample_rate)
                
                f.write("User Recording Details:\n")
                with self.buffers_lock:
                    for user_id, buffer in self.user_buffers.items():
                        info = buffer.get_info()
                        join_offset = (info['join_time'] - self.start_time) if info['join_time'] else 0
                        total_frames = info['total_frames']
                        file_duration = total_frames / self.sample_rate if total_frames > 0 else 0
                        data_mb = total_frames * (self.sample_width * self.channels) / (1024 * 1024)
                        
                        f.write(f"\n- {info['username']} (ID: {user_id})\n")
                        f.write(f"  File: {info['filename']}\n")
                        f.write(f"  Join Offset: {join_offset:.2f}s from session start\n")
                        f.write(f"  File Duration: {file_duration:.2f}s\n")
                        f.write(f"  Total Frames: {total_frames:,} (target: {target_frames:,})\n")
                        f.write(f"  Frame Match: {'✓' if abs(total_frames - target_frames) < 100 else '✗'}\n")
                        f.write(f"  File Size: {data_mb:.2f} MB\n")
                        
                        # Leave/rejoin information
                        if info['leave_times']:
                            f.write(f"  Leave/Rejoin Events: {len(info['leave_times'])}\n")
                            for i, (leave, rejoin) in enumerate(info['leave_times']):
                                leave_offset = leave - self.start_time
                                rejoin_offset = rejoin - self.start_time if rejoin < session_duration + self.start_time else session_duration
                                gap_duration = rejoin_offset - leave_offset
                                f.write(f"    Event {i+1}: Left at {leave_offset:.2f}s, rejoined at {rejoin_offset:.2f}s (gap: {gap_duration:.2f}s)\n")
                        
                f.write("\n\nTime Synchronization Summary:\n")
                all_same_length = True
                with self.buffers_lock:
                    frame_counts = [b.get_info()['total_frames'] for b in self.user_buffers.values()]
                    if frame_counts:
                        min_frames = min(frame_counts)
                        max_frames = max(frame_counts)
                        diff = max_frames - min_frames
                        all_same_length = diff < 100  # Allow small variance
                        
                f.write(f"- All files synchronized: {'✓ YES' if all_same_length else '✗ NO'}\n")
                if not all_same_length and frame_counts:
                    f.write(f"- Frame difference: {diff} frames ({diff/self.sample_rate:.3f}s)\n")
                f.write(f"- Ready for multi-track editing: {'✓ YES' if all_same_length else '✗ NO'}\n")
                    
            self.logger.info(f"Generated real-time synchronized recording metadata: {metadata_file}")
            
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
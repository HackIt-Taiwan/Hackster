import asyncio
import logging
import os
import subprocess
import threading
from queue import Queue
from typing import Optional, Dict, Any
from datetime import datetime

import discord

try:
    from discord.ext import voice_recv
    VOICE_RECV_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    VOICE_RECV_AVAILABLE = False
    voice_recv = None


# ===================== 🎧 MP3 轉換工具 =====================

def convert_pcm_to_mp3(pcm_path: str,
                       mp3_path: Optional[str] = None,
                       sample_rate: int = 48000,
                       channels: int = 2,
                       sample_format: str = "s16le") -> bool:
    """將 PCM 檔轉 MP3，使用 ffmpeg。"""
    if not mp3_path:
        mp3_path = os.path.splitext(pcm_path)[0] + ".mp3"

    command = [
        "ffmpeg",
        "-y",
        "-f", sample_format,
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "-i", pcm_path,
        mp3_path
    ]

    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[✔] 成功轉檔：{mp3_path}")
        # Clean up PCM file after successful conversion
        try:
            os.remove(pcm_path)
        except OSError:
            pass
        return True
    except subprocess.CalledProcessError:
        print(f"[✘] 轉檔失敗：{pcm_path}")
        return False
    

# ===================== 🎙️ 錄音器實作 =====================

class SynchronizedMultiUserRecorder(voice_recv.AudioSink if VOICE_RECV_AVAILABLE else object):
    """
    Synchronized multi-user recorder with consistent audio length and timing.
    Features:
    - All users have identical audio duration
    - Supports mid-meeting join/leave/rejoin
    - Fills silence when users are absent or not speaking
    - Maintains perfect timing synchronization
    """
    
    def __init__(self, output_dir: str, voice_channel):
        if VOICE_RECV_AVAILABLE:
            super().__init__()
        
        self.output_dir = output_dir
        self.voice_channel = voice_channel
        self.logger = logging.getLogger(__name__)
        
        # Audio configuration
        self.sample_rate = 48000
        self.channels = 2
        self.sample_width = 2  # 16-bit
        self.frame_size = self.channels * self.sample_width  # bytes per frame
        self.frames_per_second = self.sample_rate
        
        # Meeting timing
        self.meeting_start_time = None
        self.meeting_end_time = None
        
        # User management
        self.users = {}  # user_id -> UserAudioTracker
        self.user_lock = threading.Lock()
        
        # Monitoring thread
        self.monitor_active = True
        self.monitor_thread = threading.Thread(target=self._monitor_users, daemon=True)
        
        os.makedirs(output_dir, exist_ok=True)
        self.logger.info(f"🎙️ SynchronizedMultiUserRecorder initialized: {output_dir}")

    def wants_opus(self) -> bool:
        """Use raw PCM format to avoid Opus decoding complexity"""
        return False

    def start_recording(self):
        """Start the recording session"""
        import time
        self.meeting_start_time = time.time()
        self.monitor_thread.start()
        self.logger.info(f"🎬 Meeting recording started at {self.meeting_start_time}")

    def write(self, user: discord.User, data):
        """
        Process audio data for each user with timing synchronization
        Enhanced with robust error handling for Opus decoding issues
        """
        if self.meeting_start_time is None:
            return  # Not started yet
        
        try:
            # Validate audio data before processing
            if not hasattr(data, 'pcm') or data.pcm is None:
                self.logger.warning(f"⚠️ Invalid audio data from {user.display_name}, skipping...")
                return
            
            # Check if PCM data is empty or corrupted
            if len(data.pcm) == 0:
                self.logger.warning(f"⚠️ Empty PCM data from {user.display_name}, skipping...")
                return
            
            # Validate PCM data length is aligned to frame size
            expected_frame_size = self.channels * self.sample_width
            if len(data.pcm) % expected_frame_size != 0:
                self.logger.warning(f"⚠️ Misaligned PCM data from {user.display_name} "
                                  f"(length={len(data.pcm)}, frame_size={expected_frame_size}), attempting to fix...")
                # Truncate to nearest frame boundary
                aligned_length = (len(data.pcm) // expected_frame_size) * expected_frame_size
                if aligned_length == 0:
                    self.logger.warning(f"⚠️ PCM data too small to align for {user.display_name}, skipping...")
                    return
                data.pcm = data.pcm[:aligned_length]
            
            import time
            current_time = time.time()
            
            with self.user_lock:
                if user.id not in self.users:
                    # Create new user tracker
                    self.users[user.id] = UserAudioTracker(
                        user_id=user.id,
                        username=user.display_name,
                        output_dir=self.output_dir,
                        meeting_start_time=self.meeting_start_time,
                        sample_rate=self.sample_rate,
                        channels=self.channels,
                        sample_width=self.sample_width
                    )
                    self.logger.info(f"🎵 Started synchronized recording for: {user.display_name} ({user.id})")
                
                # Record audio data with timestamp
                self.users[user.id].add_audio_data(current_time, data.pcm)
                
        except Exception as e:
            # Handle any unexpected errors during audio processing
            self.logger.error(f"❌ Error processing audio from {user.display_name}: {e}")
            try:
                # Safely log debug info without triggering more exceptions
                has_pcm = hasattr(data, 'pcm')
                pcm_info = "None"
                if has_pcm:
                    try:
                        pcm_data = data.pcm
                        pcm_info = str(len(pcm_data)) if pcm_data is not None else "None"
                    except:
                        pcm_info = "Error accessing PCM"
                self.logger.debug(f"Audio data info: hasattr(data, 'pcm')={has_pcm}, pcm_length={pcm_info}")
            except:
                self.logger.debug("Unable to log audio data debug info due to errors")
            # Continue recording for other users even if one fails

    def _monitor_users(self):
        """
        Monitor voice channel for user join/leave events and fill silence gaps
        Enhanced with robust error handling for voice channel state changes
        """
        import time
        
        while self.monitor_active:
            try:
                current_time = time.time()
                
                # Safely get current voice channel members
                try:
                    if not self.voice_channel:
                        self.logger.warning("⚠️ Voice channel reference lost, stopping monitoring")
                        break
                    
                    current_members = {m.id for m in self.voice_channel.members if not m.bot}
                except Exception as channel_error:
                    self.logger.warning(f"⚠️ Error accessing voice channel members: {channel_error}")
                    time.sleep(1)
                    continue
    
                with self.user_lock:
                    # Track new joiners
                    for member_id in current_members:
                        if member_id in self.users:
                            try:
                                self.users[member_id].mark_present(current_time)
                            except Exception as presence_error:
                                self.logger.error(f"❌ Error marking user {member_id} present: {presence_error}")
                        # Note: New users are handled in write() method
                    
                    # Track leavers and fill silence
                    for user_id, tracker in list(self.users.items()):  # Use list() to avoid dict changes during iteration
                        try:
                            if user_id not in current_members:
                                tracker.mark_absent(current_time)
                            
                            # Fill silence gaps for all users
                            tracker.fill_silence_gaps(current_time)
                        except Exception as tracker_error:
                            self.logger.error(f"❌ Error processing tracker for user {user_id}: {tracker_error}")
                
                time.sleep(0.1)  # Check every 100ms for precise timing
                
            except Exception as e:
                self.logger.error(f"❌ Critical error in user monitoring: {e}")
                import traceback
                self.logger.debug(f"Full traceback: {traceback.format_exc()}")
                time.sleep(1)  # Wait longer on critical errors
        
        self.logger.info("🛑 User monitoring stopped")

    def stop_recording(self):
        """Stop recording and finalize all audio files"""
        import time
        self.meeting_end_time = time.time()
        self.monitor_active = False
        
        # Wait for monitor thread to finish
        if self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
        
        # Finalize all user recordings
        meeting_duration = self.meeting_end_time - self.meeting_start_time
        
        with self.user_lock:
            for user_id, tracker in self.users.items():
                tracker.finalize_recording(self.meeting_end_time, meeting_duration)
        
        self.logger.info(f"🎬 Meeting recording ended. Duration: {meeting_duration:.2f}s")
    
    def cleanup(self):
        """Clean up all resources"""
        self.logger.info("🧹 Cleaning up SynchronizedMultiUserRecorder...")
        
        if self.meeting_end_time is None:
            self.stop_recording()
        
        # Clean up all user trackers
        with self.user_lock:
            for tracker in self.users.values():
                tracker.cleanup()
        
        self.logger.info("✅ SynchronizedMultiUserRecorder cleanup completed")


class UserAudioTracker:
    """
    Tracks audio for a single user with precise timing and silence filling.
    Records all audio segments and silence gaps with timestamps, then assembles
    them in chronological order during finalization.
    """
    
    def __init__(self, user_id: int, username: str, output_dir: str, 
                 meeting_start_time: float, sample_rate: int, channels: int, sample_width: int):
        self.user_id = user_id
        self.username = username
        self.output_dir = output_dir
        self.meeting_start_time = meeting_start_time
        
        # Audio configuration
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.frame_size = channels * sample_width
        
        # Time-based audio segment tracking
        self.audio_segments = []  # [(start_time, end_time, 'audio', data), ...]
        self.is_present = True
        self.last_audio_time = meeting_start_time
        self.presence_history = [(meeting_start_time, True)]  # [(timestamp, is_present), ...]
        
        # Output file path (will be created during finalization)
        self.pcm_path = os.path.join(output_dir, f"user_{user_id}_{username}.pcm")
        
        # Thread safety
        self.lock = threading.Lock()
        
        self.logger = logging.getLogger(__name__)

    def add_audio_data(self, timestamp: float, pcm_data: bytes):
        """Add audio data with timestamp - stored for later chronological assembly"""
        try:
            with self.lock:
                # Validate PCM data
                if not pcm_data or len(pcm_data) == 0:
                    self.logger.warning(f"⚠️ Empty PCM data for {self.username}, skipping...")
                    return
                
                # Ensure data is properly aligned
                if len(pcm_data) % self.frame_size != 0:
                    self.logger.warning(f"⚠️ Misaligned PCM data for {self.username}, truncating...")
                    aligned_length = (len(pcm_data) // self.frame_size) * self.frame_size
                    if aligned_length == 0:
                        self.logger.warning(f"⚠️ PCM data too small for {self.username}, skipping...")
                        return
                    pcm_data = pcm_data[:aligned_length]
                
                # Ensure user is marked as present when speaking
                if not self.is_present:
                    self.mark_present(timestamp)
                
                # Calculate audio duration
                audio_frames = len(pcm_data) // self.frame_size
                audio_duration = audio_frames / self.sample_rate
                end_time = timestamp + audio_duration
                
                # Validate duration is reasonable (not too long or too short)
                if audio_duration < 0.001:  # Less than 1ms
                    self.logger.warning(f"⚠️ Audio segment too short for {self.username} ({audio_duration:.6f}s), skipping...")
                    return
                
                if audio_duration > 10.0:  # More than 10 seconds (unusual for individual packets)
                    self.logger.warning(f"⚠️ Audio segment suspiciously long for {self.username} ({audio_duration:.3f}s), but continuing...")
                
                # Store audio segment
                self.audio_segments.append((timestamp, end_time, 'audio', pcm_data))
                self.last_audio_time = timestamp
                
                self.logger.debug(f"🎵 Recorded {audio_duration:.3f}s audio for {self.username} at {timestamp:.3f}")
                
        except Exception as e:
            self.logger.error(f"❌ Error adding audio data for {self.username}: {e}")
            self.logger.debug(f"PCM data length: {len(pcm_data) if pcm_data else 'None'}, frame_size: {self.frame_size}")
            # Don't re-raise to avoid stopping the entire recording

    def mark_present(self, timestamp: float):
        """Mark user as present in voice channel"""
        if not self.is_present:
            self.is_present = True
            self.presence_history.append((timestamp, True))
            self.logger.debug(f"🟢 User {self.username} joined at {timestamp:.3f}")

    def mark_absent(self, timestamp: float):
        """Mark user as absent from voice channel"""
        if self.is_present:
            self.is_present = False
            self.presence_history.append((timestamp, False))
            self.logger.debug(f"🔴 User {self.username} left at {timestamp:.3f}")

    def fill_silence_gaps(self, current_time: float):
        """Record current time for final gap calculation - actual filling done in finalization"""
        self.last_audio_time = max(self.last_audio_time, current_time)
                
    def finalize_recording(self, meeting_end_time: float, total_duration: float):
        """Generate final audio file by assembling all segments chronologically"""
        try:
            with self.lock:
                self.logger.info(f"🎬 Finalizing recording for {self.username}...")
                
                # Check if we have any audio segments to process
                if not self.audio_segments:
                    self.logger.warning(f"⚠️ No audio segments found for {self.username}, skipping finalization")
                    return
                
                # Ensure output directory exists
                output_dir = os.path.dirname(self.pcm_path)
                if not os.path.exists(output_dir):
                    self.logger.warning(f"⚠️ Output directory missing for {self.username}, cannot finalize")
                    return
                
                # Create complete timeline with audio segments and silence gaps
                timeline = self._build_complete_timeline(meeting_end_time, total_duration)
                
                # Write timeline to PCM file
                with open(self.pcm_path, "wb") as audio_file:
                    for start_time, end_time, segment_type, data in timeline:
                        audio_file.write(data)
                
                self.logger.info(f"✅ Finalized PCM: {self.pcm_path} ({len(timeline)} segments)")
                
                # Convert to MP3
                mp3_path = os.path.splitext(self.pcm_path)[0] + ".mp3"
                if convert_pcm_to_mp3(self.pcm_path, mp3_path, self.sample_rate, self.channels):
                    self.logger.info(f"🎵 Converted to MP3: {mp3_path}")
                    # Clean up PCM file
                    try:
                        os.remove(self.pcm_path)
                    except:
                        pass
                else:
                    self.logger.warning(f"⚠️ MP3 conversion failed for {self.username}")
                
        except Exception as e:
            self.logger.error(f"❌ Error finalizing recording for {self.username}: {e}")
            import traceback
            self.logger.debug(f"Finalization error traceback: {traceback.format_exc()}")

    def _build_complete_timeline(self, meeting_end_time: float, total_duration: float):
        """Build complete timeline with audio segments and silence gaps in chronological order"""
        timeline = []
        current_time = self.meeting_start_time
        
        # **CRITICAL FIX**: Use total_duration as the authoritative end time, not meeting_end_time
        actual_end_time = self.meeting_start_time + total_duration
        
        self.logger.debug(f"📏 Building timeline: start={self.meeting_start_time:.3f}, "
                         f"requested_end={meeting_end_time:.3f}, "
                         f"actual_end={actual_end_time:.3f}, "
                         f"total_duration={total_duration:.3f}s")
        
        # Sort audio segments by start time and filter out segments beyond actual meeting end
        all_segments = sorted(self.audio_segments, key=lambda x: x[0])
        sorted_segments = []
        
        for seg_start, seg_end, seg_type, seg_data in all_segments:
            if seg_start >= actual_end_time:
                # Skip segments that start after meeting ends
                self.logger.debug(f"⏭️ Skipping audio segment beyond meeting end: {seg_start:.3f}s")
                continue
            
            if seg_end > actual_end_time:
                # Truncate segments that extend beyond meeting end
                self.logger.debug(f"✂️ Truncating audio segment from {seg_end:.3f}s to {actual_end_time:.3f}s")
                seg_end = actual_end_time
            
            sorted_segments.append((seg_start, seg_end, seg_type, seg_data))
        
        # Build presence intervals using actual meeting duration
        presence_intervals = self._get_presence_intervals(actual_end_time)
        
        segment_idx = 0
        for interval_start, interval_end, is_present in presence_intervals:
            interval_current = max(current_time, interval_start)
            
            # Ensure we don't process beyond actual meeting end
            interval_end = min(interval_end, actual_end_time)
            
            if not is_present:
                # User absent - fill entire interval with silence
                if interval_current < interval_end:
                    duration = interval_end - interval_current
                    silence_frames = int(duration * self.sample_rate)
                    silence_data = b'\\x00' * (silence_frames * self.frame_size)
                    timeline.append((interval_current, interval_end, 'silence', silence_data))
                    self.logger.debug(f"🔴 Absent period: {interval_current:.3f}s - {interval_end:.3f}s")
                current_time = interval_end
                continue
            
            # User present - fill gaps between audio segments with silence
            while segment_idx < len(sorted_segments) and sorted_segments[segment_idx][0] < interval_end:
                seg_start, seg_end, seg_type, seg_data = sorted_segments[segment_idx]
                
                # Skip segments outside current interval
                if seg_end <= interval_start:
                    segment_idx += 1
                    continue
                
                # Add silence gap before this segment
                if interval_current < seg_start:
                    gap_duration = seg_start - interval_current
                    if gap_duration > 0.2:  # Only fill gaps > 200ms
                        silence_frames = int(gap_duration * self.sample_rate)
                        silence_data = b'\\x00' * (silence_frames * self.frame_size)
                        timeline.append((interval_current, seg_start, 'silence', silence_data))
                        self.logger.debug(f"🔇 Silent gap: {interval_current:.3f}s - {seg_start:.3f}s ({gap_duration:.3f}s)")
                
                # Add audio segment
                actual_start = max(seg_start, interval_start)
                actual_end = min(seg_end, interval_end)
                if actual_start < actual_end:
                    timeline.append((actual_start, actual_end, 'audio', seg_data))
                
                interval_current = actual_end
                segment_idx += 1
            
            # Fill remaining silence in this interval
            if interval_current < interval_end:
                gap_duration = interval_end - interval_current
                if gap_duration > 0.2:
                    silence_frames = int(gap_duration * self.sample_rate)
                    silence_data = b'\\x00' * (silence_frames * self.frame_size)
                    timeline.append((interval_current, interval_end, 'silence', silence_data))
                    self.logger.debug(f"🔇 Final gap in interval: {interval_current:.3f}s - {interval_end:.3f}s")
            
            current_time = interval_end
        
        # **FINAL PADDING**: Ensure timeline covers exactly the total duration
        if current_time < actual_end_time:
            final_padding = actual_end_time - current_time
            silence_frames = int(final_padding * self.sample_rate)
            silence_data = b'\\x00' * (silence_frames * self.frame_size)
            timeline.append((current_time, actual_end_time, 'silence', silence_data))
            self.logger.debug(f"🔇 Final padding: {current_time:.3f}s - {actual_end_time:.3f}s ({final_padding:.3f}s)")
        
        # **VERIFICATION**: Calculate and verify final timeline duration
        total_timeline_duration = sum(end - start for start, end, _, _ in timeline)
        duration_diff = abs(total_timeline_duration - total_duration)
        
        if duration_diff > 0.1:  # More than 100ms difference is concerning
            self.logger.warning(f"⚠️ Timeline duration mismatch for {self.username}: "
                              f"expected {total_duration:.3f}s, got {total_timeline_duration:.3f}s "
                              f"(diff: {duration_diff:.3f}s)")
        else:
            self.logger.debug(f"✅ Timeline duration verified for {self.username}: {total_timeline_duration:.3f}s")
        
        return timeline

    def _get_presence_intervals(self, meeting_end_time: float):
        """Get presence intervals from presence history"""
        intervals = []
        
        if not self.presence_history:
            return [(self.meeting_start_time, meeting_end_time, True)]
        
        current_time = self.meeting_start_time
        current_present = self.presence_history[0][1]  # Initial state
        
        for timestamp, is_present in self.presence_history[1:]:
            if current_time < timestamp:
                intervals.append((current_time, timestamp, current_present))
            current_time = timestamp
            current_present = is_present
        
        # Add final interval
        if current_time < meeting_end_time:
            intervals.append((current_time, meeting_end_time, current_present))
        
        return intervals

    def cleanup(self):
        """Clean up resources"""
        with self.lock:
            self.logger.debug(f"🧹 Cleaning up UserAudioTracker for {self.username}")
            # No threads to clean up in new implementation


class MeetingRecorder:
    """
    Meeting recording manager that integrates SynchronizedMultiUserRecorder
    into the existing meeting system. Maintains all existing features:
    meeting rooms, multi-bot management, forum integration
    """

    def __init__(self, bot, config) -> None:
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.active_recordings: Dict[int, Dict[str, Any]] = {}

    async def record_meeting_audio(self, voice_channel_id: int) -> None:
        """
        Start synchronized meeting audio recording with consistent timing
        """
        try:
            guild = self.bot.guilds[0] if self.bot.guilds else None
            if not guild:
                self.logger.error("Bot not in any guild")
                return

            voice_channel = guild.get_channel(voice_channel_id)
            if not voice_channel:
                self.logger.error(f"Voice channel {voice_channel_id} not found")
                return

            # Create recording directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            recordings_dir = os.path.join(os.getcwd(), "recordings")
            recording_dir = os.path.join(
                recordings_dir,
                f"recording_{voice_channel_id}_{timestamp}_synchronized"
            )
            
            # Join voice channel using VoiceRecvClient
            voice_client = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
            
            # Create synchronized recorder
            recorder = SynchronizedMultiUserRecorder(recording_dir, voice_channel)
            
            # Start synchronized recording
            recorder.start_recording()
            voice_client.listen(recorder)
            
            # Store recording information
            self.active_recordings[voice_channel_id] = {
                'voice_client': voice_client,
                'recorder': recorder,
                'recording_dir': recording_dir,
                'start_time': datetime.now()
            }
            
            self.logger.info(f"🎙️ Started synchronized recording in channel: {voice_channel.name}")
            
            # Monitor until channel is empty or manually stopped
            await self._monitor_voice_channel(voice_channel, voice_client, recorder)
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start recording: {e}")
            await self._cleanup_recording(voice_channel_id)

    async def _monitor_voice_channel(self, voice_channel, voice_client, recorder):
        """
        Monitor voice channel and auto-stop when empty for extended period
        """
        empty_duration = 0
        max_empty_duration = 300  # 5 minutes of emptiness before stopping
        
        while voice_client.is_connected():
            try:
                # Check if there are human users in channel (exclude bots)
                human_members = [m for m in voice_channel.members if not m.bot]
                
                if not human_members:
                    empty_duration += 10
                    if empty_duration >= max_empty_duration:
                        self.logger.info("📭 Voice channel empty for 5 minutes, stopping recording")
                        break
                else:
                    empty_duration = 0
                    
                await asyncio.sleep(10)  # Check every 10 seconds
                        
            except Exception as e:
                self.logger.error(f"❌ Error monitoring voice channel: {e}")
                break
        
        # Stop recording
        await self._stop_and_cleanup(voice_client, recorder)

    async def _stop_and_cleanup(self, voice_client, recorder):
        """
        Stop synchronized recording and clean up resources
        """
        try:
            # Stop listening first
            if voice_client.is_connected():
                voice_client.stop_listening()
                
            # Stop synchronized recording and finalize audio files
            if recorder:
                recorder.stop_recording()  # This finalizes all audio with consistent length
                recorder.cleanup()
                
            # Disconnect from voice channel
            if voice_client.is_connected():
                await voice_client.disconnect()
                
            self.logger.info("🛑 Synchronized recording stopped and cleaned up")
                
        except Exception as e:
            self.logger.error(f"❌ Error during cleanup: {e}")

    async def stop_recording(self, voice_channel_id: int) -> bool:
        """
        Manually stop recording for specified channel
        """
        if voice_channel_id not in self.active_recordings:
            self.logger.warning(f"No active recording for channel {voice_channel_id}")
            return False
            
        recording_info = self.active_recordings[voice_channel_id]
        voice_client = recording_info['voice_client']
        recorder = recording_info['recorder']
        
        await self._stop_and_cleanup(voice_client, recorder)
        await self._cleanup_recording(voice_channel_id)
        
        return True

    async def _cleanup_recording(self, voice_channel_id: int):
        """
        Clean up recording records
        """
        if voice_channel_id in self.active_recordings:
            del self.active_recordings[voice_channel_id]

    def get_recording_status(self, voice_channel_id: int) -> dict:
        """
        Get current recording status
        """
        if voice_channel_id in self.active_recordings:
            recording_info = self.active_recordings[voice_channel_id]
            return {
                'is_recording': True,
                'start_time': recording_info['start_time'],
                'recording_dir': recording_info['recording_dir']
            }
        else:
            return {'is_recording': False}

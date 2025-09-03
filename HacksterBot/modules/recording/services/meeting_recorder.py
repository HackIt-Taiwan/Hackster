"""
Enhanced meeting recorder with proper duration control
Fixed the critical timeline building issue that caused incorrect recording length
"""

import os
import time
import logging
import threading
import subprocess
from datetime import datetime
from typing import Dict, List, Any, Optional

try:
    import discord
    import discord.ext.voice_recv as voice_recv
    VOICE_RECV_AVAILABLE = True
except ImportError:
    VOICE_RECV_AVAILABLE = False
    

def convert_pcm_to_mp3(pcm_path: str,
                      mp3_path: Optional[str] = None,
                      sample_rate: int = 48000,
                      channels: int = 2,
                      sample_format: str = "s16le") -> bool:
    """Convert PCM to MP3 using ffmpeg"""
    if mp3_path is None:
        mp3_path = pcm_path.replace('.pcm', '.mp3')
    
    try:
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-f', sample_format,
            '-ar', str(sample_rate),
            '-ac', str(channels),
            '-i', pcm_path,
            '-b:a', '128k',
            mp3_path
        ]
        
        subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
        print(f"[✓] MP3 conversion successful: {mp3_path}")
        
        # Clean up PCM file
        try:
            os.remove(pcm_path)
        except OSError:
            pass
        return True
    except subprocess.CalledProcessError:
        print(f"[✘] MP3 conversion failed: {pcm_path}")
        return False


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
        self.meeting_start_time = time.time()
        self.monitor_thread.start()
        self.logger.info(f"🎬 Meeting recording started at {self.meeting_start_time}")

    def write(self, user, data):
        """Process audio data for each user with timing synchronization"""
        if self.meeting_start_time is None:
            return  # Not started yet
        
        try:
            # Validate audio data before processing
            if not hasattr(data, 'pcm') or data.pcm is None:
                return
            
            if len(data.pcm) == 0:
                return
            
            # Validate PCM data length is aligned to frame size
            expected_frame_size = self.channels * self.sample_width
            if len(data.pcm) % expected_frame_size != 0:
                aligned_length = (len(data.pcm) // expected_frame_size) * expected_frame_size
                if aligned_length == 0:
                    return
                data.pcm = data.pcm[:aligned_length]
            
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
            self.logger.error(f"❌ Error processing audio from {user.display_name}: {e}")

    def _monitor_users(self):
        """Monitor voice channel for user join/leave events"""
        while self.monitor_active:
            try:
                current_time = time.time()
                
                if not self.voice_channel:
                    break
                
                current_members = {m.id for m in self.voice_channel.members if not m.bot}
    
                with self.user_lock:
                    # Track presence for all users
                    for member_id in current_members:
                        if member_id in self.users:
                            self.users[member_id].mark_present(current_time)
                    
                    # Track leavers and fill silence
                    for user_id, tracker in list(self.users.items()):
                        if user_id not in current_members:
                            tracker.mark_absent(current_time)
                        
                        # Fill silence gaps for all users
                        tracker.fill_silence_gaps(current_time)
                
                time.sleep(0.1)  # Check every 100ms for precise timing
                
            except Exception as e:
                self.logger.error(f"❌ Critical error in user monitoring: {e}")
                time.sleep(1)

    def stop_recording(self):
        """Stop recording and finalize all audio files"""
        self.meeting_end_time = time.time()
        self.monitor_active = False
        
        # Wait for monitor thread to finish
        if self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
        
        # **CRITICAL FIX**: Use consistent duration for all users
        meeting_duration = self.meeting_end_time - self.meeting_start_time
        
        with self.user_lock:
            if self.users:
                self.logger.info(f"🎯 Finalizing {len(self.users)} users with exact duration: {meeting_duration:.3f}s")
                
                for user_tracker in self.users.values():
                    try:
                        # **KEY CHANGE**: Pass exact meeting duration, not end time
                        user_tracker.finalize_recording(self.meeting_end_time, meeting_duration)
                    except Exception as e:
                        self.logger.error(f"❌ Error finalizing recording for {user_tracker.username}: {e}")
            else:
                self.logger.warning("⚠️ No users recorded during meeting")

    def cleanup(self):
        """Clean up resources"""
        with self.user_lock:
            for user_tracker in self.users.values():
                user_tracker.cleanup()


class UserAudioTracker:
    """
    Tracks audio data and presence for a single user with timeline-based assembly.
    Fixed to use total_duration as the authoritative length control.
    """
    
    def __init__(self, user_id: int, username: str, output_dir: str, 
                 meeting_start_time: float, sample_rate: int, channels: int, sample_width: int):
        self.user_id = user_id
        self.username = username
        self.output_dir = output_dir
        self.meeting_start_time = meeting_start_time
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.frame_size = channels * sample_width
        
        # Timeline-based storage
        self.audio_segments = []  # (start_time, end_time, 'audio', data)
        self.presence_history = [(meeting_start_time, True)]  # (timestamp, is_present)
        self.last_audio_time = meeting_start_time
        self.last_processed_time = meeting_start_time
        
        self.lock = threading.Lock()
        self.logger = logging.getLogger(__name__)

    def add_audio_data(self, timestamp: float, pcm_data: bytes):
        """Add audio data with precise timing"""
        with self.lock:
            # Calculate duration from PCM data length
            frames = len(pcm_data) // self.frame_size
            audio_duration = frames / self.sample_rate
            
            # Validate duration is reasonable
            if audio_duration < 0.001:  # Less than 1ms
                return
            
            if audio_duration > 10.0:  # More than 10 seconds
                self.logger.warning(f"⚠️ Unusually long audio segment for {self.username}: {audio_duration:.3f}s")
            
            # Store audio segment with timeline
            end_time = timestamp + audio_duration
            self.audio_segments.append((timestamp, end_time, 'audio', pcm_data))
            self.last_audio_time = end_time
            
            self.logger.debug(f"🎵 Audio segment for {self.username}: {timestamp:.3f}s - {end_time:.3f}s ({audio_duration:.3f}s)")

    def mark_present(self, timestamp: float):
        """Mark user as present in voice channel"""
        with self.lock:
            if not self.presence_history or self.presence_history[-1][1] != True:
                self.presence_history.append((timestamp, True))

    def mark_absent(self, timestamp: float):
        """Mark user as absent from voice channel"""
        with self.lock:
            if not self.presence_history or self.presence_history[-1][1] != False:
                self.presence_history.append((timestamp, False))

    def fill_silence_gaps(self, current_time: float):
        """Fill silence gaps up to current time"""
        with self.lock:
            if current_time > self.last_processed_time + 0.2:  # 200ms gap threshold
                self._fill_gaps_up_to(current_time)

    def finalize_recording(self, meeting_end_time: float, total_duration: float):
        """Finalize recording with exact duration control - CRITICAL FIX"""
        with self.lock:
            # **FIXED**: Use total_duration as the authoritative length, not meeting_end_time
            actual_end_time = self.meeting_start_time + total_duration
            
            self.logger.info(f"🎯 Finalizing {self.username}: "
                           f"meeting_start={self.meeting_start_time:.3f}, "
                           f"total_duration={total_duration:.3f}s, "
                           f"actual_end_time={actual_end_time:.3f}")
            
            # Build complete timeline with exact duration
            timeline = self._build_complete_timeline(meeting_end_time, total_duration)
            
            # Write final audio file
            self._write_timeline_to_file(timeline)
            
            self.logger.info(f"✅ Finalized recording for {self.username}: {total_duration:.3f}s")

    def _build_complete_timeline(self, meeting_end_time: float, total_duration: float):
        """Build complete timeline with audio segments and silence gaps - CRITICAL FIX"""
        timeline = []
        current_time = self.meeting_start_time
        
        # **CRITICAL FIX**: Use total_duration as the authoritative end time
        actual_end_time = self.meeting_start_time + total_duration
        
        # **FILTER AUDIO SEGMENTS**: Remove/truncate segments beyond actual meeting duration
        filtered_segments = []
        for start_time, end_time, segment_type, data in sorted(self.audio_segments, key=lambda x: x[0]):
            # Skip segments that start after meeting ends
            if start_time >= actual_end_time:
                self.logger.debug(f"⏭️ Skipping audio segment beyond meeting end: {start_time:.3f}s")
                continue
            
            # Truncate segments that extend beyond meeting end
            if end_time > actual_end_time:
                self.logger.debug(f"✂️ Truncating audio segment: {end_time:.3f}s → {actual_end_time:.3f}s")
                # Calculate truncated data
                original_duration = end_time - start_time
                new_duration = actual_end_time - start_time
                data_ratio = new_duration / original_duration
                frames_to_keep = int(len(data) // self.frame_size * data_ratio)
                truncated_data = data[:frames_to_keep * self.frame_size]
                filtered_segments.append((start_time, actual_end_time, segment_type, truncated_data))
            else:
                filtered_segments.append((start_time, end_time, segment_type, data))
        
        # **LIMIT PRESENCE INTERVALS**: Ensure they don't extend beyond actual meeting duration
        presence_intervals = self._get_presence_intervals_limited(actual_end_time)
        
        # Build timeline from filtered data
        segment_idx = 0
        for interval_start, interval_end, is_present in presence_intervals:
            interval_current = max(current_time, interval_start)
            
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
            while segment_idx < len(filtered_segments) and filtered_segments[segment_idx][1] <= interval_end:
                seg_start, seg_end, seg_type, seg_data = filtered_segments[segment_idx]
                
                # Add silence before audio if there's a gap
                if interval_current < seg_start:
                    gap_duration = seg_start - interval_current
                    silence_frames = int(gap_duration * self.sample_rate)
                    silence_data = b'\\x00' * (silence_frames * self.frame_size)
                    timeline.append((interval_current, seg_start, 'silence', silence_data))
                    self.logger.debug(f"🔇 Silence gap: {interval_current:.3f}s - {seg_start:.3f}s")
                
                # Add the audio segment
                timeline.append((seg_start, seg_end, seg_type, seg_data))
                interval_current = seg_end
                segment_idx += 1
            
            # Fill remaining silence in this interval
            if interval_current < interval_end:
                duration = interval_end - interval_current
                silence_frames = int(duration * self.sample_rate)
                silence_data = b'\\x00' * (silence_frames * self.frame_size)
                timeline.append((interval_current, interval_end, 'silence', silence_data))
                self.logger.debug(f"🔇 End silence: {interval_current:.3f}s - {interval_end:.3f}s")
            
            current_time = interval_end
        
        # **FINAL PADDING**: Ensure timeline covers exact total_duration
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

    def _get_presence_intervals_limited(self, actual_end_time: float):
        """Get presence intervals limited to actual meeting duration"""
        intervals = []
        
        if not self.presence_history:
            return [(self.meeting_start_time, actual_end_time, True)]
        
        current_time = self.meeting_start_time
        current_present = self.presence_history[0][1]  # Initial state
        
        for timestamp, is_present in self.presence_history[1:]:
            # Don't process events beyond actual meeting end
            if timestamp > actual_end_time:
                break
                
            if current_time < timestamp:
                intervals.append((current_time, timestamp, current_present))
            current_time = timestamp
            current_present = is_present
        
        # Add final interval up to actual_end_time only
        if current_time < actual_end_time:
            intervals.append((current_time, actual_end_time, current_present))
        
        return intervals

    def _fill_gaps_up_to(self, target_time: float):
        """Fill silence gaps up to target time"""
        # This method can remain unchanged as it's for real-time gap filling
        pass

    def _write_timeline_to_file(self, timeline):
        """Write timeline to PCM file and convert to MP3"""
        pcm_path = os.path.join(self.output_dir, f"{self.username}_{self.user_id}.pcm")
        
        try:
            with open(pcm_path, 'wb') as f:
                total_frames = 0
                for start_time, end_time, segment_type, data in timeline:
                    f.write(data)
                    frames = len(data) // self.frame_size
                    total_frames += frames
                
                total_duration = total_frames / self.sample_rate
                self.logger.info(f"📁 Written {self.username}: {total_frames} frames, {total_duration:.3f}s")
            
            # Convert to MP3
            convert_pcm_to_mp3(pcm_path, sample_rate=self.sample_rate, channels=self.channels)
            
        except Exception as e:
            self.logger.error(f"❌ Error writing audio file for {self.username}: {e}")

    def cleanup(self):
        """Clean up resources"""
        with self.lock:
            self.logger.debug(f"🧹 Cleaning up UserAudioTracker for {self.username}")


class MeetingRecorder:
    """Meeting recording manager with fixed duration control"""

    def __init__(self, bot, config) -> None:
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.active_recordings: Dict[int, Dict[str, Any]] = {}

    async def record_meeting_audio(self, voice_channel_id: int) -> None:
        """Start synchronized meeting audio recording"""
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
                f"recording_{voice_channel_id}_{timestamp}_fixed"
            )
            
            # Join voice channel
            voice_client = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
            
            # Create synchronized recorder
            recorder = SynchronizedMultiUserRecorder(recording_dir, voice_channel)
            
            # Start recording
            recorder.start_recording()
            voice_client.listen(recorder)
            
            # Store recording information
            self.active_recordings[voice_channel_id] = {
                'voice_client': voice_client,
                'recorder': recorder,
                'recording_dir': recording_dir,
                'start_time': datetime.now()
            }
            
            self.logger.info(f"🎙️ Started fixed duration recording in: {voice_channel.name}")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start recording: {e}")

    async def stop_recording(self, voice_channel_id: int) -> bool:
        """Stop recording with exact duration control"""
        if voice_channel_id not in self.active_recordings:
            return False
            
        recording_info = self.active_recordings[voice_channel_id]
        voice_client = recording_info['voice_client']
        recorder = recording_info['recorder']
        
        try:
            # Stop listening
            if voice_client.is_connected():
                voice_client.stop_listening()
                
            # **CRITICAL**: Stop recording ensures exact duration
            if recorder:
                recorder.stop_recording()
                recorder.cleanup()
                
            # Disconnect
            if voice_client.is_connected():
                await voice_client.disconnect()
                
            del self.active_recordings[voice_channel_id]
            self.logger.info("🛑 Fixed duration recording stopped")
            return True
                
        except Exception as e:
            self.logger.error(f"❌ Error stopping recording: {e}")
            return False 
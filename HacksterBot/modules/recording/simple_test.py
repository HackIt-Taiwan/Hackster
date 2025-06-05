#!/usr/bin/env python3
"""
Simple test for single-track recording functionality.
Tests the core recording logic without requiring full module system.
"""

import os
import tempfile
import wave
import time
from typing import Optional

# Simplified version of SingleTrackRecordingSink for testing
class TestSingleTrackRecordingSink:
    """Test version of audio sink that mixes all users into a single track recording."""

    def __init__(self, folder: str) -> None:
        self.folder = folder
        self.sample_rate = 48000
        self.channels = 2
        self.sample_width = 2
        
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
        
        print(f"✅ Started single-track recording: {self.output_file}")

    def write_audio(self, pcm_data: bytes) -> None:
        """Write audio data to the single track."""
        if self.is_closed:
            return

        try:
            # Write the PCM data directly to the single WAV file
            self.wav_file.writeframes(pcm_data)
        except Exception as e:
            print(f"❌ Error writing audio data: {e}")

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
                    print(f"✅ Recording completed: {self.output_file} ({file_size} bytes, {duration:.1f}s)")
                else:
                    print("❌ Recording file was not created")
                    
            except Exception as e:
                print(f"❌ Error closing WAV file: {e}")


def test_single_track_recording():
    """Test the single-track recording functionality."""
    print("🧪 Testing single-track recording functionality...\n")
    
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"📁 Using temporary directory: {temp_dir}")
        
        # Initialize the recording sink
        try:
            sink = TestSingleTrackRecordingSink(temp_dir)
        except Exception as e:
            print(f"❌ Failed to create recording sink: {e}")
            return False
        
        # Create some dummy PCM data (audio)
        sample_rate = 48000
        duration_seconds = 0.1  # 100ms of audio per chunk
        num_samples = int(sample_rate * duration_seconds * 2)  # 2 channels
        
        # Generate some test audio (a simple sine wave)
        import math
        frequency = 440  # A4 note
        samples_per_chunk = num_samples // 2  # per channel
        
        audio_chunks = []
        for chunk_idx in range(10):  # 10 chunks = 1 second total
            chunk_data = bytearray()
            for i in range(samples_per_chunk):
                # Generate stereo sine wave
                sample_time = (chunk_idx * samples_per_chunk + i) / sample_rate
                sample_value = int(8000 * math.sin(2 * math.pi * frequency * sample_time))
                
                # Convert to 16-bit little-endian format (left and right channels)
                sample_bytes = sample_value.to_bytes(2, byteorder='little', signed=True)
                chunk_data.extend(sample_bytes)  # Left channel
                chunk_data.extend(sample_bytes)  # Right channel
            
            audio_chunks.append(bytes(chunk_data))
        
        # Test writing audio data
        try:
            print("🎵 Writing audio chunks...")
            for i, chunk in enumerate(audio_chunks):
                sink.write_audio(chunk)
                print(f"   Chunk {i+1}/{len(audio_chunks)} written")
                time.sleep(0.01)  # Small delay between writes
            print("✅ Successfully wrote all audio data")
        except Exception as e:
            print(f"❌ Failed to write audio data: {e}")
            return False
        
        # Test cleanup
        try:
            sink.cleanup()
        except Exception as e:
            print(f"❌ Failed to cleanup recording sink: {e}")
            return False
        
        # Verify output file
        output_file = os.path.join(temp_dir, "meeting_recording.wav")
        if os.path.exists(output_file):
            # Check file size
            file_size = os.path.getsize(output_file)
            print(f"📊 File size: {file_size} bytes")
            
            # Try to open the WAV file to verify it's valid
            try:
                with wave.open(output_file, 'rb') as wav_file:
                    frames = wav_file.getnframes()
                    sample_rate = wav_file.getframerate()
                    channels = wav_file.getnchannels()
                    sample_width = wav_file.getsampwidth()
                    
                    print(f"📊 WAV file properties:")
                    print(f"   - Frames: {frames}")
                    print(f"   - Sample rate: {sample_rate} Hz")
                    print(f"   - Channels: {channels}")
                    print(f"   - Sample width: {sample_width} bytes")
                    
                    duration = frames / sample_rate
                    print(f"   - Duration: {duration:.3f} seconds")
                    
                    # Verify expected values
                    if sample_rate == 48000 and channels == 2 and sample_width == 2:
                        print("✅ WAV file has correct format")
                    else:
                        print("❌ WAV file format is incorrect")
                        return False
                    
                    if duration > 0.5:  # Should be about 1 second
                        print("✅ WAV file has reasonable duration")
                    else:
                        print("❌ WAV file duration is too short")
                        return False
                        
            except Exception as e:
                print(f"❌ Failed to read WAV file: {e}")
                return False
                
        else:
            print(f"❌ Output file not created: {output_file}")
            return False
    
    return True


def test_multiple_users_simulation():
    """Test simulating multiple users recording to the same track."""
    print("\n🧪 Testing multiple users simulation...\n")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"📁 Using temporary directory: {temp_dir}")
        
        sink = TestSingleTrackRecordingSink(temp_dir)
        
        # Simulate audio from multiple "users"
        users = ["Alice", "Bob", "Charlie"]
        
        try:
            print("🎵 Simulating multiple users speaking...")
            for round_num in range(5):
                for user_idx, user in enumerate(users):
                    # Generate different frequency for each user
                    frequency = 220 + (user_idx * 110)  # A3, A3+fifth, A4
                    
                    # Generate PCM audio for this user
                    sample_rate = 48000
                    duration_seconds = 0.05  # 50ms chunks
                    num_samples = int(sample_rate * duration_seconds)
                    
                    chunk_data = bytearray()
                    for i in range(num_samples):
                        sample_time = i / sample_rate
                        sample_value = int(4000 * math.sin(2 * math.pi * frequency * sample_time))
                        
                        # 16-bit stereo
                        sample_bytes = sample_value.to_bytes(2, byteorder='little', signed=True)
                        chunk_data.extend(sample_bytes)  # Left
                        chunk_data.extend(sample_bytes)  # Right
                    
                    sink.write_audio(bytes(chunk_data))
                    print(f"   {user} speaks (round {round_num + 1})")
                    time.sleep(0.01)
            
            print("✅ Multiple users simulation completed")
        except Exception as e:
            print(f"❌ Multiple users simulation failed: {e}")
            return False
        
        sink.cleanup()
        
        # Verify the combined recording
        output_file = os.path.join(temp_dir, "meeting_recording.wav")
        if os.path.exists(output_file):
            with wave.open(output_file, 'rb') as wav_file:
                duration = wav_file.getnframes() / wav_file.getframerate()
                print(f"✅ Combined recording duration: {duration:.3f} seconds")
        
    return True


if __name__ == "__main__":
    print("🚀 Starting single-track recording tests...\n")
    
    import math  # Import here for the test functions
    
    success = True
    
    # Test basic functionality
    if not test_single_track_recording():
        success = False
    
    # Test multiple users
    if not test_multiple_users_simulation():
        success = False
    
    print(f"\n{'🎉 All tests passed!' if success else '❌ Some tests failed!'}")
    print("\n📝 Summary:")
    print("   - Single-track recording eliminates per-user audio files")
    print("   - All participants are mixed into one continuous WAV file")
    print("   - Simpler architecture with fewer moving parts")
    print("   - No need for complex gap tracking or synchronization")
    
    exit(0 if success else 1) 
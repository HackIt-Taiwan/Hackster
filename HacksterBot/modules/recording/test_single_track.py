#!/usr/bin/env python3
"""
Test script for single-track recording functionality.

This script tests the core functionality of the SingleTrackRecordingSink
without requiring a full Discord bot setup.
"""

import os
import tempfile
import wave
import time
from unittest.mock import Mock

# Test the SingleTrackRecordingSink class
def test_single_track_recording():
    """Test basic functionality of SingleTrackRecordingSink."""
    print("Testing SingleTrackRecordingSink...")
    
    # Import the class we want to test
    try:
        import sys
        import os
        sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        from HacksterBot.modules.recording.services.meeting_recorder import SingleTrackRecordingSink
        print("✅ Successfully imported SingleTrackRecordingSink")
    except ImportError as e:
        print(f"❌ Failed to import SingleTrackRecordingSink: {e}")
        return False
    
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"📁 Using temporary directory: {temp_dir}")
        
        # Initialize the recording sink
        try:
            sink = SingleTrackRecordingSink(temp_dir)
            print("✅ Successfully created SingleTrackRecordingSink")
        except Exception as e:
            print(f"❌ Failed to create SingleTrackRecordingSink: {e}")
            return False
        
        # Mock voice data
        mock_user = Mock()
        mock_user.id = 12345
        mock_user.display_name = "TestUser"
        
        mock_voice_data = Mock()
        # Create some dummy PCM data (silence)
        sample_rate = 48000
        duration_seconds = 0.1  # 100ms of audio
        num_samples = int(sample_rate * duration_seconds * 2)  # 2 channels
        dummy_pcm = b'\x00' * (num_samples * 2)  # 16-bit samples
        mock_voice_data.pcm = dummy_pcm
        
        # Test writing audio data
        try:
            for i in range(5):  # Write 5 chunks of audio
                sink.write(mock_user, mock_voice_data)
                time.sleep(0.01)  # Small delay between writes
            print("✅ Successfully wrote audio data")
        except Exception as e:
            print(f"❌ Failed to write audio data: {e}")
            return False
        
        # Test cleanup
        try:
            sink.cleanup()
            print("✅ Successfully cleaned up recording sink")
        except Exception as e:
            print(f"❌ Failed to cleanup recording sink: {e}")
            return False
        
        # Check if output file was created
        output_file = os.path.join(temp_dir, "meeting_recording.wav")
        if os.path.exists(output_file):
            print(f"✅ Output file created: {output_file}")
            
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
                    
                print("✅ WAV file is valid")
                
            except Exception as e:
                print(f"❌ Failed to read WAV file: {e}")
                return False
                
        else:
            print(f"❌ Output file not created: {output_file}")
            return False
    
    print("🎉 All tests passed!")
    return True


def test_meeting_recorder_initialization():
    """Test MeetingRecorder initialization."""
    print("\nTesting MeetingRecorder initialization...")
    
    try:
        from HacksterBot.modules.recording.services.meeting_recorder import MeetingRecorder
        print("✅ Successfully imported MeetingRecorder")
    except ImportError as e:
        print(f"❌ Failed to import MeetingRecorder: {e}")
        return False
    
    # Mock bot and config
    mock_bot = Mock()
    mock_bot.guilds = []
    
    mock_config = Mock()
    mock_config.recording = Mock()
    
    try:
        recorder = MeetingRecorder(mock_bot, mock_config)
        print("✅ Successfully created MeetingRecorder")
        
        # Check initial state
        assert recorder.audio_sink is None
        assert recorder.recording_task is None
        print("✅ MeetingRecorder initial state is correct")
        
    except Exception as e:
        print(f"❌ Failed to create MeetingRecorder: {e}")
        return False
    
    print("✅ MeetingRecorder initialization test passed!")
    return True


if __name__ == "__main__":
    print("🚀 Starting single-track recording tests...\n")
    
    success = True
    
    # Test SingleTrackRecordingSink
    if not test_single_track_recording():
        success = False
    
    # Test MeetingRecorder
    if not test_meeting_recorder_initialization():
        success = False
    
    print(f"\n{'🎉 All tests passed!' if success else '❌ Some tests failed!'}")
    exit(0 if success else 1) 
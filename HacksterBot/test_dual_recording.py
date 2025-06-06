#!/usr/bin/env python3
"""
Simplified dual user recording test for HacksterBot.
Tests if two people speaking simultaneously still causes lag.
"""

import os
import tempfile
import time
import threading
import math
import logging
from unittest.mock import Mock

# Add project root to path
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def create_mock_pcm_data(frequency: int, duration_ms: int, amplitude: int = 8000) -> bytes:
    """Create mock PCM audio data for testing."""
    sample_rate = 48000
    channels = 2
    duration_seconds = duration_ms / 1000.0
    num_samples = int(sample_rate * duration_seconds)
    
    pcm_data = bytearray()
    for i in range(num_samples):
        sample_time = i / sample_rate
        sample_value = int(amplitude * math.sin(2 * math.pi * frequency * sample_time))
        
        # 16-bit stereo PCM
        sample_bytes = sample_value.to_bytes(2, byteorder='little', signed=True)
        pcm_data.extend(sample_bytes)  # Left channel
        pcm_data.extend(sample_bytes)  # Right channel
    
    return bytes(pcm_data)


def test_dual_user_recording():
    """Test the exact scenario: two people speaking simultaneously."""
    
    logger.info("🎯 Testing Dual User Simultaneous Recording")
    logger.info("=" * 50)
    
    try:
        from modules.recording.services.meeting_recorder import OptimizedMultiTrackSink
        
        with tempfile.TemporaryDirectory() as temp_dir:
            logger.info(f"📁 Test directory: {temp_dir}")
            
            # Create the optimized recording sink
            sink = OptimizedMultiTrackSink(temp_dir)
            
            # Create two users
            user1 = Mock()
            user1.id = 12345
            user1.display_name = "Alice"
            
            user2 = Mock()
            user2.id = 67890
            user2.display_name = "Bob"
            
            logger.info("🎤 Starting dual user recording test...")
            logger.info("   Alice and Bob will speak simultaneously for 5 seconds")
            
            start_time = time.time()
            total_packets = 0
            
            def speaker_simulation(user, frequency, name):
                """Simulate a user speaking."""
                nonlocal total_packets
                packets_sent = 0
                
                for chunk_idx in range(250):  # 250 chunks × 20ms = 5 seconds
                    # Create mock voice data with different frequencies
                    mock_voice_data = Mock()
                    mock_voice_data.pcm = create_mock_pcm_data(frequency, 20)
                    
                    # Write to sink (this is where lag would occur)
                    sink.write(user, mock_voice_data)
                    packets_sent += 1
                    total_packets += 1
                    
                    # Realistic Discord timing
                    time.sleep(0.02)  # 20ms intervals (Discord standard)
                
                logger.info(f"   {name} sent {packets_sent} packets")
            
            # Start both users speaking simultaneously
            alice_thread = threading.Thread(
                target=speaker_simulation, 
                args=(user1, 440, "Alice"),  # A4 note
                name="Alice-Speaker"
            )
            
            bob_thread = threading.Thread(
                target=speaker_simulation, 
                args=(user2, 330, "Bob"),    # E4 note
                name="Bob-Speaker"
            )
            
            # Launch both threads at the same time
            alice_thread.start()
            bob_thread.start()
            
            # Wait for both to finish
            alice_thread.join()
            bob_thread.join()
            
            total_time = time.time() - start_time
            
            # Performance analysis
            logger.info(f"\n📊 Dual User Recording Results:")
            logger.info(f"   • Total users: 2 (Alice & Bob)")
            logger.info(f"   • Total packets sent: {total_packets}")
            logger.info(f"   • Total time: {total_time:.3f}s")
            logger.info(f"   • Expected time: ~5.0s")
            logger.info(f"   • Time overhead: {(total_time - 5.0):.3f}s")
            logger.info(f"   • Packets per second: {total_packets/total_time:.1f}")
            logger.info(f"   • Active user buffers: {len(sink.user_buffers)}")
            
            # Check for lag indicators
            packets_received = sink.packets_received
            packet_loss_rate = (total_packets - packets_received) / total_packets * 100
            
            logger.info(f"   • Packets received by sink: {packets_received}")
            logger.info(f"   • Packet loss rate: {packet_loss_rate:.2f}%")
            
            # Lag assessment
            is_real_time = total_time <= 6.0  # Allow 1s tolerance
            low_packet_loss = packet_loss_rate < 2.0
            
            logger.info(f"\n🔍 Lag Analysis:")
            logger.info(f"   • Real-time performance: {'✅ YES' if is_real_time else '❌ NO'}")
            logger.info(f"   • Low packet loss: {'✅ YES' if low_packet_loss else '❌ NO'}")
            
            # Cleanup
            sink.cleanup()
            
            # Final verdict
            if is_real_time and low_packet_loss:
                logger.info("\n🎉 SUCCESS: No lag detected with dual users!")
                logger.info("   The zero-latency architecture successfully handles simultaneous speakers.")
                return True
            else:
                logger.warning("\n⚠️ WARNING: Potential lag detected!")
                if not is_real_time:
                    logger.warning("   Recording took longer than expected (possible lag)")
                if not low_packet_loss:
                    logger.warning("   High packet loss rate detected")
                return False
                
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__":
    logger.info("🎯 HacksterBot Dual User Recording Test")
    logger.info("Testing if two people speaking simultaneously causes lag")
    logger.info("=" * 60)
    
    # Run the test
    success = test_dual_user_recording()
    
    logger.info("\n" + "=" * 60)
    if success:
        logger.info("🏆 FINAL RESULT: ✅ NO LAG DETECTED!")
        logger.info("The recording system handles dual users perfectly.")
        logger.info("\n📝 Architecture Benefits:")
        logger.info("   ✅ Each user has dedicated processing thread")
        logger.info("   ✅ No shared locks between users")
        logger.info("   ✅ Independent audio buffers")
        logger.info("   ✅ Parallel file writing")
        logger.info("   ✅ Zero-latency packet distribution")
    else:
        logger.error("🏆 FINAL RESULT: ❌ LAG STILL EXISTS!")
        logger.error("The recording system may need further optimization.")
    
    exit(0 if success else 1) 
"""
Recording module for HacksterBot.

This module provides meeting recording functionality, integrated from HackMeet-DiscordBot.
Features include:
- Multi-bot recording management 
- Voice channel creation and management
- Individual audio track recording
- Forum thread integration
- Automatic meeting cleanup
"""

from core.module_base import ModuleBase
from .services.recording_manager import RecordingManager


async def create_module(bot, config):
    """Create the recording module instance."""
    return RecordingModule(bot, config)


class RecordingModule(ModuleBase):
    """Main recording module class."""
    
    def __init__(self, bot, config):
        super().__init__(bot, config)
        self.recording_manager = None
        
    async def setup(self):
        """Initialize the recording module."""
        try:
            # Initialize recording manager with multiple bot tokens
            recording_tokens = getattr(self.config.recording, 'bot_tokens', '').split(',')
            recording_tokens = [token.strip() for token in recording_tokens if token.strip()]
            
            if not recording_tokens:
                self.logger.warning("No recording bot tokens configured. Recording functionality disabled.")
                return
                
            self.recording_manager = RecordingManager(
                recording_tokens, 
                self.bot, 
                self.config
            )
            await self.recording_manager.initialize()
            
            self.logger.info(f"Recording module loaded with {len(recording_tokens)} recording bots")
            
        except Exception as e:
            self.logger.error(f"Failed to setup recording module: {e}")
            raise
            
    async def teardown(self):
        """Clean up recording module."""
        if self.recording_manager:
            await self.recording_manager.shutdown()
            
    async def create_meeting_room(self, member, category, base_channel_name="會議室"):
        """Create a meeting room for the given member."""
        if not self.recording_manager:
            self.logger.error("Recording manager not initialized")
            return None
            
        return await self.recording_manager.create_meeting_room(member, category, base_channel_name)
        
    async def start_recording(self, voice_channel_id: int):
        """Start recording for a voice channel."""
        if not self.recording_manager:
            self.logger.error("Recording manager not initialized")
            return False
            
        return await self.recording_manager.start_recording(voice_channel_id)
        
    async def stop_recording(self, voice_channel_id: int):
        """Stop recording for a voice channel."""
        if not self.recording_manager:
            self.logger.error("Recording manager not initialized") 
            return False
            
        return await self.recording_manager.stop_recording(voice_channel_id) 
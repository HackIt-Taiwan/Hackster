"""
AI module for HacksterBot.
Handles AI-powered chat responses and message classification.
"""
import logging
from typing import TYPE_CHECKING

import discord
from core.bot import ModuleBase
from .handler import AIHandler

if TYPE_CHECKING:
    from core.bot import HacksterBot
    from core.config import Config

logger = logging.getLogger(__name__)


class Module(ModuleBase):
    """AI module for handling AI-powered responses."""
    
    def __init__(self, bot: 'HacksterBot', config: 'Config'):
        """
        Initialize the AI module.
        
        Args:
            bot: Bot instance
            config: Configuration object
        """
        super().__init__(bot, config)
        self.ai_handler = None
    
    async def setup(self) -> None:
        """Setup the AI module."""
        await super().setup()
        
        # Initialize AI handler
        self.ai_handler = AIHandler(self.bot, self.config)
        await self.ai_handler.initialize()
        
        # Register event handlers
        self.bot.add_listener(self._on_message, 'on_message')
        self.bot.add_listener(self._on_message_edit, 'on_message_edit')
        
        self.logger.info("AI module setup complete")
    
    async def teardown(self) -> None:
        """Teardown the AI module."""
        if self.ai_handler:
            await self.ai_handler.close()
        
        await super().teardown()
        self.logger.info("AI module teardown complete")
    
    async def _on_message(self, message):
        """Handle incoming messages for AI processing."""
        # Skip bot messages
        if message.author.bot:
            return
        
        # Skip DM messages (private messages)
        if isinstance(message.channel, discord.DMChannel):
            return
        
        # Check if bot is mentioned
        bot_mentioned = self.bot.user in message.mentions
        
        # Handle AI responses for mentions only (no DM responses)
        if bot_mentioned:
            await self.ai_handler.handle_message(message)
    
    async def _on_message_edit(self, before, after):
        """Handle message edits."""
        # Only process if the content actually changed
        if before.content != after.content:
            await self._on_message(after)
    
    async def get_agent(self, provider: str, model: str):
        """
        Get an AI agent for other modules to use.
        
        Args:
            provider: AI provider (e.g., 'openai', 'gemini', 'anthropic')
            model: Model name
            
        Returns:
            AI agent instance
        """
        if not self.ai_handler:
            self.logger.error("AI handler not initialized, cannot provide agent")
            return None
        
        try:
            from .services.ai_select import create_agent
            agent = await create_agent(self.config, provider, model)
            self.logger.info(f"Created agent for {provider}/{model}")
            return agent
        except Exception as e:
            self.logger.error(f"Failed to create agent for {provider}/{model}: {e}")
            return None


# Alternative setup function (for backwards compatibility)
async def setup(bot: 'HacksterBot', config: 'Config') -> None:
    """
    Setup function for the AI module.
    
    Args:
        bot: Bot instance
        config: Configuration object
    """
    module = Module(bot, config)
    await module.setup()
    bot.modules['ai'] = module 
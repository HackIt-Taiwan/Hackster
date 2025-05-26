"""
AI response handler for the HacksterBot AI module.
"""
import asyncio
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional, TYPE_CHECKING

import discord

from config.settings import MESSAGE_TYPES, AI_MAX_RETRIES, AI_RETRY_DELAY, RATE_LIMIT_WINDOW, RATE_LIMIT_MAX_MESSAGES
from .services.ai_select import create_primary_agent, create_general_ai_agent
from .classifiers.message_classifier import MessageClassifier
from .services.search import SearchService

if TYPE_CHECKING:
    from core.bot import HacksterBot
    from core.config import Config

logger = logging.getLogger(__name__)


class AIHandler:
    """
    Handles AI-powered message processing and responses.
    """
    
    def __init__(self, bot: 'HacksterBot', config: 'Config'):
        """
        Initialize the AI handler.
        
        Args:
            bot: Bot instance
            config: Configuration object
        """
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # AI agents
        self._crazy_agent = None
        self._general_agent = None
        self._classifier = None
        self._search = None
        
        # Rate limiting
        self.user_message_times = defaultdict(list)
        
        self.logger.info("AI handler initialized")
    
    async def initialize(self) -> None:
        """Initialize AI services."""
        self.logger.info("Initializing AI services...")
        
        try:
            # Initialize services asynchronously
            await self._ensure_services()
            self.logger.info("AI services initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize AI services: {e}")
            raise
    
    async def close(self) -> None:
        """Close AI handler and cleanup resources."""
        self.logger.info("Closing AI handler...")
        
        # Cleanup if needed
        if self._search:
            # Close search service if it has cleanup methods
            pass
        
        self.logger.info("AI handler closed")
    
    async def _ensure_services(self) -> None:
        """Ensure all required AI services are initialized."""
        if self._crazy_agent is None:
            self._crazy_agent = await create_primary_agent(self.config)
        if self._general_agent is None:
            self._general_agent = await create_general_ai_agent(self.config)
        if self._classifier is None:
            self._classifier = MessageClassifier(self.config)
        if self._search is None:
            self._search = SearchService(self.config)
    
    def _check_rate_limit(self, user_id: int) -> bool:
        """
        Check if user is rate limited.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            True if user is rate limited
        """
        now = datetime.now()
        cutoff = now - timedelta(seconds=RATE_LIMIT_WINDOW)
        
        # Remove old timestamps
        self.user_message_times[user_id] = [
            timestamp for timestamp in self.user_message_times[user_id] 
            if timestamp > cutoff
        ]
        
        # Check if over limit
        if len(self.user_message_times[user_id]) >= RATE_LIMIT_MAX_MESSAGES:
            return True
        
        # Add current timestamp
        self.user_message_times[user_id].append(now)
        return False
    
    def _clean_response(self, response: str) -> str:
        """
        Clean up the AI response for formatting.
        
        Args:
            response: Raw AI response
            
        Returns:
            Cleaned response
        """
        # Remove any special command patterns if needed
        response = response.strip()
        
        # Remove any markdown artifacts that might cause issues
        response = re.sub(r'\*\*\*+', '**', response)  # Fix excessive bold
        response = re.sub(r'___+', '__', response)     # Fix excessive underline
        
        return response
    
    async def handle_message(self, message: discord.Message) -> None:
        """
        Handle an incoming message for AI processing.
        
        Args:
            message: Discord message to process
        """
        try:
            # Check rate limit
            if self._check_rate_limit(message.author.id):
                self.logger.warning(f"Rate limit exceeded for user {message.author.id}")
                await message.channel.send(
                    f"{message.author.mention} 您發送訊息太頻繁了，請稍等一下再試。",
                    delete_after=10
                )
                return
            
            # Get message content, removing bot mention
            content = message.content
            if self.bot.user in message.mentions:
                content = content.replace(f'<@{self.bot.user.id}>', '').strip()
                content = content.replace(f'<@!{self.bot.user.id}>', '').strip()
            
            if not content:
                await message.channel.send("您想說什麼呢？", delete_after=10)
                return
            
            # Start typing indicator
            async with message.channel.typing():
                # Get AI response
                response_chunks = []
                async for chunk in self.get_streaming_response(
                    content,
                    user_id=message.author.id,
                    channel_id=message.channel.id,
                    guild_id=getattr(message.guild, 'id', None)
                ):
                    response_chunks.append(chunk)
                
                response = ''.join(response_chunks)
                
                if response:
                    # Split long messages
                    await self._send_response(message.channel, response)
                else:
                    await message.channel.send("抱歉，我無法處理您的請求。")
                    
        except Exception as e:
            self.logger.error(f"Error handling message: {e}")
            await message.channel.send("處理訊息時發生錯誤，請稍後再試。")
    
    async def _send_response(self, channel: discord.TextChannel, response: str) -> None:
        """
        Send AI response to channel, splitting if necessary.
        
        Args:
            channel: Discord channel to send to
            response: Response text to send
        """
        # Discord message limit is 2000 characters
        max_length = 1900  # Leave some buffer
        
        if len(response) <= max_length:
            await channel.send(response)
        else:
            # Split the message at natural break points
            parts = self._split_message(response, max_length)
            for part in parts:
                await channel.send(part)
                await asyncio.sleep(0.5)  # Small delay between messages
    
    def _split_message(self, text: str, max_length: int) -> list[str]:
        """
        Split a long message into smaller parts.
        
        Args:
            text: Text to split
            max_length: Maximum length per part
            
        Returns:
            List of message parts
        """
        if len(text) <= max_length:
            return [text]
        
        parts = []
        current = ""
        
        # Split by sentences first
        sentences = text.split('。')
        
        for sentence in sentences:
            if sentence:
                sentence = sentence + '。'
                if len(current + sentence) <= max_length:
                    current += sentence
                else:
                    if current:
                        parts.append(current.strip())
                        current = sentence
                    else:
                        # Sentence is too long, split by words
                        words = sentence.split()
                        for word in words:
                            if len(current + word + ' ') <= max_length:
                                current += word + ' '
                            else:
                                if current:
                                    parts.append(current.strip())
                                    current = word + ' '
                                else:
                                    # Word is too long, force split
                                    parts.append(word[:max_length])
                                    current = word[max_length:] + ' '
        
        if current:
            parts.append(current.strip())
        
        return parts
    
    async def get_streaming_response(
        self, 
        message: str, 
        context: Optional[str] = None,
        user_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        guild_id: Optional[int] = None
    ) -> AsyncGenerator[str, None]:
        """
        Get a streaming response from the AI.
        
        Args:
            message: User message
            context: Optional context
            user_id: Discord user ID
            channel_id: Discord channel ID
            guild_id: Discord guild ID
            
        Yields:
            Response chunks
        """
        await self._ensure_services()
        
        try:
            # Classify the message
            message_type = await self._classifier.classify_message(message)
            
            # Select appropriate agent
            if message_type == MESSAGE_TYPES['SEARCH']:
                # Use search service for search queries
                search_results = await self._search.search(message)
                
                # Use general agent with search context
                agent = self._general_agent
                message_with_context = f"根據以下搜尋結果回答問題：\n\n{search_results}\n\n問題：{message}"
                self.logger.info("Using general agent with search results")
            elif message_type == MESSAGE_TYPES['GENERAL']:
                agent = self._general_agent
                message_with_context = message
                self.logger.info("Using general agent")
            else:
                # Default to crazy agent for chat
                agent = self._crazy_agent
                message_with_context = message
                self.logger.info("Using crazy agent")
            
            # Get response with retry logic
            for attempt in range(AI_MAX_RETRIES):
                try:
                    async with agent.run_stream(message_with_context) as result:
                        async for chunk in result.stream_text(delta=True):
                            cleaned_chunk = self._clean_response(chunk)
                            if cleaned_chunk:
                                yield cleaned_chunk
                    return
                    
                except Exception as e:
                    if attempt == AI_MAX_RETRIES - 1:
                        self.logger.error(f"AI response failed after {AI_MAX_RETRIES} attempts: {e}")
                        yield "抱歉，AI 服務暫時無法回應，請稍後再試。"
                        return
                    
                    self.logger.warning(f"AI response attempt {attempt + 1} failed: {e}")
                    await asyncio.sleep(AI_RETRY_DELAY)
                    
        except Exception as e:
            self.logger.error(f"Error in get_streaming_response: {e}")
            yield "抱歉，處理您的請求時發生錯誤。" 
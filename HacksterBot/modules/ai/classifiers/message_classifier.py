"""
Message classifier service for HacksterBot.
"""
import logging
from typing import Optional

from config.settings import MESSAGE_TYPES
from ..services.ai_select import create_message_classifier

logger = logging.getLogger(__name__)


class MessageClassifier:
    """
    Classifies user messages into different types for appropriate handling.
    """
    
    def __init__(self, config):
        """
        Initialize the message classifier.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self._agent = None
        self.logger = logging.getLogger(__name__)

    async def _ensure_agent(self):
        """Ensure the classifier agent is initialized."""
        if self._agent is None:
            self._agent = await create_message_classifier(self.config)

    async def classify_message(self, message: str) -> str:
        """
        Classify the given message into predefined types using the classifier agent.
        
        Args:
            message: Message text to classify
            
        Returns:
            One of the MESSAGE_TYPES values
        """
        try:
            await self._ensure_agent()
            result_text = ""
            
            # Format the message for the classifier
            formatted_message = message.replace("{message}", message)
            
            async with self._agent.run_stream(formatted_message) as result:
                async for chunk in result.stream_text(delta=True):
                    result_text += chunk
            
            result_text = result_text.strip().lower()
            
            # Validate the classification result
            valid_types = list(MESSAGE_TYPES.values())
            if result_text not in valid_types:
                self.logger.warning(f"Invalid classification result: {result_text}")
                return MESSAGE_TYPES['UNKNOWN']

            return result_text
            
        except Exception as e:
            self.logger.error(f"Classification error: {str(e)}")
            return MESSAGE_TYPES['UNKNOWN'] 
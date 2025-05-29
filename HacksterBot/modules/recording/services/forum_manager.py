"""
Forum Manager - Handles forum post creation for meeting records.
"""

import logging
from typing import Optional

import discord


class ForumManager:
    """Manages forum posts for meeting records."""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
    async def create_forum_post(self, forum_channel: discord.ForumChannel, title: str, content: str) -> Optional[discord.Thread]:
        """Create a forum post for meeting record."""
        try:
            # Create the forum post
            thread, message = await forum_channel.create_thread(
                name=title,
                content=content
            )
            
            self.logger.info(f"Created forum post: {title}")
            return thread
            
        except Exception as e:
            self.logger.error(f"Failed to create forum post: {e}")
            return None
            
    async def post_with_file(self, thread: discord.Thread, content: str, file_path: str = None) -> Optional[discord.Message]:
        """Post a message with optional file attachment to the forum thread."""
        try:
            if file_path:
                file = discord.File(file_path)
                message = await thread.send(content=content, file=file)
            else:
                message = await thread.send(content=content)
                
            return message
            
        except Exception as e:
            self.logger.error(f"Failed to post to forum thread: {e}")
            return None 
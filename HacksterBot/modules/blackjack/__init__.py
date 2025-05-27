"""
Blackjack game module for HacksterBot.
Provides 21-point card game functionality with AI opponent.
"""
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from core.bot import ModuleBase
from .game import BlackjackGame
from .services.game_manager import GameManager

if TYPE_CHECKING:
    from core.bot import HacksterBot
    from core.config import Config

logger = logging.getLogger(__name__)


class Module(ModuleBase):
    """Blackjack game module."""
    
    def __init__(self, bot: 'HacksterBot', config: 'Config'):
        """
        Initialize the blackjack module.
        
        Args:
            bot: Bot instance
            config: Configuration object
        """
        super().__init__(bot, config)
        self.game_manager = None
    
    async def setup(self) -> None:
        """Setup the blackjack module."""
        await super().setup()
        
        # Initialize game manager
        self.game_manager = GameManager(self.bot, self.config)
        await self.game_manager.initialize()
        
        # Register slash commands
        @self.bot.tree.command(name="blackjack", description="開始一局21點遊戲")
        async def blackjack_command(interaction: discord.Interaction):
            """Start a new blackjack game."""
            await self.game_manager.start_game(interaction)
        
        @self.bot.tree.command(name="bj_stats", description="查看你的21點遊戲統計")
        async def blackjack_stats_command(interaction: discord.Interaction):
            """Show blackjack statistics."""
            await self.game_manager.show_stats(interaction)
        
        @self.bot.tree.command(name="bj_leaderboard", description="查看21點遊戲排行榜")
        async def blackjack_leaderboard_command(interaction: discord.Interaction):
            """Show blackjack leaderboard."""
            await self.game_manager.show_leaderboard(interaction)
        
        @self.bot.tree.command(name="bj_reset", description="重置你的21點遊戲狀態（清除卡住的遊戲）")
        async def blackjack_reset_command(interaction: discord.Interaction):
            """Reset blackjack game state."""
            await self.game_manager.reset_user_game(interaction)
        
        self.logger.info("Blackjack module setup complete")
    
    async def teardown(self) -> None:
        """Teardown the blackjack module."""
        if self.game_manager:
            await self.game_manager.close()
        
        await super().teardown()
        self.logger.info("Blackjack module teardown complete")


async def setup(bot: 'HacksterBot', config: 'Config') -> None:
    """
    Setup function for the blackjack module.
    
    Args:
        bot: Bot instance
        config: Configuration object
    """
    module = Module(bot, config)
    await module.setup()
    bot.modules['blackjack'] = module 
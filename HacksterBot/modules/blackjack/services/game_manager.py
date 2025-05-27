"""
Game manager for blackjack games.
Handles game lifecycle, statistics, and AI opponent logic.
"""
import logging
from typing import Dict, Optional, TYPE_CHECKING
from datetime import datetime

import discord
from core.mongodb import get_database
from core.models import GameStatistics
from ..game import BlackjackGame, GameResult
from ..ui import BlackjackView
from .ai_opponent import AIOpponent

if TYPE_CHECKING:
    from core.bot import HacksterBot
    from core.config import Config

logger = logging.getLogger(__name__)


class GameManager:
    """Manages blackjack games and statistics."""
    
    def __init__(self, bot: 'HacksterBot', config: 'Config'):
        """
        Initialize the game manager.
        
        Args:
            bot: Bot instance
            config: Configuration object
        """
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Active games (user_id -> BlackjackGame)
        self.active_games: Dict[int, BlackjackGame] = {}
        
        # AI opponent
        self.ai_opponent: Optional[AIOpponent] = None
    
    async def initialize(self) -> None:
        """Initialize the game manager."""
        try:
            # Initialize AI opponent
            self.ai_opponent = AIOpponent(self.bot, self.config)
            await self.ai_opponent.initialize()
            
            self.logger.info("Game manager initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize game manager: {e}")
            raise
    
    async def close(self) -> None:
        """Close the game manager and clean up resources."""
        # Clear active games
        self.active_games.clear()
        
        # Close AI opponent
        if self.ai_opponent:
            await self.ai_opponent.close()
        
        self.logger.info("Game manager closed")
    
    async def start_game(self, interaction: discord.Interaction) -> None:
        """
        Start a new blackjack game.
        
        Args:
            interaction: Discord interaction
        """
        user_id = interaction.user.id
        
        # Check if user already has an active game
        if user_id in self.active_games:
            embed = discord.Embed(
                title="⚠️ 遊戲進行中",
                description=(
                    "你已經有一局正在進行的21點遊戲了！\n\n"
                    "**解決方案：**\n"
                    "• 尋找並完成你的進行中遊戲\n"
                    "• 或使用 `/bj_reset` 重置遊戲狀態"
                ),
                color=discord.Color.orange()
            )
            embed.set_footer(text="💡 提示：如果找不到進行中的遊戲，可能是介面逾時了，請使用重置指令。")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            # Create a new game
            game = BlackjackGame(user_id)
            self.active_games[user_id] = game
            
            # Create the view
            view = BlackjackView(self, game)
            embed = view._create_game_embed()
            
            # Add AI commentary if available
            if self.ai_opponent:
                commentary = await self.ai_opponent.get_game_start_commentary(game)
                if commentary:
                    embed.add_field(
                        name="🤖 AI 莊家",
                        value=commentary,
                        inline=False
                    )
            
            await interaction.response.send_message(embed=embed, view=view)
            
            # Store the message reference in the view
            view.message = await interaction.original_response()
            
            # If the game ended immediately (e.g., blackjack), record the result
            if game.is_game_over():
                await self.record_game_result(game)
            
            self.logger.info(f"Started new blackjack game for user {user_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to start game for user {user_id}: {e}")
            embed = discord.Embed(
                title="❌ 錯誤",
                description="啟動遊戲時發生錯誤，請稍後再試。",
                color=discord.Color.red()
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def record_game_result(self, game: BlackjackGame) -> None:
        """
        Record the result of a completed game.
        
        Args:
            game: Completed blackjack game
        """
        try:
            # Get or create user statistics
            stats = GameStatistics.objects(
                user_id=game.player_id,
                game_type="blackjack"
            ).first()
            
            if not stats:
                stats = GameStatistics(
                    user_id=game.player_id,
                    game_type="blackjack"
                )
            
            # Update statistics
            stats.games_played += 1
            stats.last_played = datetime.utcnow()
            
            # Determine if it's a win, loss, or tie
            if game.result in [GameResult.PLAYER_WIN, GameResult.PLAYER_BLACKJACK, GameResult.DEALER_BUST]:
                stats.games_won += 1
                if game.result == GameResult.PLAYER_BLACKJACK:
                    # Blackjack gets special scoring
                    stats.total_score += 150  # 1.5x points for blackjack
                else:
                    stats.total_score += 100  # Standard win points
            elif game.result == GameResult.TIE:
                stats.games_tied += 1
                stats.total_score += 50  # Half points for tie
            else:
                # Loss - no points added
                pass
            
            # Calculate win rate
            if stats.games_played > 0:
                stats.win_rate = stats.games_won / stats.games_played
            
            # Update streak
            if game.result in [GameResult.PLAYER_WIN, GameResult.PLAYER_BLACKJACK, GameResult.DEALER_BUST]:
                stats.current_streak += 1
                stats.best_streak = max(stats.best_streak, stats.current_streak)
            else:
                stats.current_streak = 0
            
            await stats.save()
            
            self.logger.info(f"Recorded game result for user {game.player_id}: {game.result.name}")
            
        except Exception as e:
            self.logger.error(f"Failed to record game result for user {game.player_id}: {e}")
        finally:
            # Always clean up the active game, regardless of whether stats recording succeeded
            await self.cleanup_game(game.player_id)
    
    async def show_stats(self, interaction: discord.Interaction) -> None:
        """
        Show user's blackjack statistics.
        
        Args:
            interaction: Discord interaction
        """
        try:
            user_id = interaction.user.id
            
            # Get user statistics
            stats = GameStatistics.objects(
                user_id=user_id,
                game_type="blackjack"
            ).first()
            
            if not stats or stats.games_played == 0:
                embed = discord.Embed(
                    title="📊 你的21點統計",
                    description="你還沒有玩過21點遊戲！使用 `/blackjack` 開始你的第一局遊戲。",
                    color=discord.Color.blue()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Create statistics embed
            embed = discord.Embed(
                title="📊 你的21點統計",
                color=discord.Color.blue()
            )
            
            # Basic stats
            embed.add_field(
                name="🎮 基本統計",
                value=(
                    f"總遊戲數: {stats.games_played}\n"
                    f"勝利: {stats.games_won}\n"
                    f"平手: {stats.games_tied}\n"
                    f"敗北: {stats.games_played - stats.games_won - stats.games_tied}"
                ),
                inline=True
            )
            
            # Performance stats
            win_rate_percent = stats.win_rate * 100 if stats.win_rate else 0
            embed.add_field(
                name="📈 表現統計",
                value=(
                    f"勝率: {win_rate_percent:.1f}%\n"
                    f"總分數: {stats.total_score}\n"
                    f"當前連勝: {stats.current_streak}\n"
                    f"最佳連勝: {stats.best_streak}"
                ),
                inline=True
            )
            
            # Rank calculation
            rank = await self._calculate_user_rank(user_id, stats.total_score)
            embed.add_field(
                name="🏆 排名",
                value=f"第 {rank} 名",
                inline=True
            )
            
            # Last played
            if stats.last_played:
                embed.set_footer(text=f"最後遊戲時間: {stats.last_played.strftime('%Y-%m-%d %H:%M:%S')} UTC")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to show stats for user {interaction.user.id}: {e}")
            embed = discord.Embed(
                title="❌ 錯誤",
                description="無法載入統計資料，請稍後再試。",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def show_leaderboard(self, interaction: discord.Interaction) -> None:
        """
        Show the blackjack leaderboard.
        
        Args:
            interaction: Discord interaction
        """
        try:
            # Get top 10 players
            top_players = GameStatistics.objects(
                game_type="blackjack",
                games_played__gt=0
            ).order_by('-total_score').limit(10)
            
            if not top_players:
                embed = discord.Embed(
                    title="🏆 21點排行榜",
                    description="還沒有人玩過21點遊戲！成為第一個挑戰者吧！",
                    color=discord.Color.gold()
                )
                await interaction.response.send_message(embed=embed)
                return
            
            # Create leaderboard embed
            embed = discord.Embed(
                title="🏆 21點排行榜",
                description="分數最高的前10名玩家",
                color=discord.Color.gold()
            )
            
            # Add players to leaderboard
            leaderboard_text = ""
            for i, stats in enumerate(top_players, 1):
                try:
                    user = self.bot.get_user(stats.user_id)
                    username = user.display_name if user else f"User#{stats.user_id}"
                    
                    # Medal emojis for top 3
                    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
                    
                    win_rate_percent = stats.win_rate * 100 if stats.win_rate else 0
                    
                    leaderboard_text += (
                        f"{medal} **{username}**\n"
                        f"   分數: {stats.total_score} | "
                        f"勝率: {win_rate_percent:.1f}% | "
                        f"遊戲數: {stats.games_played}\n\n"
                    )
                    
                except Exception as e:
                    self.logger.warning(f"Failed to get user info for {stats.user_id}: {e}")
                    continue
            
            embed.description = leaderboard_text or "無法載入排行榜資料"
            
            # Add current user's rank if they're not in top 10
            user_id = interaction.user.id
            user_stats = GameStatistics.objects(
                user_id=user_id,
                game_type="blackjack"
            ).first()
            
            if user_stats and user_stats.games_played > 0:
                user_rank = await self._calculate_user_rank(user_id, user_stats.total_score)
                if user_rank > 10:
                    embed.add_field(
                        name="你的排名",
                        value=f"第 {user_rank} 名 (分數: {user_stats.total_score})",
                        inline=False
                    )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            self.logger.error(f"Failed to show leaderboard: {e}")
            embed = discord.Embed(
                title="❌ 錯誤",
                description="無法載入排行榜，請稍後再試。",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
    
    async def cleanup_game(self, user_id: int) -> None:
        """
        Clean up a user's active game.
        
        Args:
            user_id: User ID to clean up
        """
        if user_id in self.active_games:
            del self.active_games[user_id]
            self.logger.info(f"Cleaned up game for user {user_id}")
    
    async def reset_user_game(self, interaction: discord.Interaction) -> None:
        """
        Reset a user's game state (force cleanup).
        
        Args:
            interaction: Discord interaction
        """
        user_id = interaction.user.id
        
        if user_id in self.active_games:
            await self.cleanup_game(user_id)
            embed = discord.Embed(
                title="✅ 遊戲狀態已重置",
                description="你的21點遊戲狀態已清除，現在可以開始新遊戲了！",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="ℹ️ 無需重置",
                description="你目前沒有進行中的21點遊戲。",
                color=discord.Color.blue()
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def _calculate_user_rank(self, user_id: int, user_score: int) -> int:
        """
        Calculate a user's rank based on their score.
        
        Args:
            user_id: User ID
            user_score: User's total score
            
        Returns:
            User's rank (1-based)
        """
        try:
            # Count users with higher scores
            higher_scores = GameStatistics.objects(
                game_type="blackjack",
                total_score__gt=user_score,
                games_played__gt=0
            ).count()
            
            return higher_scores + 1
            
        except Exception as e:
            self.logger.error(f"Failed to calculate rank for user {user_id}: {e}")
            return 999  # Return a high rank on error 
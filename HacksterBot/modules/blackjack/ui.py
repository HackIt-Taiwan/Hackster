"""
Discord UI components for blackjack game.
"""
import discord
from typing import TYPE_CHECKING, Optional
from .game import BlackjackGame

if TYPE_CHECKING:
    from .services.game_manager import GameManager


class BlackjackView(discord.ui.View):
    """Main view for blackjack game interactions."""
    
    def __init__(self, game_manager: 'GameManager', game: BlackjackGame, timeout: float = 300):
        """
        Initialize the blackjack view.
        
        Args:
            game_manager: Game manager instance
            game: Current blackjack game
            timeout: View timeout in seconds
        """
        super().__init__(timeout=timeout)
        self.game_manager = game_manager
        self.game = game
        self.message: Optional[discord.Message] = None
        
        # Update button states
        self._update_buttons()
    
    def _update_buttons(self) -> None:
        """Update button states based on game state."""
        # Remove all items first
        self.clear_items()
        
        if not self.game.is_game_over():
            # Add hit button
            hit_button = discord.ui.Button(
                label="要牌 (Hit)",
                style=discord.ButtonStyle.primary,
                emoji="🎯",
                disabled=not self.game.can_hit()
            )
            hit_button.callback = self._hit_callback
            self.add_item(hit_button)
            
            # Add stand button
            stand_button = discord.ui.Button(
                label="停牌 (Stand)",
                style=discord.ButtonStyle.secondary,
                emoji="✋",
                disabled=not self.game.can_stand()
            )
            stand_button.callback = self._stand_callback
            self.add_item(stand_button)
        else:
            # Game is over, add new game button
            new_game_button = discord.ui.Button(
                label="新遊戲",
                style=discord.ButtonStyle.success,
                emoji="🔄"
            )
            new_game_button.callback = self._new_game_callback
            self.add_item(new_game_button)
            
            # Add stats button
            stats_button = discord.ui.Button(
                label="查看統計",
                style=discord.ButtonStyle.secondary,
                emoji="📊"
            )
            stats_button.callback = self._stats_callback
            self.add_item(stats_button)
    
    async def _hit_callback(self, interaction: discord.Interaction) -> None:
        """Handle hit button press."""
        if interaction.user.id != self.game.player_id:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return
        
        # Defer the response
        await interaction.response.defer()
        
        # Perform hit action
        if self.game.hit():
            # Update the view and message
            self._update_buttons()
            embed = self._create_game_embed()
            
            await interaction.edit_original_response(embed=embed, view=self)
            
            # If game is over, record the result
            if self.game.is_game_over():
                await self.game_manager.record_game_result(self.game)
        else:
            await interaction.followup.send("無法執行要牌動作！", ephemeral=True)
    
    async def _stand_callback(self, interaction: discord.Interaction) -> None:
        """Handle stand button press."""
        if interaction.user.id != self.game.player_id:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return
        
        # Defer the response
        await interaction.response.defer()
        
        # Perform stand action
        if self.game.stand():
            # Update the view and message
            self._update_buttons()
            embed = self._create_game_embed()
            
            await interaction.edit_original_response(embed=embed, view=self)
            
            # Record the game result
            await self.game_manager.record_game_result(self.game)
        else:
            await interaction.followup.send("無法執行停牌動作！", ephemeral=True)
    
    async def _new_game_callback(self, interaction: discord.Interaction) -> None:
        """Handle new game button press."""
        if interaction.user.id != self.game.player_id:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return
        
        # Start a new game
        await self.game_manager.start_game(interaction)
    
    async def _stats_callback(self, interaction: discord.Interaction) -> None:
        """Handle stats button press."""
        await self.game_manager.show_stats(interaction)
    
    def _create_game_embed(self) -> discord.Embed:
        """Create an embed for the current game state."""
        # Determine embed color based on game state
        if self.game.is_game_over():
            if self.game.result.name in ['PLAYER_WIN', 'PLAYER_BLACKJACK', 'DEALER_BUST']:
                color = discord.Color.green()
            elif self.game.result.name == 'TIE':
                color = discord.Color.gold()
            else:
                color = discord.Color.red()
        else:
            color = discord.Color.blue()
        
        embed = discord.Embed(
            title="🃏 21點遊戲",
            description=self.game.get_game_display(),
            color=color
        )
        
        # Add footer with deck info
        embed.set_footer(text=f"剩餘牌數: {self.game.deck.cards_remaining()}")
        
        return embed
    
    async def on_timeout(self) -> None:
        """Handle view timeout."""
        # Disable all buttons
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        
        # Try to edit the message if it exists
        if self.message:
            try:
                embed = self._create_game_embed()
                embed.set_footer(text="遊戲已逾時")
                await self.message.edit(embed=embed, view=self)
            except discord.NotFound:
                pass
        
        # Clean up the game from active games
        await self.game_manager.cleanup_game(self.game.player_id)


class ConfirmView(discord.ui.View):
    """View for confirmation dialogs."""
    
    def __init__(self, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.result: Optional[bool] = None
    
    @discord.ui.button(label="是", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Confirm button callback."""
        self.result = True
        self.stop()
        await interaction.response.defer()
    
    @discord.ui.button(label="否", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel button callback."""
        self.result = False
        self.stop()
        await interaction.response.defer()
    
    async def on_timeout(self) -> None:
        """Handle timeout."""
        self.result = False
        self.stop() 
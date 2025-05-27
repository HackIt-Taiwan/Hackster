"""
Tickets System Module for HacksterBot.

This module provides a centralized ticket management system that can be used
by other modules to award and track tickets for various activities.

Features:
- Award tickets to users for various activities
- Track ticket usage and history
- User commands to view their own tickets
- API for other modules to integrate with
"""
import logging
from typing import Optional, Dict, Any, List
import discord
from discord.ext import commands
from discord import app_commands

from core.module_base import ModuleBase
from core.config import Config
from .services.ticket_service import TicketService

logger = logging.getLogger(__name__)


class TicketsSystemModule(ModuleBase):
    """
    Centralized ticket management system.
    """
    
    def __init__(self, bot, config):
        super().__init__(bot, config)
        self.ticket_service = TicketService()
        
    async def setup(self):
        """Initialize the tickets system module."""
        try:
            logger.info("Setting up Tickets System module...")
            
            # Initialize ticket service
            await self.ticket_service.initialize()
            
            # Create and register slash commands using proper app_commands syntax
            @app_commands.command(name="tickets", description="查看你的票券")
            @app_commands.describe(ticket_type="票券類型 (可選)")
            async def tickets_command(interaction: discord.Interaction, ticket_type: Optional[str] = None):
                await self._handle_tickets_command(interaction, ticket_type)
            
            @app_commands.command(name="ticket_history", description="查看你的票券歷史記錄")
            @app_commands.describe(
                ticket_type="票券類型 (可選)",
                limit="顯示數量限制 (預設 10)"
            )
            async def ticket_history_command(interaction: discord.Interaction, 
                                           ticket_type: Optional[str] = None, 
                                           limit: int = 10):
                await self._handle_ticket_history_command(interaction, ticket_type, limit)
            
            # Add commands to tree
            self.bot.tree.add_command(tickets_command)
            self.bot.tree.add_command(ticket_history_command)
            
            logger.info("Tickets System module setup completed")
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup Tickets System module: {e}")
            return False
    
    async def teardown(self):
        """Clean up the tickets system module."""
        try:
            logger.info("Tearing down Tickets System module...")
            
            # Remove slash commands
            self.bot.tree.remove_command("tickets")
            self.bot.tree.remove_command("ticket_history")
            
            logger.info("Tickets System module teardown completed")
            
        except Exception as e:
            logger.error(f"Error during Tickets System module teardown: {e}")
    
    # Public API for other modules
    async def award_ticket(self, user_id: int, guild_id: int, ticket_type: str, 
                          source: str, event_name: Optional[str] = None, 
                          metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Award a ticket to a user.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            ticket_type: Type of ticket (e.g., 'invite', 'event', 'special')
            source: Description of how the ticket was earned
            event_name: Associated event name (optional)
            metadata: Additional data about the ticket (optional)
            
        Returns:
            bool: True if ticket was awarded successfully
        """
        return await self.ticket_service.award_ticket(
            user_id=user_id,
            guild_id=guild_id,
            ticket_type=ticket_type,
            source=source,
            event_name=event_name,
            metadata=metadata
        )
    
    async def remove_ticket(self, user_id: int, guild_id: int, ticket_id: str, 
                           reason: str) -> bool:
        """
        Remove a ticket (delete it from database).
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            ticket_id: Ticket ID to remove
            reason: Reason for removing the ticket
            
        Returns:
            bool: True if ticket was removed successfully
        """
        return await self.ticket_service.remove_ticket(
            user_id=user_id,
            guild_id=guild_id,
            ticket_id=ticket_id,
            reason=reason
        )
    
    async def remove_tickets_by_type(self, user_id: int, guild_id: int, 
                                    ticket_type: str, count: int, reason: str) -> int:
        """
        Remove multiple tickets of a specific type.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            ticket_type: Type of tickets to remove
            count: Number of tickets to remove
            reason: Reason for removing the tickets
            
        Returns:
            int: Number of tickets actually removed
        """
        return await self.ticket_service.remove_tickets_by_type(
            user_id=user_id,
            guild_id=guild_id,
            ticket_type=ticket_type,
            count=count,
            reason=reason
        )
    
    async def get_user_tickets(self, user_id: int, guild_id: int, 
                              ticket_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get tickets for a user.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            ticket_type: Filter by ticket type (optional)
            
        Returns:
            List of ticket data
        """
        return await self.ticket_service.get_user_tickets(
            user_id=user_id,
            guild_id=guild_id,
            ticket_type=ticket_type
        )
    
    async def get_user_ticket_count(self, user_id: int, guild_id: int,
                                   ticket_type: Optional[str] = None) -> int:
        """
        Get ticket count for a user.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            ticket_type: Filter by ticket type (optional)
            
        Returns:
            Number of tickets
        """
        return await self.ticket_service.get_user_ticket_count(
            user_id=user_id,
            guild_id=guild_id,
            ticket_type=ticket_type
        )
    
    # User Command Handlers
    async def _handle_tickets_command(self, interaction: discord.Interaction, ticket_type: Optional[str] = None):
        """Handle tickets command."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            user_id = interaction.user.id
            guild_id = interaction.guild.id
            
            # Get user tickets
            tickets = await self.get_user_tickets(
                user_id=user_id,
                guild_id=guild_id,
                ticket_type=ticket_type
            )
            
            if not tickets:
                embed = discord.Embed(
                    title="🎫 你的票券",
                    description="你目前沒有任何票券。",
                    color=0x3498db
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Group tickets by type and event
            ticket_summary = {}
            for ticket in tickets:
                key = f"{ticket['ticket_type']}"
                if ticket.get('event_name'):
                    key += f" - {ticket['event_name']}"
                
                if key not in ticket_summary:
                    ticket_summary[key] = 0
                
                ticket_summary[key] += 1
            
            # Create embed
            embed = discord.Embed(
                title="🎫 你的票券",
                color=0x3498db
            )
            
            description_lines = []
            total_tickets = len(tickets)
            
            description_lines.append(f"**總計：{total_tickets} 張票券**\n")
            
            for ticket_key, count in ticket_summary.items():
                description_lines.append(f"🎫 **{ticket_key}**：{count} 張\n")
            
            embed.description = "\n".join(description_lines)
            
            # Add footer
            embed.set_footer(text="使用 /ticket_history 查看詳細歷史記錄")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in tickets command: {e}")
            await interaction.followup.send(
                "❌ 查看票券時發生錯誤，請稍後再試。",
                ephemeral=True
            )
    
    async def _handle_ticket_history_command(self, interaction: discord.Interaction,
                                           ticket_type: Optional[str] = None,
                                           limit: int = 10):
        """Handle ticket history command."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            user_id = interaction.user.id
            guild_id = interaction.guild.id
            
            # Validate limit
            if limit < 1 or limit > 50:
                limit = 10
            
            # Get user tickets
            tickets = await self.get_user_tickets(
                user_id=user_id,
                guild_id=guild_id,
                ticket_type=ticket_type
            )
            
            if not tickets:
                embed = discord.Embed(
                    title="📋 票券歷史記錄",
                    description="你目前沒有任何票券記錄。",
                    color=0x3498db
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Sort by earned date (newest first) and limit
            tickets.sort(key=lambda x: x['earned_at'], reverse=True)
            tickets = tickets[:limit]
            
            # Create embed
            embed = discord.Embed(
                title="📋 票券歷史記錄",
                color=0x3498db
            )
            
            description_lines = []
            
            for ticket in tickets:
                earned_date = discord.utils.format_dt(ticket['earned_at'], style='d')
                
                line = f"🎫 **{ticket['ticket_type']}**"
                if ticket.get('event_name'):
                    line += f" - {ticket['event_name']}"
                line += f"\n   來源：{ticket['source']} | 獲得：{earned_date}"
                
                description_lines.append(line)
            
            embed.description = "\n\n".join(description_lines)
            
            # Add footer
            total_count = len(await self.get_user_tickets(user_id, guild_id, ticket_type))
            if total_count > limit:
                embed.set_footer(text=f"顯示最新 {limit} 筆記錄，共 {total_count} 筆")
            else:
                embed.set_footer(text=f"共 {total_count} 筆記錄")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in ticket_history command: {e}")
            await interaction.followup.send(
                "❌ 查看票券歷史時發生錯誤，請稍後再試。",
                ephemeral=True
            )


# Module factory function
def create_module(bot, config):
    """Create and return the tickets system module instance."""
    return TicketsSystemModule(bot, config) 
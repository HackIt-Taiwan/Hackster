"""
Ticket Service for managing user tickets.

This service provides all ticket-related operations including:
- Awarding tickets to users
- Tracking ticket usage
- Querying user tickets
- Managing ticket metadata
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from mongoengine import Q

from core.models import EventTicket

logger = logging.getLogger(__name__)


class TicketService:
    """
    Service class for managing user tickets.
    """
    
    def __init__(self):
        self.initialized = False
    
    async def initialize(self):
        """Initialize the ticket service."""
        try:
            logger.info("Initializing Ticket Service...")
            self.initialized = True
            logger.info("Ticket Service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Ticket Service: {e}")
            raise
    
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
        try:
            # Create new ticket
            ticket = EventTicket(
                user_id=user_id,
                guild_id=guild_id,
                ticket_type=ticket_type,
                ticket_source=source,
                event_name=event_name,
                earned_at=datetime.utcnow(),
                metadata=metadata or {}
            )
            
            # Save to database
            ticket.save()
            
            logger.info(f"Awarded {ticket_type} ticket to user {user_id} in guild {guild_id}")
            logger.debug(f"Ticket details: source={source}, event={event_name}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to award ticket to user {user_id}: {e}")
            return False
    
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
        try:
            # Find the ticket
            ticket = EventTicket.objects(
                id=ticket_id,
                user_id=user_id,
                guild_id=guild_id
            ).first()
            
            if not ticket:
                logger.warning(f"Ticket {ticket_id} not found for user {user_id}")
                return False
            
            # Delete the ticket
            ticket.delete()
            
            logger.info(f"Removed ticket {ticket_id} for user {user_id}: {reason}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove ticket {ticket_id} for user {user_id}: {e}")
            return False
    
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
        try:
            # Find tickets of the specified type (oldest first)
            tickets = EventTicket.objects(
                user_id=user_id,
                guild_id=guild_id,
                ticket_type=ticket_type
            ).order_by('earned_at')[:count]
            
            removed_count = 0
            for ticket in tickets:
                ticket.delete()
                removed_count += 1
            
            if removed_count > 0:
                logger.info(f"Removed {removed_count} {ticket_type} tickets for user {user_id}: {reason}")
            
            return removed_count
            
        except Exception as e:
            logger.error(f"Failed to remove {count} {ticket_type} tickets for user {user_id}: {e}")
            return 0
    
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
        try:
            # Build query
            query = Q(user_id=user_id, guild_id=guild_id)
            
            if ticket_type:
                query &= Q(ticket_type=ticket_type)
            
            # Get tickets
            tickets = EventTicket.objects(query).order_by('-earned_at')
            
            # Convert to dict format
            result = []
            for ticket in tickets:
                ticket_data = {
                    'id': str(ticket.id),
                    'ticket_type': ticket.ticket_type,
                    'source': ticket.ticket_source,
                    'event_name': ticket.event_name,
                    'earned_at': ticket.earned_at,
                    'metadata': ticket.metadata
                }
                
                result.append(ticket_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get tickets for user {user_id}: {e}")
            return []
    
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
        try:
            # Build query
            query = Q(user_id=user_id, guild_id=guild_id)
            
            if ticket_type:
                query &= Q(ticket_type=ticket_type)
            
            # Count tickets
            count = EventTicket.objects(query).count()
            
            return count
            
        except Exception as e:
            logger.error(f"Failed to count tickets for user {user_id}: {e}")
            return 0
    
    async def get_user_ticket_summary(self, user_id: int, guild_id: int) -> Dict[str, int]:
        """
        Get a summary of user's tickets grouped by type.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            
        Returns:
            Dict with ticket type as key and count as value
        """
        try:
            tickets = await self.get_user_tickets(user_id, guild_id)
            
            summary = {}
            for ticket in tickets:
                ticket_type = ticket['ticket_type']
                if ticket_type not in summary:
                    summary[ticket_type] = 0
                
                summary[ticket_type] += 1
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to get ticket summary for user {user_id}: {e}")
            return {}
    
    async def revoke_tickets(self, user_id: int, guild_id: int,
                            ticket_type: Optional[str] = None,
                            source_filter: Optional[str] = None) -> int:
        """
        Revoke (delete) tickets for a user.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            ticket_type: Filter by ticket type (optional)
            source_filter: Filter by ticket source (optional)
            
        Returns:
            Number of tickets revoked
        """
        try:
            # Build query
            query = Q(user_id=user_id, guild_id=guild_id)
            
            if ticket_type:
                query &= Q(ticket_type=ticket_type)
            
            if source_filter:
                query &= Q(ticket_source__icontains=source_filter)
            
            # Get tickets to revoke
            tickets = EventTicket.objects(query)
            count = tickets.count()
            
            # Delete tickets
            tickets.delete()
            
            if count > 0:
                logger.info(f"Revoked {count} tickets for user {user_id}")
            
            return count
            
        except Exception as e:
            logger.error(f"Failed to revoke tickets for user {user_id}: {e}")
            return 0
    
    async def get_ticket_statistics(self, guild_id: int) -> Dict[str, Any]:
        """
        Get overall ticket statistics for a guild.
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            Dict with various statistics
        """
        try:
            # Get all tickets for the guild
            all_tickets = EventTicket.objects(guild_id=guild_id)
            
            total_tickets = all_tickets.count()
            
            # Get unique users with tickets
            unique_users = len(set(ticket.user_id for ticket in all_tickets))
            
            # Get ticket types
            ticket_types = {}
            for ticket in all_tickets:
                ticket_type = ticket.ticket_type
                if ticket_type not in ticket_types:
                    ticket_types[ticket_type] = 0
                
                ticket_types[ticket_type] += 1
            
            return {
                'total_tickets': total_tickets,
                'unique_users': unique_users,
                'ticket_types': ticket_types
            }
            
        except Exception as e:
            logger.error(f"Failed to get ticket statistics for guild {guild_id}: {e}")
            return {
                'total_tickets': 0,
                'unique_users': 0,
                'ticket_types': {}
            } 
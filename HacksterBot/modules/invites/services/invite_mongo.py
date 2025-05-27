"""
MongoDB service for invite tracking system.
Handles invite records, statistics, and event tickets.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from mongoengine import Q

from core.models import InviteRecord, InviteStatistics

logger = logging.getLogger(__name__)

# GMT+8 時區
GMT_PLUS_8 = timezone(timedelta(hours=8))


class InviteMongo:
    """MongoDB service for invite tracking."""
    
    def __init__(self, config):
        """Initialize the invite MongoDB service."""
        self.config = config
        self._ticket_system = None
        
    def set_ticket_system(self, ticket_system):
        """Set the ticket system reference for ticket operations."""
        self._ticket_system = ticket_system
    
    def to_gmt8_time(self, dt: datetime) -> datetime:
        """
        Convert UTC datetime to GMT+8.
        
        Args:
            dt: UTC datetime
            
        Returns:
            datetime: GMT+8 datetime
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(GMT_PLUS_8)
    
    def record_invite_join(self, invite_code: str, guild_id: int, inviter_id: int, 
                          invited_user_id: int, invited_user_name: str) -> InviteRecord:
        """
        Record a new member joining through an invite.
        
        Args:
            invite_code: The invite code used
            guild_id: Guild ID
            inviter_id: User ID of the inviter
            invited_user_id: User ID of the invited user
            invited_user_name: Name of the invited user
            
        Returns:
            InviteRecord: The created invite record
        """
        try:
            # Create invite record
            invite_record = InviteRecord(
                invite_code=invite_code,
                guild_id=guild_id,
                inviter_id=inviter_id,
                invited_user_id=invited_user_id,
                invited_user_name=invited_user_name,
                joined_at=datetime.utcnow(),
                is_active=True
            )
            invite_record.save()
            
            # Update inviter statistics
            self._update_inviter_stats(inviter_id, guild_id, 'join')
            
            logger.info(f"Recorded invite join: {invited_user_name} invited by {inviter_id} using {invite_code}")
            return invite_record
            
        except Exception as e:
            logger.error(f"Error recording invite join: {e}")
            raise
    
    def record_invite_leave(self, invited_user_id: int, guild_id: int) -> Optional[InviteRecord]:
        """
        Record a member leaving who was invited by someone.
        
        Args:
            invited_user_id: User ID of the user who left
            guild_id: Guild ID
            
        Returns:
            InviteRecord: Updated invite record if found, None otherwise
        """
        try:
            # Find active invite record
            invite_record = InviteRecord.objects(
                invited_user_id=invited_user_id,
                guild_id=guild_id,
                is_active=True
            ).first()
            
            if not invite_record:
                logger.info(f"No active invite record found for user {invited_user_id}")
                return None
            
            # Update record
            invite_record.left_at = datetime.utcnow()
            invite_record.is_active = False
            invite_record.save()
            
            # Update inviter statistics
            self._update_inviter_stats(invite_record.inviter_id, guild_id, 'leave')
            
            logger.info(f"Recorded invite leave: {invited_user_id} (invited by {invite_record.inviter_id})")
            return invite_record
            
        except Exception as e:
            logger.error(f"Error recording invite leave: {e}")
            raise
    
    def get_user_invite_stats(self, user_id: int, guild_id: int) -> Optional[InviteStatistics]:
        """
        Get invite statistics for a user.
        
        Args:
            user_id: User ID
            guild_id: Guild ID
            
        Returns:
            InviteStatistics: User's invite statistics
        """
        try:
            return InviteStatistics.objects(
                user_id=user_id,
                guild_id=guild_id
            ).first()
            
        except Exception as e:
            logger.error(f"Error getting user invite stats: {e}")
            return None
    
    def get_invite_leaderboard(self, guild_id: int, limit: int = 10) -> List[InviteStatistics]:
        """
        Get invite leaderboard for a guild.
        
        Args:
            guild_id: Guild ID
            limit: Maximum number of results
            
        Returns:
            List[InviteStatistics]: Top inviters
        """
        try:
            return InviteStatistics.objects(
                guild_id=guild_id,
                active_invites__gt=0
            ).order_by('-active_invites', '-total_invites').limit(limit)
            
        except Exception as e:
            logger.error(f"Error getting invite leaderboard: {e}")
            return []
    
    def find_invite_by_usage(self, guild_id: int, before_invites: Dict, after_invites: Dict) -> Optional[Tuple[str, int]]:
        """
        Find which invite was used by comparing invite usage before and after.
        
        Args:
            guild_id: Guild ID
            before_invites: Invite data before member join
            after_invites: Invite data after member join
            
        Returns:
            Tuple[str, int]: (invite_code, inviter_id) if found, None otherwise
        """
        try:
            for code, after_data in after_invites.items():
                if code in before_invites:
                    before_uses = before_invites[code].get('uses', 0)
                    after_uses = after_data.get('uses', 0)
                    
                    if after_uses > before_uses:
                        inviter_id = after_data.get('inviter_id')
                        logger.info(f"Found used invite: {code} by user {inviter_id}")
                        return code, inviter_id
                else:
                    # New invite was created and used immediately
                    inviter_id = after_data.get('inviter_id')
                    logger.info(f"Found new invite used: {code} by user {inviter_id}")
                    return code, inviter_id
            
            logger.warning("Could not determine which invite was used")
            return None
            
        except Exception as e:
            logger.error(f"Error finding invite by usage: {e}")
            return None
    
    def get_user_active_invites(self, user_id: int, guild_id: int) -> List[InviteRecord]:
        """
        Get all active invites by a user.
        
        Args:
            user_id: User ID
            guild_id: Guild ID
            
        Returns:
            List[InviteRecord]: Active invite records
        """
        try:
            return InviteRecord.objects(
                inviter_id=user_id,
                guild_id=guild_id,
                is_active=True
            ).order_by('-joined_at')
            
        except Exception as e:
            logger.error(f"Error getting user active invites: {e}")
            return []
    
    async def get_user_tickets(self, user_id: int, guild_id: int) -> List[Dict]:
        """
        Get tickets for a user using the centralized ticket system.
        
        Args:
            user_id: User ID
            guild_id: Guild ID
            
        Returns:
            List[Dict]: User's tickets
        """
        try:
            if not self._ticket_system:
                logger.warning("Ticket system not available")
                return []
            
            return await self._ticket_system.get_user_tickets(user_id, guild_id)
            
        except Exception as e:
            logger.error(f"Error getting user tickets: {e}")
            return []
    
    async def get_user_current_event_tickets(self, user_id: int, guild_id: int, current_event_names: List[str]) -> Dict:
        """
        Get tickets for current/active events only using the centralized ticket system.
        
        Args:
            user_id: User ID
            guild_id: Guild ID
            current_event_names: List of current active event names
            
        Returns:
            Dict: Ticket summary for current events
        """
        try:
            if not self._ticket_system:
                logger.warning("Ticket system not available")
                return {'total_tickets': 0, 'events': {}}
            
            # Get all tickets for the user
            all_tickets = await self._ticket_system.get_user_tickets(user_id, guild_id)
            
            # Filter for current events
            current_tickets = [
                ticket for ticket in all_tickets 
                if ticket.get('event_name') in current_event_names
            ]
            
            # Group by event
            event_summary = {}
            for ticket in current_tickets:
                event_name = ticket.get('event_name') or "未知活動"
                if event_name not in event_summary:
                    event_summary[event_name] = 0
                event_summary[event_name] += 1
            
            return {
                'total_tickets': len(current_tickets),
                'events': event_summary
            }
            
        except Exception as e:
            logger.error(f"Error getting current event tickets: {e}")
            return {
                'total_tickets': 0,
                'events': {}
            }
    
    async def get_guild_statistics(self, guild_id: int) -> Dict:
        """
        Get overall invite statistics for a guild.
        
        Args:
            guild_id: Guild ID
            
        Returns:
            Dict: Guild statistics
        """
        try:
            stats = InviteStatistics.objects(guild_id=guild_id)
            
            total_inviters = stats.count()
            total_invites = sum(stat.total_invites for stat in stats)
            active_invites = sum(stat.active_invites for stat in stats)
            
            # Get recent activity (last 7 days)
            recent_cutoff = datetime.utcnow() - timedelta(days=7)
            recent_joins = InviteRecord.objects(
                guild_id=guild_id,
                joined_at__gte=recent_cutoff
            ).count()
            
            # Get tickets awarded count from ticket system
            tickets_awarded = 0
            if self._ticket_system:
                try:
                    ticket_stats = await self._ticket_system.get_ticket_statistics(guild_id)
                    tickets_awarded = ticket_stats.get('total_tickets', 0)
                except Exception as e:
                    logger.warning(f"Could not get ticket statistics: {e}")
            
            return {
                'total_inviters': total_inviters,
                'total_invites': total_invites,
                'active_invites': active_invites,
                'recent_joins_7d': recent_joins,
                'tickets_awarded': tickets_awarded
            }
            
        except Exception as e:
            logger.error(f"Error getting guild statistics: {e}")
            return {}
    
    def _update_inviter_stats(self, inviter_id: int, guild_id: int, action: str):
        """
        Update inviter statistics.
        
        Args:
            inviter_id: User ID of the inviter
            guild_id: Guild ID
            action: 'join' or 'leave'
        """
        try:
            # Try to get existing stats
            stats = InviteStatistics.objects(
                user_id=inviter_id,
                guild_id=guild_id
            ).first()
            
            # Create new stats if none exist
            if not stats:
                stats = InviteStatistics(
                    user_id=inviter_id,
                    guild_id=guild_id,
                    total_invites=0,
                    active_invites=0,
                    left_invites=0,
                    created_at=datetime.utcnow()
                )
            
            if action == 'join':
                stats.total_invites += 1
                stats.active_invites += 1
                
                if not stats.first_invite_at:
                    stats.first_invite_at = datetime.utcnow()
                stats.last_invite_at = datetime.utcnow()
                
            elif action == 'leave':
                stats.active_invites = max(0, stats.active_invites - 1)
                stats.left_invites += 1
            
            stats.save()
            logger.debug(f"Updated stats for user {inviter_id}: {action}")
            
        except Exception as e:
            logger.error(f"Error updating inviter stats: {e}")
            raise
    
    async def revoke_invite_tickets(self, inviter_id: int, invited_user_id: int, guild_id: int) -> int:
        """
        Revoke tickets awarded for a specific invite when the invited user leaves.
        
        Args:
            inviter_id: User ID of the inviter
            invited_user_id: User ID of the invited user who left
            guild_id: Guild ID
            
        Returns:
            int: Number of tickets revoked
        """
        try:
            if not self._ticket_system:
                logger.warning("Ticket system not available")
                return 0
            
            # Remove one invite ticket (oldest first)
            revoked_count = await self._ticket_system.remove_tickets_by_type(
                user_id=inviter_id,
                guild_id=guild_id,
                ticket_type='invite',
                count=1,
                reason=f"User {invited_user_id} left the server"
            )
            
            if revoked_count > 0:
                logger.info(f"Revoked {revoked_count} invite tickets for user {inviter_id} due to user {invited_user_id} leaving")
            
            return revoked_count
            
        except Exception as e:
            logger.error(f"Error revoking invite tickets: {e}")
            return 0 
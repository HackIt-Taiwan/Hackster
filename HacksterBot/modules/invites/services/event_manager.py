"""
Event manager for invite system.
Handles loading event configurations and processing rewards.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class EventManager:
    """Manages invite events and rewards."""
    
    def __init__(self, config, invite_mongo, bot):
        """
        Initialize event manager.
        
        Args:
            config: Bot configuration
            invite_mongo: Invite MongoDB service
            bot: Discord bot instance (for accessing ticket system)
        """
        self.config = config
        self.invite_mongo = invite_mongo
        self.bot = bot
        self.events_config = {}
        self.last_loaded = None
        
    def load_events_config(self) -> bool:
        """
        Load events configuration from JSON file.
        
        Returns:
            bool: True if loaded successfully
        """
        try:
            config_file = Path(self.config.invite.events_config_file)
            
            if not config_file.exists():
                logger.warning(f"Events config file not found: {config_file}")
                return False
            
            # Check if file was modified
            file_mtime = config_file.stat().st_mtime
            if self.last_loaded and file_mtime <= self.last_loaded:
                return True
            
            with open(config_file, 'r', encoding='utf-8') as f:
                self.events_config = json.load(f)
            
            self.last_loaded = file_mtime
            logger.info(f"Loaded events config from {config_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error loading events config: {e}")
            return False
    
    def get_active_events(self) -> List[Dict]:
        """
        Get currently active events.
        
        Returns:
            List[Dict]: Active events
        """
        if not self.load_events_config():
            return []
        
        active_events = []
        current_date = datetime.utcnow().date()
        
        for event in self.events_config.get('active_events', []):
            if not event.get('enabled', False):
                continue
            
            # Check date range
            start_date = datetime.strptime(event['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(event['end_date'], '%Y-%m-%d').date()
            
            if start_date <= current_date <= end_date:
                active_events.append(event)
                
        return active_events
    
    def get_active_event_names(self) -> List[str]:
        """
        Get names of currently active events.
        
        Returns:
            List[str]: List of active event names
        """
        active_events = self.get_active_events()
        return [event['name'] for event in active_events]
    
    def check_invite_rewards(self, inviter_id: int, guild_id: int, invited_user_id: int, 
                           invited_user_name: str) -> List[Dict]:
        """
        Check if an invite qualifies for any rewards.
        
        Args:
            inviter_id: User ID of the inviter
            guild_id: Guild ID
            invited_user_id: User ID of invited user
            invited_user_name: Name of invited user
            
        Returns:
            List[Dict]: List of rewards to be processed
        """
        if not self.config.invite.check_events_on_invite:
            return []
        
        active_events = self.get_active_events()
        if not active_events:
            return []
        
        rewards_to_process = []
        
        for event in active_events:
            if event.get('type') != 'invite_reward':
                continue
            
            # Check if user qualifies for this event
            if self._check_event_conditions(event, inviter_id, guild_id):
                # Process rewards
                for reward in event.get('rewards', []):
                    reward_data = {
                        'event': event,
                        'reward': reward,
                        'inviter_id': inviter_id,
                        'guild_id': guild_id,
                        'invited_user_id': invited_user_id,
                        'invited_user_name': invited_user_name
                    }
                    rewards_to_process.append(reward_data)
        
        return rewards_to_process
    
    async def process_reward(self, reward_data: Dict) -> Optional[Dict]:
        """
        Process a single reward using the centralized ticket system.
        
        Args:
            reward_data: Reward data dictionary
            
        Returns:
            Dict: Result of reward processing
        """
        try:
            event = reward_data['event']
            reward = reward_data['reward']
            inviter_id = reward_data['inviter_id']
            guild_id = reward_data['guild_id']
            invited_user_name = reward_data['invited_user_name']
            
            if reward['type'] == 'ticket':
                # Get the ticket system module
                ticket_system = self.bot.get_module('tickets_system')
                if not ticket_system:
                    logger.error("Ticket system module not found")
                    return {
                        'type': 'ticket',
                        'success': False,
                        'error': 'Ticket system not available'
                    }
                
                # Award ticket using centralized system
                success = await ticket_system.award_ticket(
                    user_id=inviter_id,
                    guild_id=guild_id,
                    ticket_type=reward.get('ticket_type', 'invite'),
                    source=f"邀請 {invited_user_name}",
                    event_name=event['name'],
                    metadata={
                        'event_id': event['id'],
                        'invited_user_id': reward_data['invited_user_id'],
                        'invited_user_name': invited_user_name
                    }
                )
                
                if success:
                    result = {
                        'type': 'ticket',
                        'success': True,
                        'amount': reward['amount'],
                        'description': reward.get('description', '邀請票券')
                    }
                    
                    logger.info(f"Awarded {reward['amount']} {reward['type']} to user {inviter_id}")
                    return result
                else:
                    return {
                        'type': 'ticket',
                        'success': False,
                        'error': 'Failed to award ticket'
                    }
            
            else:
                logger.warning(f"Unknown reward type: {reward['type']}")
                return None
                
        except Exception as e:
            logger.error(f"Error processing reward: {e}")
            return {
                'type': reward.get('type', 'unknown'),
                'success': False,
                'error': str(e)
            }
    
    def get_reward_notification_message(self, reward_data: Dict, result: Dict) -> Optional[str]:
        """
        Generate reward notification message.
        
        Args:
            reward_data: Original reward data
            result: Reward processing result
            
        Returns:
            Optional[str]: Notification message or None
        """
        if not result or not result.get('success'):
            return None
        
        event = reward_data['event']
        reward = reward_data['reward']
        invited_user_name = reward_data['invited_user_name']
        
        # Check if notifications are enabled for this event
        if not event.get('notifications', {}).get('on_reward', True):
            return None
        
        if reward['type'] == 'ticket':
            return (
                f"🎉 恭喜！你邀請了 **{invited_user_name}** 加入伺服器！\n"
                f"🎫 獲得 **{reward['amount']}** 張 {reward.get('description', '票券')}\n"
                f"📅 活動：{event['name']}"
            )
        
        return None
    
    def get_user_event_summary(self, user_id: int, guild_id: int) -> Dict:
        """
        Get summary of user's participation in events.
        
        Args:
            user_id: User ID
            guild_id: Guild ID
            
        Returns:
            Dict: Event participation summary
        """
        try:
            active_events = self.get_active_events()
            
            summary = {
                'active_events': len(active_events),
                'events': []
            }
            
            for event in active_events:
                event_info = {
                    'name': event['name'],
                    'description': event['description'],
                    'end_date': event['end_date']
                }
                summary['events'].append(event_info)
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting user event summary: {e}")
            return {'active_events': 0, 'events': []}
    
    def _check_event_conditions(self, event: Dict, user_id: int, guild_id: int) -> bool:
        """
        Check if user meets event conditions.
        
        Args:
            event: Event configuration
            user_id: User ID
            guild_id: Guild ID
            
        Returns:
            bool: True if conditions are met
        """
        try:
            conditions = event.get('conditions', {})
            
            # For invite rewards, we typically award on each invite
            # rather than checking total invite count
            invite_count_required = conditions.get('invite_count', 1)
            
            # Since this is called for each new invite, we just check if it's >= 1
            return invite_count_required <= 1
            
        except Exception as e:
            logger.error(f"Error checking event conditions: {e}")
            return False
    
    def get_global_settings(self) -> Dict:
        """
        Get global settings from events config.
        
        Returns:
            Dict: Global settings
        """
        if not self.load_events_config():
            return {}
        
        return self.events_config.get('global_settings', {})
    
    def get_reward_types(self) -> Dict:
        """
        Get reward types configuration.
        
        Returns:
            Dict: Reward types configuration
        """
        if not self.load_events_config():
            return {}
        
        return self.events_config.get('reward_types', {}) 
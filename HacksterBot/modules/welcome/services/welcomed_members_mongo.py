"""
MongoDB-based welcomed members management using MongoEngine.
Replaces the SQLite-based implementation with MongoDB.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from mongoengine import Q
from core.models import WelcomedMember

logger = logging.getLogger(__name__)


class WelcomedMembersMongo:
    """
    MongoDB-based implementation for managing welcomed members.
    Uses MongoEngine for object-oriented database operations.
    """
    
    def __init__(self, config):
        """
        Initialize the MongoDB welcomed members manager.
        
        Args:
            config: Configuration object
        """
        self.config = config
        logger.info("WelcomedMembersMongo initialized")

    def add_or_update_member(self, user_id: int, guild_id: int, username: str) -> Tuple[bool, int]:
        """
        添加或更新已歡迎的成員記錄
        
        Args:
            user_id: Discord 用戶 ID
            guild_id: Discord 伺服器 ID  
            username: 用戶名稱
            
        Returns:
            (是否需要發送歡迎訊息, 加入次數)
        """
        try:
            # 尋找現有記錄
            member = WelcomedMember.objects(user_id=user_id, guild_id=guild_id).first()
            
            if member:
                # 更新現有記錄
                member.join_count += 1
                member.username = username
                
                # 如果上次歡迎成功，重置重試相關欄位
                if member.welcome_status == 'success':
                    member.retry_count = 0
                    member.last_retry_at = None
                    member.welcome_status = 'pending'  # 新的加入需要重新歡迎
                
                member.save()
                
                # 如果之前歡迎成功，這次仍需要歡迎（因為用戶重新加入）
                need_welcome = True
                return need_welcome, member.join_count
            else:
                # 創建新記錄
                member = WelcomedMember(
                    user_id=user_id,
                    guild_id=guild_id,
                    username=username,
                    welcome_status='pending'
                )
                member.save()
                return True, 1
                
        except Exception as e:
            logger.error(f"Error adding/updating welcomed member: {e}")
            return False, 0

    def get_member_join_count(self, user_id: int, guild_id: int) -> int:
        """
        獲取成員的加入次數
        
        Args:
            user_id: Discord 用戶 ID
            guild_id: Discord 伺服器 ID
            
        Returns:
            加入次數
        """
        try:
            member = WelcomedMember.objects(user_id=user_id, guild_id=guild_id).first()
            return member.join_count if member else 0
        except Exception as e:
            logger.error(f"Error getting member join count: {e}")
            return 0

    def get_member_info(self, user_id: int, guild_id: int) -> Optional[Dict]:
        """
        獲取成員的完整資訊
        
        Args:
            user_id: Discord 用戶 ID
            guild_id: Discord 伺服器 ID
            
        Returns:
            成員資訊字典，如果不存在則返回 None
        """
        try:
            member = WelcomedMember.objects(user_id=user_id, guild_id=guild_id).first()
            
            if member:
                return {
                    'username': member.username,
                    'join_count': member.join_count,
                    'first_welcomed_at': member.first_welcomed_at,
                    'welcome_status': member.welcome_status,
                    'retry_count': member.retry_count,
                    'last_retry_at': member.last_retry_at
                }
            return None
        except Exception as e:
            logger.error(f"Error getting member info: {e}")
            return None

    def mark_welcome_success(self, user_id: int, guild_id: int):
        """
        標記歡迎訊息發送成功
        
        Args:
            user_id: Discord 用戶 ID
            guild_id: Discord 伺服器 ID
        """
        try:
            member = WelcomedMember.objects(user_id=user_id, guild_id=guild_id).first()
            if member:
                member.welcome_status = 'success'
                member.retry_count = 0
                member.last_retry_at = None
                member.save()
                logger.info(f"Marked welcome success for user {user_id} in guild {guild_id}")
        except Exception as e:
            logger.error(f"Error marking welcome success: {e}")

    def mark_welcome_failed(self, user_id: int, guild_id: int):
        """
        標記歡迎訊息發送失敗
        
        Args:
            user_id: Discord 用戶 ID
            guild_id: Discord 伺服器 ID
        """
        try:
            member = WelcomedMember.objects(user_id=user_id, guild_id=guild_id).first()
            if member:
                member.welcome_status = 'failed'
                member.retry_count += 1
                member.last_retry_at = datetime.utcnow()
                member.save()
                logger.info(f"Marked welcome failed for user {user_id} in guild {guild_id}, retry count: {member.retry_count}")
        except Exception as e:
            logger.error(f"Error marking welcome failed: {e}")

    def get_pending_welcomes(self, max_retry: int = 3, retry_interval_minutes: int = 5) -> List[Dict]:
        """
        獲取需要重試的歡迎記錄
        
        Args:
            max_retry: 最大重試次數
            retry_interval_minutes: 重試間隔（分鐘）
            
        Returns:
            需要重試的歡迎記錄列表
        """
        try:
            retry_cutoff = datetime.utcnow() - timedelta(minutes=retry_interval_minutes)
            
            # 查詢條件：
            # 1. 狀態為 pending 或 failed
            # 2. 重試次數小於最大值
            # 3. 沒有重試時間記錄 或 重試時間已過間隔
            query = (
                (Q(welcome_status='pending') | Q(welcome_status='failed')) &
                Q(retry_count__lt=max_retry) &
                (Q(last_retry_at__exists=False) | Q(last_retry_at__lte=retry_cutoff))
            )
            
            members = WelcomedMember.objects(query).order_by('last_retry_at')
            
            return [{
                'user_id': member.user_id,
                'guild_id': member.guild_id,
                'username': member.username,
                'retry_count': member.retry_count
            } for member in members]
            
        except Exception as e:
            logger.error(f"Error getting pending welcomes: {e}")
            return []

    def get_welcome_statistics(self, guild_id: int) -> Dict:
        """
        獲取歡迎統計資料
        
        Args:
            guild_id: Discord 伺服器 ID
            
        Returns:
            統計資料字典
        """
        try:
            total_members = WelcomedMember.objects(guild_id=guild_id).count()
            success_count = WelcomedMember.objects(guild_id=guild_id, welcome_status='success').count()
            pending_count = WelcomedMember.objects(guild_id=guild_id, welcome_status='pending').count()
            failed_count = WelcomedMember.objects(guild_id=guild_id, welcome_status='failed').count()
            
            return {
                'total_members': total_members,
                'success_count': success_count,
                'pending_count': pending_count,
                'failed_count': failed_count,
                'success_rate': round(success_count / total_members * 100, 2) if total_members > 0 else 0
            }
        except Exception as e:
            logger.error(f"Error getting welcome statistics: {e}")
            return {}

    def cleanup_old_records(self, days: int = 90):
        """
        清理舊記錄
        
        Args:
            days: 保留天數
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # 只刪除成功歡迎且超過保留期的記錄
            deleted_count = WelcomedMember.objects(
                welcome_status='success',
                first_welcomed_at__lt=cutoff_date
            ).delete()
            
            logger.info(f"Cleaned up {deleted_count} old welcome records older than {days} days")
            return deleted_count
        except Exception as e:
            logger.error(f"Error cleaning up old records: {e}")
            return 0

    def close(self):
        """
        關閉資料庫連接（MongoEngine 自動管理連接）
        """
        # MongoEngine 自動管理連接，不需要手動關閉
        pass 
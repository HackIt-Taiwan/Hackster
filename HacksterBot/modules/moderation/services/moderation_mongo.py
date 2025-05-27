"""
MongoDB-based moderation database management using MongoEngine.
Replaces the SQLite-based implementation with MongoDB.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from mongoengine import Q
from core.models import User, Violation, Mute
from config.settings import MUTE_DURATIONS

logger = logging.getLogger(__name__)


class ModerationMongo:
    """
    MongoDB-based implementation for moderation database operations.
    Uses MongoEngine for object-oriented database operations.
    """
    
    def __init__(self, config=None):
        """
        Initialize the MongoDB moderation manager.
        
        Args:
            config: Configuration object (optional)
        """
        self.config = config
        logger.info("ModerationMongo initialized")

    def add_violation(self, user_id: int, guild_id: int, content: Optional[str] = None, 
                      violation_categories: Optional[List[str]] = None, 
                      details: Optional[Dict] = None) -> str:
        """
        添加違規記錄
        
        Args:
            user_id: Discord 用戶 ID
            guild_id: Discord 伺服器 ID
            content: 違規內容
            violation_categories: 違規類別列表
            details: 額外詳細資訊
            
        Returns:
            創建的違規記錄 ID
        """
        try:
            # 確保用戶記錄存在
            user, created = User.objects.get_or_create(
                user_id=user_id,
                guild_id=guild_id,
                defaults={'last_violation': datetime.utcnow()}
            )
            
            if not created:
                user.last_violation = datetime.utcnow()
                user.save()
            
            # 創建違規記錄
            violation = Violation(
                user_id=user_id,
                guild_id=guild_id,
                content=content,
                violation_categories=violation_categories or [],
                details=details or {}
            )
            violation.save()
            
            logger.info(f"Added violation record {violation.id} for user {user_id} in guild {guild_id}")
            return str(violation.id)
            
        except Exception as e:
            logger.error(f"Error adding violation: {e}")
            raise

    def get_violation_count(self, user_id: int, guild_id: int) -> int:
        """
        獲取用戶在特定伺服器的違規次數
        
        Args:
            user_id: Discord 用戶 ID
            guild_id: Discord 伺服器 ID
            
        Returns:
            違規次數
        """
        try:
            count = Violation.objects(user_id=user_id, guild_id=guild_id).count()
            return count
        except Exception as e:
            logger.error(f"Error getting violation count: {e}")
            return 0

    def get_user_violations(self, user_id: int, guild_id: int, limit: int = 10) -> List[Dict]:
        """
        獲取用戶的違規記錄
        
        Args:
            user_id: Discord 用戶 ID
            guild_id: Discord 伺服器 ID
            limit: 返回記錄數量限制
            
        Returns:
            違規記錄列表
        """
        try:
            violations = Violation.objects(
                user_id=user_id, 
                guild_id=guild_id
            ).order_by('-created_at').limit(limit)
            
            return [{
                'id': str(violation.id),
                'content': violation.content,
                'violation_categories': violation.violation_categories,
                'details': violation.details,
                'created_at': violation.created_at
            } for violation in violations]
            
        except Exception as e:
            logger.error(f"Error getting user violations: {e}")
            return []

    def add_mute(self, user_id: int, guild_id: int, violation_count: int, 
                duration: Optional[timedelta] = None) -> str:
        """
        添加禁言記錄
        
        Args:
            user_id: Discord 用戶 ID
            guild_id: Discord 伺服器 ID
            violation_count: 當前違規次數
            duration: 禁言時長（如果為 None，則根據違規次數計算）
            
        Returns:
            創建的禁言記錄 ID
        """
        try:
            # 計算禁言時長
            if duration is None:
                duration = self.calculate_mute_duration(violation_count)
            
            # 計算過期時間
            duration_minutes = None
            expires_at = None
            if duration:
                duration_minutes = int(duration.total_seconds() / 60)
                expires_at = datetime.utcnow() + duration
            
            # 創建禁言記錄
            mute = Mute(
                user_id=user_id,
                guild_id=guild_id,
                violation_count=violation_count,
                duration_minutes=duration_minutes,
                expires_at=expires_at
            )
            mute.save()
            
            logger.info(f"Added mute record {mute.id} for user {user_id} in guild {guild_id}, "
                       f"duration: {duration_minutes} minutes")
            return str(mute.id)
            
        except Exception as e:
            logger.error(f"Error adding mute: {e}")
            raise

    def get_active_mute(self, user_id: int, guild_id: int) -> Optional[Dict]:
        """
        獲取用戶的活躍禁言記錄
        
        Args:
            user_id: Discord 用戶 ID
            guild_id: Discord 伺服器 ID
            
        Returns:
            活躍的禁言記錄，如果沒有則返回 None
        """
        try:
            mute = Mute.objects(
                user_id=user_id,
                guild_id=guild_id,
                is_active=True
            ).first()
            
            if mute:
                return {
                    'id': str(mute.id),
                    'violation_count': mute.violation_count,
                    'duration_minutes': mute.duration_minutes,
                    'started_at': mute.started_at,
                    'expires_at': mute.expires_at,
                    'is_active': mute.is_active
                }
            return None
            
        except Exception as e:
            logger.error(f"Error getting active mute: {e}")
            return None

    def deactivate_mute(self, user_id: int, guild_id: int) -> bool:
        """
        停用用戶的禁言
        
        Args:
            user_id: Discord 用戶 ID
            guild_id: Discord 伺服器 ID
            
        Returns:
            是否成功停用
        """
        try:
            mute = Mute.objects(
                user_id=user_id,
                guild_id=guild_id,
                is_active=True
            ).first()
            
            if mute:
                mute.is_active = False
                mute.deactivated_at = datetime.utcnow()
                mute.save()
                logger.info(f"Deactivated mute for user {user_id} in guild {guild_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error deactivating mute: {e}")
            return False

    def check_and_update_expired_mutes(self) -> List[Dict]:
        """
        檢查並更新過期的禁言記錄
        
        Returns:
            已過期的禁言記錄列表
        """
        try:
            now = datetime.utcnow()
            
            # 查找過期的活躍禁言
            expired_mutes = Mute.objects(
                is_active=True,
                expires_at__lte=now
            )
            
            expired_list = []
            for mute in expired_mutes:
                expired_list.append({
                    'id': str(mute.id),
                    'user_id': mute.user_id,
                    'guild_id': mute.guild_id,
                    'violation_count': mute.violation_count,
                    'expires_at': mute.expires_at
                })
                
                # 更新為非活躍狀態
                mute.is_active = False
                mute.deactivated_at = now
                mute.save()
            
            if expired_list:
                logger.info(f"Updated {len(expired_list)} expired mutes")
            
            return expired_list
            
        except Exception as e:
            logger.error(f"Error checking expired mutes: {e}")
            return []

    def calculate_mute_duration(self, violation_count: int) -> Optional[timedelta]:
        """
        根據違規次數計算禁言時長
        
        Args:
            violation_count: 違規次數
            
        Returns:
            禁言時長，如果不需要禁言則返回 None
        """
        if violation_count in MUTE_DURATIONS:
            minutes = MUTE_DURATIONS[violation_count]
            return timedelta(minutes=minutes)
        elif violation_count > max(MUTE_DURATIONS.keys()):
            # 超過預設次數，使用最高等級的禁言時長
            minutes = MUTE_DURATIONS[max(MUTE_DURATIONS.keys())]
            return timedelta(minutes=minutes)
        return None

    def get_moderation_statistics(self, guild_id: int, days: int = 30) -> Dict:
        """
        獲取審核統計資料
        
        Args:
            guild_id: Discord 伺服器 ID
            days: 統計天數
            
        Returns:
            統計資料字典
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            total_violations = Violation.objects(
                guild_id=guild_id,
                created_at__gte=cutoff_date
            ).count()
            
            total_mutes = Mute.objects(
                guild_id=guild_id,
                started_at__gte=cutoff_date
            ).count()
            
            active_mutes = Mute.objects(
                guild_id=guild_id,
                is_active=True
            ).count()
            
            # 違規類別統計
            violations = Violation.objects(
                guild_id=guild_id,
                created_at__gte=cutoff_date
            )
            
            category_counts = {}
            for violation in violations:
                for category in violation.violation_categories:
                    category_counts[category] = category_counts.get(category, 0) + 1
            
            return {
                'total_violations': total_violations,
                'total_mutes': total_mutes,
                'active_mutes': active_mutes,
                'category_counts': category_counts,
                'period_days': days
            }
            
        except Exception as e:
            logger.error(f"Error getting moderation statistics: {e}")
            return {}

    def cleanup_old_violations(self, days: int = 365):
        """
        清理舊的違規記錄
        
        Args:
            days: 保留天數
            
        Returns:
            刪除的記錄數量
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            deleted_count = Violation.objects(
                created_at__lt=cutoff_date
            ).delete()
            
            logger.info(f"Cleaned up {deleted_count} old violation records older than {days} days")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up old violations: {e}")
            return 0

    def get_top_violators(self, guild_id: int, limit: int = 10, days: int = 30) -> List[Dict]:
        """
        獲取最多違規的用戶列表
        
        Args:
            guild_id: Discord 伺服器 ID
            limit: 返回數量限制
            days: 統計天數
            
        Returns:
            違規用戶列表
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # 使用 MongoDB 聚合管道來統計
            pipeline = [
                {
                    '$match': {
                        'guild_id': guild_id,
                        'created_at': {'$gte': cutoff_date}
                    }
                },
                {
                    '$group': {
                        '_id': '$user_id',
                        'violation_count': {'$sum': 1},
                        'latest_violation': {'$max': '$created_at'}
                    }
                },
                {
                    '$sort': {'violation_count': -1}
                },
                {
                    '$limit': limit
                }
            ]
            
            results = Violation._get_collection().aggregate(pipeline)
            
            violators = []
            for result in results:
                # 獲取用戶資訊
                user = User.objects(
                    user_id=result['_id'],
                    guild_id=guild_id
                ).first()
                
                violators.append({
                    'user_id': result['_id'],
                    'username': user.username if user else None,
                    'violation_count': result['violation_count'],
                    'latest_violation': result['latest_violation']
                })
            
            return violators
            
        except Exception as e:
            logger.error(f"Error getting top violators: {e}")
            return []

    def close(self):
        """
        關閉資料庫連接（MongoEngine 自動管理連接）
        """
        # MongoEngine 自動管理連接，不需要手動關閉
        pass 
"""
MongoDB-based URL blacklist management using MongoEngine.
Replaces the JSON-based implementation with MongoDB.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from urllib.parse import urlparse
from mongoengine import Q
from core.models import URLBlacklist

logger = logging.getLogger(__name__)


class URLBlacklistMongo:
    """
    MongoDB-based implementation for URL blacklist management.
    Uses MongoEngine for object-oriented database operations.
    """
    
    def __init__(self, config=None):
        """
        Initialize the MongoDB URL blacklist manager.
        
        Args:
            config: Configuration object (optional)
        """
        self.config = config
        logger.info("URLBlacklistMongo initialized")

    def add_url(self, url: str, threat_level: float = 0.0, 
                threat_types: Optional[List[str]] = None, 
                update_if_exists: bool = True) -> bool:
        """
        添加 URL 到黑名單
        
        Args:
            url: 要添加的 URL
            threat_level: 威脅等級 (0.0-1.0)
            threat_types: 威脅類型列表
            update_if_exists: 如果 URL 已存在是否更新
            
        Returns:
            是否成功添加或更新
        """
        try:
            # 解析域名
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            if not domain:
                logger.warning(f"Invalid URL: {url}")
                return False
            
            # 檢查是否已存在
            existing = URLBlacklist.objects(url=url).first()
            
            if existing:
                if update_if_exists:
                    # 更新現有記錄
                    existing.threat_level = max(existing.threat_level, threat_level)
                    existing.threat_types = list(set(existing.threat_types + (threat_types or [])))
                    existing.last_updated = datetime.utcnow()
                    existing.detection_count += 1
                    existing.is_active = True
                    existing.save()
                    logger.info(f"Updated blacklist entry for URL: {url}")
                    return True
                else:
                    logger.info(f"URL already exists in blacklist: {url}")
                    return False
            else:
                # 創建新記錄
                blacklist_entry = URLBlacklist(
                    url=url,
                    domain=domain,
                    threat_level=threat_level,
                    threat_types=threat_types or [],
                    detection_count=1,
                    is_active=True
                )
                blacklist_entry.save()
                logger.info(f"Added new URL to blacklist: {url}")
                return True
                
        except Exception as e:
            logger.error(f"Error adding URL to blacklist: {e}")
            return False

    def is_url_blacklisted(self, url: str) -> bool:
        """
        檢查 URL 是否在黑名單中
        
        Args:
            url: 要檢查的 URL
            
        Returns:
            是否在黑名單中
        """
        try:
            entry = URLBlacklist.objects(url=url, is_active=True).first()
            return entry is not None
        except Exception as e:
            logger.error(f"Error checking URL blacklist: {e}")
            return False

    def is_domain_blacklisted(self, domain: str) -> bool:
        """
        檢查域名是否在黑名單中
        
        Args:
            domain: 要檢查的域名
            
        Returns:
            是否在黑名單中
        """
        try:
            domain = domain.lower()
            entry = URLBlacklist.objects(domain=domain, is_active=True).first()
            return entry is not None
        except Exception as e:
            logger.error(f"Error checking domain blacklist: {e}")
            return False

    def get_blacklisted_urls(self, domain: Optional[str] = None, 
                           threat_level_min: Optional[float] = None,
                           limit: int = 100) -> List[Dict]:
        """
        獲取黑名單 URL 列表
        
        Args:
            domain: 過濾特定域名
            threat_level_min: 最小威脅等級
            limit: 返回數量限制
            
        Returns:
            黑名單 URL 列表
        """
        try:
            query = Q(is_active=True)
            
            if domain:
                query &= Q(domain=domain.lower())
            
            if threat_level_min is not None:
                query &= Q(threat_level__gte=threat_level_min)
            
            entries = URLBlacklist.objects(query).order_by('-threat_level', '-last_updated').limit(limit)
            
            return [{
                'url': entry.url,
                'domain': entry.domain,
                'threat_level': entry.threat_level,
                'threat_types': entry.threat_types,
                'first_detected': entry.first_detected,
                'last_updated': entry.last_updated,
                'detection_count': entry.detection_count
            } for entry in entries]
            
        except Exception as e:
            logger.error(f"Error getting blacklisted URLs: {e}")
            return []

    def remove_url(self, url: str) -> bool:
        """
        從黑名單中移除 URL
        
        Args:
            url: 要移除的 URL
            
        Returns:
            是否成功移除
        """
        try:
            entry = URLBlacklist.objects(url=url).first()
            if entry:
                entry.is_active = False
                entry.last_updated = datetime.utcnow()
                entry.save()
                logger.info(f"Removed URL from blacklist: {url}")
                return True
            else:
                logger.warning(f"URL not found in blacklist: {url}")
                return False
        except Exception as e:
            logger.error(f"Error removing URL from blacklist: {e}")
            return False

    def get_threat_info(self, url: str) -> Optional[Dict]:
        """
        獲取 URL 的威脅資訊
        
        Args:
            url: 要查詢的 URL
            
        Returns:
            威脅資訊字典，如果不存在則返回 None
        """
        try:
            entry = URLBlacklist.objects(url=url, is_active=True).first()
            if entry:
                return {
                    'url': entry.url,
                    'domain': entry.domain,
                    'threat_level': entry.threat_level,
                    'threat_types': entry.threat_types,
                    'first_detected': entry.first_detected,
                    'last_updated': entry.last_updated,
                    'detection_count': entry.detection_count
                }
            return None
        except Exception as e:
            logger.error(f"Error getting threat info: {e}")
            return None

    def get_domains_by_threat_level(self, min_threat_level: float = 0.5) -> Set[str]:
        """
        獲取威脅等級高於指定值的域名集合
        
        Args:
            min_threat_level: 最小威脅等級
            
        Returns:
            域名集合
        """
        try:
            entries = URLBlacklist.objects(
                is_active=True,
                threat_level__gte=min_threat_level
            ).distinct('domain')
            
            return set(entries)
        except Exception as e:
            logger.error(f"Error getting domains by threat level: {e}")
            return set()

    def update_threat_level(self, url: str, threat_level: float, 
                           threat_types: Optional[List[str]] = None) -> bool:
        """
        更新 URL 的威脅等級
        
        Args:
            url: 要更新的 URL
            threat_level: 新的威脅等級
            threat_types: 新的威脅類型列表
            
        Returns:
            是否成功更新
        """
        try:
            entry = URLBlacklist.objects(url=url).first()
            if entry:
                entry.threat_level = threat_level
                if threat_types:
                    entry.threat_types = threat_types
                entry.last_updated = datetime.utcnow()
                entry.save()
                logger.info(f"Updated threat level for URL {url}: {threat_level}")
                return True
            else:
                logger.warning(f"URL not found for update: {url}")
                return False
        except Exception as e:
            logger.error(f"Error updating threat level: {e}")
            return False

    def get_statistics(self) -> Dict:
        """
        獲取黑名單統計資料
        
        Returns:
            統計資料字典
        """
        try:
            total_urls = URLBlacklist.objects(is_active=True).count()
            total_domains = len(URLBlacklist.objects(is_active=True).distinct('domain'))
            
            # 威脅等級分布
            high_threat = URLBlacklist.objects(is_active=True, threat_level__gte=0.8).count()
            medium_threat = URLBlacklist.objects(
                is_active=True, 
                threat_level__gte=0.5, 
                threat_level__lt=0.8
            ).count()
            low_threat = URLBlacklist.objects(
                is_active=True, 
                threat_level__lt=0.5
            ).count()
            
            # 威脅類型統計
            all_entries = URLBlacklist.objects(is_active=True)
            threat_type_counts = {}
            for entry in all_entries:
                for threat_type in entry.threat_types:
                    threat_type_counts[threat_type] = threat_type_counts.get(threat_type, 0) + 1
            
            return {
                'total_urls': total_urls,
                'total_domains': total_domains,
                'threat_distribution': {
                    'high': high_threat,
                    'medium': medium_threat,
                    'low': low_threat
                },
                'threat_type_counts': threat_type_counts
            }
            
        except Exception as e:
            logger.error(f"Error getting blacklist statistics: {e}")
            return {}

    def cleanup_old_entries(self, days: int = 365) -> int:
        """
        清理舊的黑名單記錄
        
        Args:
            days: 保留天數
            
        Returns:
            清理的記錄數量
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # 只清理低威脅等級且長時間未更新的記錄
            deleted_count = URLBlacklist.objects(
                is_active=True,
                threat_level__lt=0.3,
                last_updated__lt=cutoff_date
            ).update(is_active=False)
            
            logger.info(f"Cleaned up {deleted_count} old blacklist entries older than {days} days")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up old entries: {e}")
            return 0

    def bulk_add_urls(self, urls_data: List[Dict]) -> int:
        """
        批量添加 URL 到黑名單
        
        Args:
            urls_data: URL 資料列表，每個項目包含 url, threat_level, threat_types
            
        Returns:
            成功添加的數量
        """
        try:
            added_count = 0
            for url_data in urls_data:
                url = url_data.get('url')
                threat_level = url_data.get('threat_level', 0.0)
                threat_types = url_data.get('threat_types', [])
                
                if self.add_url(url, threat_level, threat_types):
                    added_count += 1
            
            logger.info(f"Bulk added {added_count} URLs to blacklist")
            return added_count
            
        except Exception as e:
            logger.error(f"Error in bulk add URLs: {e}")
            return 0

    def export_blacklist(self) -> List[Dict]:
        """
        匯出完整黑名單
        
        Returns:
            完整黑名單資料
        """
        try:
            entries = URLBlacklist.objects(is_active=True).order_by('-threat_level')
            
            return [{
                'url': entry.url,
                'domain': entry.domain,
                'threat_level': entry.threat_level,
                'threat_types': entry.threat_types,
                'first_detected': entry.first_detected.isoformat(),
                'last_updated': entry.last_updated.isoformat(),
                'detection_count': entry.detection_count
            } for entry in entries]
            
        except Exception as e:
            logger.error(f"Error exporting blacklist: {e}")
            return []

    def close(self):
        """
        關閉資料庫連接（MongoEngine 自動管理連接）
        """
        # MongoEngine 自動管理連接，不需要手動關閉
        pass 
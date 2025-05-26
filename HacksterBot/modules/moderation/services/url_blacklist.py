"""
URL blacklist management service.

This module provides functionality to manage a blacklist of known malicious URLs
for fast lookup and automatic updating based on detection results.
"""
import json
import logging
import threading
import time
from typing import Dict, List, Optional, Set, Any
from datetime import datetime, timedelta
from pathlib import Path
import urllib.parse
import hashlib

logger = logging.getLogger(__name__)

class URLBlacklist:
    """Manages a blacklist of known malicious URLs for fast lookup."""
    
    def __init__(self, blacklist_file: str):
        """
        Initialize the URL blacklist manager.
        
        Args:
            blacklist_file: Path to the JSON file storing the blacklist
        """
        self.blacklist_file = Path(blacklist_file)
        self.blacklist_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Thread-safe lock for file operations
        self._lock = threading.RLock()
        
        # In-memory cache of blacklisted URLs
        self._url_cache: Dict[str, Dict] = {}
        self._domain_cache: Dict[str, Dict] = {}
        self._shortened_url_cache: Dict[str, str] = {}  # Maps shortened URL to final URL
        
        # Load existing blacklist
        self._load_blacklist()
        
        logger.info(f"URL blacklist initialized with {len(self._url_cache)} URLs and {len(self._domain_cache)} domains")
    
    def _load_blacklist(self):
        """Load blacklist data from file."""
        try:
            if self.blacklist_file.exists():
                with open(self.blacklist_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                self._url_cache = data.get('urls', {})
                self._domain_cache = data.get('domains', {})
                self._shortened_url_cache = data.get('shortened_urls', {})
                
                logger.info(f"Loaded blacklist: {len(self._url_cache)} URLs, {len(self._domain_cache)} domains, {len(self._shortened_url_cache)} shortened URLs")
            else:
                # Create empty blacklist
                self._url_cache = {}
                self._domain_cache = {}
                self._shortened_url_cache = {}
                self._save_blacklist()
                logger.info("Created new empty blacklist file")
                
        except Exception as e:
            logger.error(f"Error loading blacklist: {e}")
            # Initialize with empty cache if loading fails
            self._url_cache = {}
            self._domain_cache = {}
            self._shortened_url_cache = {}
    
    def _save_blacklist(self):
        """Save blacklist data to file."""
        try:
            with self._lock:
                data = {
                    'urls': self._url_cache,
                    'domains': self._domain_cache,
                    'shortened_urls': self._shortened_url_cache,
                    'last_updated': datetime.now().isoformat()
                }
                
                # Write to temporary file first, then rename for atomic operation
                temp_file = self.blacklist_file.with_suffix('.tmp')
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                # Atomic rename
                temp_file.replace(self.blacklist_file)
                
                logger.debug("Blacklist saved successfully")
                
        except Exception as e:
            logger.error(f"Error saving blacklist: {e}")
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL for consistent storage and lookup."""
        try:
            # Parse and rebuild URL to normalize it
            parsed = urllib.parse.urlparse(url.lower().strip())
            
            # Remove www. prefix
            netloc = parsed.netloc
            if netloc.startswith('www.'):
                netloc = netloc[4:]
            
            # Rebuild normalized URL
            normalized = urllib.parse.urlunparse((
                parsed.scheme,
                netloc,
                parsed.path.rstrip('/'),
                parsed.params,
                parsed.query,
                ''  # Remove fragment
            ))
            
            return normalized
            
        except Exception:
            # If normalization fails, return the original URL
            return url.lower().strip()
    
    def _get_domain_from_url(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urllib.parse.urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return ""
    
    def _create_url_hash(self, url: str) -> str:
        """Create a hash of the URL for efficient storage."""
        return hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
    
    def is_blacklisted(self, url: str) -> Optional[Dict]:
        """
        Check if a URL is in the blacklist.
        
        Args:
            url: The URL to check
            
        Returns:
            Dictionary with blacklist information if found, None otherwise
        """
        if not url:
            return None
            
        normalized_url = self._normalize_url(url)
        domain = self._get_domain_from_url(normalized_url)
        
        with self._lock:
            # Check exact URL match
            if normalized_url in self._url_cache:
                return self._url_cache[normalized_url]
            
            # Check if this is a shortened URL we've seen before
            if url in self._shortened_url_cache:
                final_url = self._shortened_url_cache[url]
                normalized_final = self._normalize_url(final_url)
                if normalized_final in self._url_cache:
                    return self._url_cache[normalized_final]
            
            # Check domain blacklist
            if domain and domain in self._domain_cache:
                return self._domain_cache[domain]
        
        return None
    
    def add_url(self, url: str, reason: str, threat_types: List[str], severity: int = 5, source: str = "manual"):
        """
        Add a URL to the blacklist.
        
        Args:
            url: The URL to blacklist
            reason: Reason for blacklisting
            threat_types: List of threat types
            severity: Severity level (1-10)
            source: Source of the blacklist entry
        """
        if not url:
            return
            
        normalized_url = self._normalize_url(url)
        
        blacklist_entry = {
            'url': normalized_url,
            'reason': reason,
            'threat_types': threat_types,
            'severity': severity,
            'source': source,
            'blacklisted_at': datetime.now().isoformat(),
            'last_seen': datetime.now().isoformat()
        }
        
        with self._lock:
            self._url_cache[normalized_url] = blacklist_entry
            self._save_blacklist()
        
        logger.info(f"Added URL to blacklist: {normalized_url} (reason: {reason})")
    
    def add_domain(self, domain: str, reason: str, threat_types: List[str], severity: int = 5, source: str = "manual"):
        """
        Add a domain to the blacklist.
        
        Args:
            domain: The domain to blacklist
            reason: Reason for blacklisting
            threat_types: List of threat types
            severity: Severity level (1-10)
            source: Source of the blacklist entry
        """
        if not domain:
            return
            
        domain = domain.lower().strip()
        if domain.startswith('www.'):
            domain = domain[4:]
        
        blacklist_entry = {
            'domain': domain,
            'reason': reason,
            'threat_types': threat_types,
            'severity': severity,
            'source': source,
            'blacklisted_at': datetime.now().isoformat(),
            'last_seen': datetime.now().isoformat()
        }
        
        with self._lock:
            self._domain_cache[domain] = blacklist_entry
            self._save_blacklist()
        
        logger.info(f"Added domain to blacklist: {domain} (reason: {reason})")
    
    def add_shortened_url(self, shortened_url: str, final_url: str):
        """
        Add a mapping from shortened URL to final URL.
        
        Args:
            shortened_url: The shortened URL
            final_url: The final expanded URL
        """
        if not shortened_url or not final_url or shortened_url == final_url:
            return
            
        with self._lock:
            self._shortened_url_cache[shortened_url] = final_url
            # Save periodically or when cache gets large
            if len(self._shortened_url_cache) % 50 == 0:
                self._save_blacklist()
        
        logger.debug(f"Added shortened URL mapping: {shortened_url} -> {final_url}")
    
    def add_unsafe_result(self, url: str, safety_result: Dict, original_url: str = None, blacklist_domain: str = "auto-detected"):
        """
        Add a URL to blacklist based on safety check results.
        
        Args:
            url: The URL that was found to be unsafe
            safety_result: The safety check result dictionary
            original_url: Original URL if this was unshortened
            blacklist_domain: Domain/source for the blacklist entry
        """
        if not url or not safety_result.get('is_unsafe'):
            return
            
        threat_types = safety_result.get('threat_types', ['UNKNOWN'])
        severity = safety_result.get('severity', 5)
        reason = safety_result.get('message', 'Detected as unsafe by security scan')
        
        # Add the main URL
        self.add_url(
            url=url,
            reason=f"{reason} (via {blacklist_domain})",
            threat_types=threat_types,
            severity=severity,
            source=blacklist_domain
        )
        
        # If this was an unshortened URL, also add the mapping
        if original_url and original_url != url:
            self.add_shortened_url(original_url, url)
    
    def remove_url(self, url: str) -> bool:
        """
        Remove a URL from the blacklist.
        
        Args:
            url: The URL to remove
            
        Returns:
            True if URL was removed, False if not found
        """
        if not url:
            return False
            
        normalized_url = self._normalize_url(url)
        
        with self._lock:
            if normalized_url in self._url_cache:
                del self._url_cache[normalized_url]
                self._save_blacklist()
                logger.info(f"Removed URL from blacklist: {normalized_url}")
                return True
        
        return False
    
    def remove_domain(self, domain: str) -> bool:
        """
        Remove a domain from the blacklist.
        
        Args:
            domain: The domain to remove
            
        Returns:
            True if domain was removed, False if not found
        """
        if not domain:
            return False
            
        domain = domain.lower().strip()
        if domain.startswith('www.'):
            domain = domain[4:]
        
        with self._lock:
            if domain in self._domain_cache:
                del self._domain_cache[domain]
                self._save_blacklist()
                logger.info(f"Removed domain from blacklist: {domain}")
                return True
        
        return False
    
    def cleanup_old_entries(self, days: int = 30):
        """
        Remove blacklist entries older than specified days.
        
        Args:
            days: Number of days after which to remove entries
        """
        if days <= 0:
            return
            
        cutoff_date = datetime.now() - timedelta(days=days)
        removed_urls = 0
        removed_domains = 0
        
        with self._lock:
            # Clean up URLs
            urls_to_remove = []
            for url, entry in self._url_cache.items():
                try:
                    blacklisted_at = datetime.fromisoformat(entry['blacklisted_at'])
                    if blacklisted_at < cutoff_date:
                        urls_to_remove.append(url)
                except (KeyError, ValueError):
                    # Remove entries with invalid dates
                    urls_to_remove.append(url)
            
            for url in urls_to_remove:
                del self._url_cache[url]
                removed_urls += 1
            
            # Clean up domains
            domains_to_remove = []
            for domain, entry in self._domain_cache.items():
                try:
                    blacklisted_at = datetime.fromisoformat(entry['blacklisted_at'])
                    if blacklisted_at < cutoff_date:
                        domains_to_remove.append(domain)
                except (KeyError, ValueError):
                    # Remove entries with invalid dates
                    domains_to_remove.append(domain)
            
            for domain in domains_to_remove:
                del self._domain_cache[domain]
                removed_domains += 1
            
            if removed_urls > 0 or removed_domains > 0:
                self._save_blacklist()
        
        logger.info(f"Cleaned up {removed_urls} URLs and {removed_domains} domains older than {days} days")
    
    def get_stats(self) -> Dict[str, int]:
        """Get blacklist statistics."""
        with self._lock:
            return {
                'total_urls': len(self._url_cache),
                'total_domains': len(self._domain_cache),
                'total_shortened_mappings': len(self._shortened_url_cache)
            }
    
    def close(self):
        """Save and cleanup resources."""
        try:
            self._save_blacklist()
            logger.info("URL blacklist closed and saved")
        except Exception as e:
            logger.error(f"Error closing URL blacklist: {e}") 
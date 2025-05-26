"""
URL safety checking service using multiple security APIs and analysis methods.

This module provides comprehensive URL safety checking using:
1. VirusTotal API for threat intelligence
2. URLVoid API for additional verification  
3. URL unshortening to check final destinations
4. Local blacklist for fast lookup
5. Heuristic analysis for suspicious patterns
"""
import asyncio
import aiohttp
import json
import logging
import re
import time
import hashlib
import base64
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin
import urllib.parse

from config.settings import (
    URL_SAFETY_CHECK_API,
    URL_SAFETY_API_KEY,
    URL_SAFETY_THRESHOLD,
    URL_SAFETY_MAX_RETRIES,
    URL_SAFETY_RETRY_DELAY,
    URL_SAFETY_REQUEST_TIMEOUT,
    URL_SAFETY_MAX_URLS,
    URL_BLACKLIST_ENABLED,
    URL_BLACKLIST_FILE,
    URL_BLACKLIST_AUTO_DOMAIN,
    VIRUSTOTAL_RATE_LIMIT_REQUESTS_PER_MINUTE
)

from .url_unshortener import URLUnshortener
from .url_blacklist import URLBlacklist

logger = logging.getLogger(__name__)

# URL pattern for detection
URL_PATTERN = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w\.-]*(?:\?[-\w%&=.]*)?(?:#[-\w]*)?'

# URL safety checking relies purely on API and crawling - no hardcoded lists

class URLSafetyChecker:
    """Comprehensive URL safety checker using multiple methods."""
    
    def __init__(self, config=None):
        """Initialize the URL safety checker with all required services."""
        self.enabled = True
        self.api_provider = URL_SAFETY_CHECK_API
        self.api_key = URL_SAFETY_API_KEY
        self.threshold = URL_SAFETY_THRESHOLD
        self.max_retries = URL_SAFETY_MAX_RETRIES
        self.retry_delay = URL_SAFETY_RETRY_DELAY
        self.request_timeout = URL_SAFETY_REQUEST_TIMEOUT
        self.max_urls = URL_SAFETY_MAX_URLS
        
        # Initialize URL unshortener
        self.url_unshortener = URLUnshortener()
        
        # Initialize blacklist if enabled
        self.blacklist = None
        if URL_BLACKLIST_ENABLED:
            self.blacklist = URLBlacklist(URL_BLACKLIST_FILE)
        
        # Rate limiting for APIs
        self.api_calls = []
        self.rate_limit = VIRUSTOTAL_RATE_LIMIT_REQUESTS_PER_MINUTE
        
        # Session for HTTP requests
        self.session = None
        
        logger.info(f"URL safety checker initialized. Provider: {self.api_provider}, Blacklist: {URL_BLACKLIST_ENABLED}")
    
    async def _init_session(self):
        """Initialize HTTP session if not already done."""
        if self.session is None:
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    
    def _rate_limit_check(self) -> bool:
        """Check if we can make an API call without exceeding rate limits."""
        now = time.time()
        
        # Remove old timestamps (older than 1 minute)
        self.api_calls = [call_time for call_time in self.api_calls if now - call_time < 60]
        
        # Check if we can make a new call
        if len(self.api_calls) >= self.rate_limit:
            return False
            
        # Add current timestamp
        self.api_calls.append(now)
        return True
    
    def _get_domain_from_url(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return ""
    
    async def _check_domain_reputation(self, domain: str) -> Dict:
        """Check domain reputation using API only - no hardcoded lists."""
        if not domain:
            return {
                "success": False,
                "error": "Empty domain provided"
            }
        
        # Use VirusTotal domain API to check domain reputation
        if not self.api_key:
            return {
                "success": False,
                "error": "API key not configured for domain check"
            }
        
        if not self._rate_limit_check():
            return {
                "success": False,
                "error": "Rate limit exceeded for domain check"
            }
        
        await self._init_session()
        
        headers = {
            "x-apikey": self.api_key,
            "User-Agent": "URLSafetyChecker/1.0"
        }
        
        vt_domain_url = f"https://www.virustotal.com/api/v3/domains/{domain}"
        
        try:
            async with self.session.get(vt_domain_url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_domain_response(data, domain)
                elif response.status == 404:
                    # Domain not found in VirusTotal - not necessarily bad
                    return {
                        "success": True,
                        "is_unsafe": False,
                        "message": "Domain not found in threat database",
                        "method": "domain_api"
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Domain API error: {response.status}"
                    }
        except Exception as e:
            logger.error(f"Domain reputation check failed for {domain}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _parse_domain_response(self, data: Dict, domain: str) -> Dict:
        """Parse VirusTotal domain API response."""
        try:
            attributes = data.get('data', {}).get('attributes', {})
            stats = attributes.get('last_analysis_stats', {})
            
            malicious = stats.get('malicious', 0)
            suspicious = stats.get('suspicious', 0)
            total_engines = stats.get('harmless', 0) + stats.get('malicious', 0) + stats.get('suspicious', 0) + stats.get('undetected', 0)
            
            # Calculate threat score
            threat_score = 0
            if total_engines > 0:
                threat_score = (malicious + suspicious * 0.5) / total_engines
            
            # Get categories
            categories = attributes.get('categories', {})
            threat_types = list(set(cat.upper() for cat in categories.values() if cat))
            
            is_unsafe = threat_score >= self.threshold or malicious > 0
            
            return {
                "success": True,
                "is_unsafe": is_unsafe,
                "threat_score": round(threat_score, 3),
                "malicious_count": malicious,
                "suspicious_count": suspicious,
                "total_engines": total_engines,
                "threat_types": threat_types,
                "severity": self._calculate_severity(threat_score, malicious, suspicious),
                "message": self._generate_threat_message(threat_score, malicious, suspicious, threat_types),
                "method": "domain_api"
            }
            
        except Exception as e:
            logger.error(f"Error parsing domain response: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to parse domain response: {str(e)}"
            }
    
    async def _check_virustotal(self, url: str) -> Dict:
        """Check URL using VirusTotal API."""
        if not self.api_key:
            return {
                "success": False,
                "error": "VirusTotal API key not configured"
            }
        
        if not self._rate_limit_check():
            return {
                "success": False,
                "error": "Rate limit exceeded"
            }
        
        await self._init_session()
        
        # URL encode the URL for VirusTotal
        url_id = base64.urlsafe_b64encode(url.encode()).decode().strip("=")
        
        headers = {
            "x-apikey": self.api_key,
            "User-Agent": "URLSafetyChecker/1.0"
        }
        
        vt_url = f"https://www.virustotal.com/api/v3/urls/{url_id}"
        
        try:
            # First try to get existing analysis
            async with self.session.get(vt_url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_virustotal_response(data, url)
                elif response.status == 404:
                    # URL not found, submit for analysis
                    return await self._submit_url_to_virustotal(url, headers)
                else:
                    error_text = await response.text()
                    logger.error(f"VirusTotal API error {response.status}: {error_text}")
                    return {
                        "success": False,
                        "error": f"VirusTotal API error: {response.status}"
                    }
                    
        except asyncio.TimeoutError:
            logger.error(f"VirusTotal request timeout for URL: {url}")
            return {
                "success": False,
                "error": "Request timeout"
            }
        except Exception as e:
            logger.error(f"VirusTotal request failed for URL {url}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _submit_url_to_virustotal(self, url: str, headers: Dict) -> Dict:
        """Submit URL to VirusTotal for analysis."""
        submit_url = "https://www.virustotal.com/api/v3/urls"
        
        data = aiohttp.FormData()
        data.add_field('url', url)
        
        try:
            async with self.session.post(submit_url, headers=headers, data=data) as response:
                if response.status == 200:
                    submission_data = await response.json()
                    analysis_id = submission_data.get('data', {}).get('id')
                    
                    if analysis_id:
                        # Wait a bit for analysis to complete
                        await asyncio.sleep(5)
                        return await self._get_virustotal_analysis(analysis_id, headers, url)
                    else:
                        return {
                            "success": False,
                            "error": "Failed to get analysis ID from VirusTotal"
                        }
                else:
                    error_text = await response.text()
                    logger.error(f"VirusTotal submission error {response.status}: {error_text}")
                    return {
                        "success": False,
                        "error": f"VirusTotal submission failed: {response.status}"
                    }
                    
        except Exception as e:
            logger.error(f"VirusTotal submission failed for URL {url}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _get_virustotal_analysis(self, analysis_id: str, headers: Dict, original_url: str) -> Dict:
        """Get analysis results from VirusTotal."""
        analysis_url = f"https://www.virustotal.com/api/v3/analyses/{analysis_id}"
        
        # Try multiple times as analysis might take time
        for attempt in range(3):
            try:
                async with self.session.get(analysis_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        analysis_status = data.get('data', {}).get('attributes', {}).get('status')
                        
                        if analysis_status == 'completed':
                            return self._parse_virustotal_response(data, original_url)
                        elif analysis_status in ['queued', 'running']:
                            # Wait longer and try again
                            await asyncio.sleep(10)
                            continue
                        else:
                            return {
                                "success": False,
                                "error": f"Analysis failed with status: {analysis_status}"
                            }
                    else:
                        error_text = await response.text()
                        logger.error(f"VirusTotal analysis error {response.status}: {error_text}")
                        return {
                            "success": False,
                            "error": f"Analysis retrieval failed: {response.status}"
                        }
                        
            except Exception as e:
                logger.error(f"VirusTotal analysis retrieval failed: {str(e)}")
                if attempt == 2:  # Last attempt
                    return {
                        "success": False,
                        "error": str(e)
                    }
                await asyncio.sleep(5)
        
        return {
            "success": False,
            "error": "Analysis timeout"
        }
    
    def _parse_virustotal_response(self, data: Dict, url: str) -> Dict:
        """Parse VirusTotal API response."""
        try:
            attributes = data.get('data', {}).get('attributes', {})
            stats = attributes.get('stats', {})
            
            malicious = stats.get('malicious', 0)
            suspicious = stats.get('suspicious', 0)
            total_engines = stats.get('harmless', 0) + stats.get('malicious', 0) + stats.get('suspicious', 0) + stats.get('undetected', 0)
            
            # Calculate threat score
            threat_score = 0
            if total_engines > 0:
                threat_score = (malicious + suspicious * 0.5) / total_engines
            
            # Get threat categories
            threat_types = []
            if malicious > 0:
                categories = attributes.get('categories', {})
                for engine, category in categories.items():
                    if category and category not in threat_types:
                        threat_types.append(category.upper())
            
            # Determine if URL is unsafe
            is_unsafe = threat_score >= self.threshold
            
            # Get additional information
            last_analysis_date = attributes.get('last_analysis_date')
            if last_analysis_date:
                last_analysis = datetime.fromtimestamp(last_analysis_date).isoformat()
            else:
                last_analysis = None
            
            return {
                "success": True,
                "is_unsafe": is_unsafe,
                "threat_score": round(threat_score, 3),
                "malicious_count": malicious,
                "suspicious_count": suspicious,
                "total_engines": total_engines,
                "threat_types": threat_types if threat_types else ["UNKNOWN"] if is_unsafe else [],
                "last_analysis": last_analysis,
                "severity": self._calculate_severity(threat_score, malicious, suspicious),
                "message": self._generate_threat_message(threat_score, malicious, suspicious, threat_types),
                "provider": "virustotal"
            }
            
        except Exception as e:
            logger.error(f"Error parsing VirusTotal response: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to parse VirusTotal response: {str(e)}"
            }
    
    def _calculate_severity(self, threat_score: float, malicious: int, suspicious: int) -> int:
        """Calculate severity level (1-10) based on threat indicators."""
        if malicious >= 5:
            return 9  # Very high
        elif malicious >= 3:
            return 8  # High
        elif malicious >= 1:
            return 7  # Medium-high
        elif suspicious >= 5:
            return 6  # Medium
        elif suspicious >= 3:
            return 5  # Medium-low
        elif suspicious >= 1:
            return 4  # Low-medium
        elif threat_score >= self.threshold:
            return 3  # Low
        else:
            return 1  # Very low
    
    def _generate_threat_message(self, threat_score: float, malicious: int, suspicious: int, threat_types: List[str]) -> str:
        """Generate human-readable threat message."""
        if malicious >= 5:
            return f"High-risk URL detected by {malicious} security engines"
        elif malicious >= 1:
            message = f"Malicious content detected by {malicious} security engine(s)"
            if suspicious > 0:
                message += f" and flagged as suspicious by {suspicious} additional engine(s)"
            return message
        elif suspicious >= 3:
            return f"Suspicious content flagged by {suspicious} security engines"
        elif suspicious >= 1:
            return f"Potentially suspicious content detected"
        elif threat_score >= self.threshold:
            return f"URL flagged with threat score: {threat_score:.2%}"
        else:
            return "URL appears safe"
    
    async def _check_multiple_apis(self, url: str) -> Dict:
        """Check URL using multiple API providers for better accuracy."""
        results = []
        
        # VirusTotal URL check
        if self.api_provider in ['virustotal', 'all'] and self.api_key:
            vt_result = await self._check_virustotal(url)
            if vt_result.get('success'):
                results.append(vt_result)
        
        # Also check domain reputation via API
        if self.api_key:
            domain = self._get_domain_from_url(url)
            if domain:
                domain_result = await self._check_domain_reputation(domain)
                if domain_result.get('success'):
                    results.append(domain_result)
        
        # If we have results, combine them
        if results:
            return self._combine_api_results(results, url)
        else:
            # No API available or all failed - return safe by default
            return {
                "success": True,
                "is_unsafe": False,
                "threat_score": 0.0,
                "threat_types": [],
                "severity": 1,
                "message": "No API available for checking, URL not blocked",
                "method": "no_api"
            }
    
    def _combine_api_results(self, results: List[Dict], url: str) -> Dict:
        """Combine results from multiple API providers."""
        if not results:
            return {"success": False, "error": "No API results available"}
        
        # If only one result, return it
        if len(results) == 1:
            return results[0]
        
        # Combine multiple results
        total_threat_score = sum(r.get('threat_score', 0) for r in results)
        avg_threat_score = total_threat_score / len(results)
        
        total_malicious = sum(r.get('malicious_count', 0) for r in results)
        total_suspicious = sum(r.get('suspicious_count', 0) for r in results)
        
        combined_threat_types = set()
        providers = []
        
        for result in results:
            combined_threat_types.update(result.get('threat_types', []))
            providers.append(result.get('provider', 'unknown'))
        
        is_unsafe = avg_threat_score >= self.threshold or total_malicious > 0
        
        return {
            "success": True,
            "is_unsafe": is_unsafe,
            "threat_score": round(avg_threat_score, 3),
            "malicious_count": total_malicious,
            "suspicious_count": total_suspicious,
            "threat_types": list(combined_threat_types),
            "severity": self._calculate_severity(avg_threat_score, total_malicious, total_suspicious),
            "message": self._generate_threat_message(avg_threat_score, total_malicious, total_suspicious, list(combined_threat_types)),
            "providers": providers
        }
    

    
    async def extract_urls(self, text: str) -> List[str]:
        """Extract all URLs from text content."""
        if not text:
            return []
            
        # Find all URLs in the text
        urls = re.findall(URL_PATTERN, text)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_urls = [url for url in urls if not (url in seen or seen.add(url))]
        
        # Limit number of URLs to process
        if len(unique_urls) > self.max_urls:
            logger.warning(f"Too many URLs ({len(unique_urls)}), limiting to {self.max_urls}")
            unique_urls = unique_urls[:self.max_urls]
        
        logger.info(f"Extracted {len(unique_urls)} unique URLs from text")
        return unique_urls
    
    async def check_url(self, url: str) -> Tuple[bool, Dict]:
        """
        Check a single URL for safety.
        
        Args:
            url: The URL to check
            
        Returns:
            Tuple of (is_unsafe, result_dict)
        """
        result = {
            "url": url,
            "is_unsafe": False,
            "check_time": datetime.now().isoformat(),
            "message": "URL appears safe",
            "threat_types": [],
            "severity": 1,
            "method": "combined"
        }
        
        if not url:
            result.update({
                "is_unsafe": False,
                "message": "Empty URL provided",
                "error": "Empty URL"
            })
            return False, result
        
        try:
            # Ensure URL has a scheme
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
                result["url"] = url
            
            logger.info(f"Checking URL safety: {url}")
            
            # Step 1: Check blacklist first (fastest)
            if self.blacklist:
                blacklist_result = self.blacklist.is_blacklisted(url)
                if blacklist_result:
                    result.update({
                        "is_unsafe": True,
                        "message": f"URL in blacklist: {blacklist_result.get('reason', 'No reason provided')}",
                        "threat_types": blacklist_result.get('threat_types', ['BLACKLISTED']),
                        "severity": blacklist_result.get('severity', 8),
                        "method": "blacklist",
                        "blacklist_info": blacklist_result
                    })
                    logger.warning(f"URL found in blacklist: {url}")
                    return True, result
            
            # Step 2: Unshorten URL if needed
            unshorten_result = None
            final_url = url
            if self.url_unshortener.is_shortened_url(url):
                logger.info(f"Detected shortened URL, expanding: {url}")
                unshorten_result = await self.url_unshortener.unshorten_url(url)
                if unshorten_result.get('success') and unshorten_result.get('final_url') != url:
                    final_url = unshorten_result['final_url']
                    result["unshortened_url"] = final_url
                    result["unshorten_info"] = unshorten_result
                    logger.info(f"URL unshortened: {url} -> {final_url}")
                    
                    # Check blacklist again for the final URL
                    if self.blacklist:
                        blacklist_result = self.blacklist.is_blacklisted(final_url)
                        if blacklist_result:
                            result.update({
                                "is_unsafe": True,
                                "message": f"Final URL in blacklist: {blacklist_result.get('reason', 'No reason provided')}",
                                "threat_types": blacklist_result.get('threat_types', ['BLACKLISTED']),
                                "severity": blacklist_result.get('severity', 8),
                                "method": "blacklist",
                                "blacklist_info": blacklist_result
                            })
                            logger.warning(f"Final URL found in blacklist: {final_url}")
                            return True, result
            
            # Step 3: API-based security check
            safety_result = await self._check_multiple_apis(final_url)
            
            if safety_result.get('success'):
                # Update result with safety check information
                result.update({
                    "is_unsafe": safety_result.get('is_unsafe', False),
                    "message": safety_result.get('message', 'Check completed'),
                    "threat_types": safety_result.get('threat_types', []),
                    "severity": safety_result.get('severity', 1),
                    "threat_score": safety_result.get('threat_score', 0.0),
                    "method": safety_result.get('method', 'api'),
                    "api_info": safety_result
                })
                
                # Add to blacklist if unsafe
                if safety_result.get('is_unsafe') and self.blacklist:
                    self.blacklist.add_unsafe_result(
                        url=final_url,
                        safety_result=safety_result,
                        original_url=url if url != final_url else None,
                        blacklist_domain=URL_BLACKLIST_AUTO_DOMAIN
                    )
                    logger.info(f"Added unsafe URL to blacklist: {final_url}")
            else:
                # API check failed, use error information
                result.update({
                    "message": f"Safety check failed: {safety_result.get('error', 'Unknown error')}",
                    "error": safety_result.get('error'),
                    "method": "failed"
                })
            
            logger.info(f"URL safety check completed: {url} -> unsafe: {result['is_unsafe']}")
            return result['is_unsafe'], result
            
        except Exception as e:
            logger.error(f"Error checking URL safety {url}: {str(e)}")
            result.update({
                "is_unsafe": False,  # Don't block on errors
                "message": f"Error checking URL: {str(e)}",
                "error": str(e),
                "method": "error"
            })
            return False, result
    
    async def check_urls(self, urls: List[str]) -> Tuple[bool, Dict]:
        """
        Check multiple URLs for safety.
        
        Args:
            urls: List of URLs to check
            
        Returns:
            Tuple of (has_unsafe_urls, results_dict)
        """
        if not urls:
            return False, {}
            
        logger.info(f"Checking {len(urls)} URLs for safety")
        
        # Check URLs in parallel with some concurrency control
        semaphore = asyncio.Semaphore(3)  # Limit concurrent checks
        
        async def check_single_url(url):
            async with semaphore:
                return await self.check_url(url)
        
        # Execute all checks
        tasks = [check_single_url(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        has_unsafe = False
        url_results = {}
        
        for i, result in enumerate(results):
            url = urls[i]
            if isinstance(result, Exception):
                logger.error(f"Exception checking URL {url}: {str(result)}")
                url_results[url] = {
                    "url": url,
                    "is_unsafe": False,
                    "error": str(result),
                    "check_time": datetime.now().isoformat()
                }
            else:
                is_unsafe, url_result = result
                url_results[url] = url_result
                if is_unsafe:
                    has_unsafe = True
        
        logger.info(f"URL safety check completed. Unsafe URLs found: {has_unsafe}")
        return has_unsafe, url_results
    
    async def close(self):
        """Clean up resources."""
        if self.session:
            await self.session.close()
            self.session = None
        
        if hasattr(self.url_unshortener, 'close'):
            self.url_unshortener.close()
        
        if self.blacklist and hasattr(self.blacklist, 'close'):
            self.blacklist.close()
        
        logger.info("URL safety checker closed")
    
    def __del__(self):
        """Cleanup on deletion."""
        if hasattr(self, 'session') and self.session and not self.session.closed:
            logger.warning("URLSafetyChecker was deleted without calling close()") 
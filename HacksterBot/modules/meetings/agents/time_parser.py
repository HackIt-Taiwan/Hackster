"""
Time parser agent for natural language meeting scheduling.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import time
import pytz
from pydantic_ai import Agent
from pydantic_ai.models import Model
from core.models import MeetingParseLog
from modules.ai.services.ai_select import get_agent


class TimeParserAgent:
    """Agent for parsing natural language time expressions."""
    
    def __init__(self, bot, config):
        self.bot = bot
        self.config = config
        self.logger = bot.logger
        self.ai_agent = None
        self.timezone = pytz.timezone(config.meetings.default_timezone)
        
    async def initialize(self):
        """Initialize the AI agent."""
        try:
            # Get AI model for time parsing
            model = await get_agent(
                self.config.meetings.time_parser_ai_service,
                self.config.meetings.time_parser_model
            )
            
            if not model:
                # Try backup
                model = await get_agent(
                    self.config.meetings.backup_time_parser_ai_service,
                    self.config.meetings.backup_time_parser_model
                )
            
            if not model:
                raise Exception("No AI model available for time parsing")
            
            # Create time parser agent
            self.ai_agent = Agent(
                model=model,
                system_prompt=self._get_system_prompt()
            )
            
            self.logger.info("Time parser agent initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize time parser agent: {e}")
            raise
    
    def _get_system_prompt(self) -> str:
        """Get system prompt for time parsing."""
        now = datetime.now(self.timezone)
        
        return f"""你是一個專業的時間解析助手，專門將自然語言的時間表達轉換為標準格式。

當前時間: {now.strftime('%Y-%m-%d %H:%M %A')} (台北時區)

你的任務：
1. 解析自然語言時間表達式
2. 轉換為 ISO 8601 格式 (YYYY-MM-DDTHH:MM:SS)
3. 提供信心分數 (0-100)
4. 處理相對時間 (明天、下週、後天等)
5. 處理模糊時間 (早上、下午、晚上等)

時間對應表：
- 早上/上午: 09:00
- 中午: 12:00  
- 下午: 14:00
- 傍晚: 17:00
- 晚上: 19:00
- 深夜: 22:00

週期對應：
- 今天: {now.strftime('%Y-%m-%d')}
- 明天: {(now + timedelta(days=1)).strftime('%Y-%m-%d')}
- 後天: {(now + timedelta(days=2)).strftime('%Y-%m-%d')}

回應格式必須是 JSON：
{{
    "parsed_time": "YYYY-MM-DDTHH:MM:SS",
    "confidence": 95,
    "interpreted_as": "2025年1月20日下午2點",
    "ambiguous": false,
    "suggestions": []
}}

如果時間模糊或有多種可能，設置 ambiguous=true 並提供 suggestions 數組。
如果完全無法解析，設置 confidence=0。

範例：
輸入: "明天下午2點"
輸出: {{"parsed_time": "{(now + timedelta(days=1)).strftime('%Y-%m-%d')}T14:00:00", "confidence": 95, "interpreted_as": "明天下午2點", "ambiguous": false, "suggestions": []}}

輸入: "週五晚上"
輸出: {{"parsed_time": "...", "confidence": 80, "interpreted_as": "本週五晚上7點", "ambiguous": true, "suggestions": ["2025-01-24T19:00:00", "2025-01-31T19:00:00"]}}
"""
    
    async def parse_time(self, time_text: str, user_id: int, guild_id: int) -> Dict:
        """
        Parse natural language time expression.
        
        Args:
            time_text: Natural language time expression
            user_id: User ID for logging
            guild_id: Guild ID for logging
            
        Returns:
            Dict with parsed time information
        """
        start_time = datetime.now()
        
        try:
            # First try pattern matching for common expressions
            pattern_result = self._try_pattern_matching(time_text)
            if pattern_result and pattern_result.get('confidence', 0) > 70:
                await self._log_parse_attempt(
                    user_id, guild_id, time_text, pattern_result,
                    "pattern_matching", True, None, 
                    (datetime.now() - start_time).total_seconds()
                )
                return pattern_result
            
            # Use AI for complex expressions
            ai_result = await self._parse_with_ai(time_text)
            
            # Validate AI result
            validated_result = self._validate_parsed_time(ai_result)
            
            await self._log_parse_attempt(
                user_id, guild_id, time_text, validated_result,
                self.config.meetings.time_parser_model, True, None,
                (datetime.now() - start_time).total_seconds()
            )
            
            return validated_result
            
        except Exception as e:
            self.logger.error(f"Time parsing failed: {e}")
            
            await self._log_parse_attempt(
                user_id, guild_id, time_text, None,
                "error", False, str(e),
                (datetime.now() - start_time).total_seconds()
            )
            
            return {
                "parsed_time": None,
                "confidence": 0,
                "interpreted_as": "無法解析",
                "ambiguous": True,
                "suggestions": [],
                "error": str(e)
            }
    
    def _try_pattern_matching(self, time_text: str) -> Optional[Dict]:
        """Try to parse using simple pattern matching."""
        now = datetime.now(self.timezone)
        text = time_text.lower().strip()
        
        # Common patterns
        patterns = [
            # Tomorrow + time
            (r'明天\s*(\d{1,2})[點点]\s*(\d{1,2})?[分]?', lambda m: self._parse_tomorrow_time(m)),
            (r'明天\s*(早上|上午|中午|下午|傍晚|晚上)', lambda m: self._parse_tomorrow_period(m)),
            
            # Today + time  
            (r'今天\s*(\d{1,2})[點点]\s*(\d{1,2})?[分]?', lambda m: self._parse_today_time(m)),
            (r'今天\s*(早上|上午|中午|下午|傍晚|晚上)', lambda m: self._parse_today_period(m)),
            
            # Day after tomorrow
            (r'後天\s*(\d{1,2})[點点]\s*(\d{1,2})?[分]?', lambda m: self._parse_day_after_tomorrow_time(m)),
            (r'後天\s*(早上|上午|中午|下午|傍晚|晚上)', lambda m: self._parse_day_after_tomorrow_period(m)),
        ]
        
        for pattern, parser in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return parser(match)
                except:
                    continue
        
        return None
    
    def _parse_tomorrow_time(self, match) -> Dict:
        """Parse 'tomorrow + specific time' pattern."""
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        
        tomorrow = datetime.now(self.timezone) + timedelta(days=1)
        parsed_time = tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        return {
            "parsed_time": parsed_time.strftime('%Y-%m-%dT%H:%M:%S'),
            "confidence": 90,
            "interpreted_as": f"明天{hour}點{minute}分",
            "ambiguous": False,
            "suggestions": []
        }
    
    def _parse_tomorrow_period(self, match) -> Dict:
        """Parse 'tomorrow + time period' pattern."""
        period = match.group(1)
        time_map = {
            '早上': 9, '上午': 9, '中午': 12, 
            '下午': 14, '傍晚': 17, '晚上': 19
        }
        
        hour = time_map.get(period, 14)
        tomorrow = datetime.now(self.timezone) + timedelta(days=1)
        parsed_time = tomorrow.replace(hour=hour, minute=0, second=0, microsecond=0)
        
        return {
            "parsed_time": parsed_time.strftime('%Y-%m-%dT%H:%M:%S'),
            "confidence": 85,
            "interpreted_as": f"明天{period}{hour}點",
            "ambiguous": False,
            "suggestions": []
        }
    
    def _parse_today_time(self, match) -> Dict:
        """Parse 'today + specific time' pattern."""
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        
        today = datetime.now(self.timezone)
        parsed_time = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # If time has passed, assume tomorrow
        if parsed_time <= today:
            parsed_time += timedelta(days=1)
            interpreted = f"明天{hour}點{minute}分"
        else:
            interpreted = f"今天{hour}點{minute}分"
        
        return {
            "parsed_time": parsed_time.strftime('%Y-%m-%dT%H:%M:%S'),
            "confidence": 90,
            "interpreted_as": interpreted,
            "ambiguous": False,
            "suggestions": []
        }
    
    def _parse_today_period(self, match) -> Dict:
        """Parse 'today + time period' pattern."""
        period = match.group(1)
        time_map = {
            '早上': 9, '上午': 9, '中午': 12,
            '下午': 14, '傍晚': 17, '晚上': 19
        }
        
        hour = time_map.get(period, 14)
        today = datetime.now(self.timezone)
        parsed_time = today.replace(hour=hour, minute=0, second=0, microsecond=0)
        
        # If time has passed, assume tomorrow
        if parsed_time <= today:
            parsed_time += timedelta(days=1)
            interpreted = f"明天{period}{hour}點"
        else:
            interpreted = f"今天{period}{hour}點"
        
        return {
            "parsed_time": parsed_time.strftime('%Y-%m-%dT%H:%M:%S'),
            "confidence": 85,
            "interpreted_as": interpreted,
            "ambiguous": False,
            "suggestions": []
        }
    
    def _parse_day_after_tomorrow_time(self, match) -> Dict:
        """Parse 'day after tomorrow + specific time' pattern."""
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        
        day_after = datetime.now(self.timezone) + timedelta(days=2)
        parsed_time = day_after.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        return {
            "parsed_time": parsed_time.strftime('%Y-%m-%dT%H:%M:%S'),
            "confidence": 90,
            "interpreted_as": f"後天{hour}點{minute}分",
            "ambiguous": False,
            "suggestions": []
        }
    
    def _parse_day_after_tomorrow_period(self, match) -> Dict:
        """Parse 'day after tomorrow + time period' pattern."""
        period = match.group(1)
        time_map = {
            '早上': 9, '上午': 9, '中午': 12,
            '下午': 14, '傍晚': 17, '晚上': 19
        }
        
        hour = time_map.get(period, 14)
        day_after = datetime.now(self.timezone) + timedelta(days=2)
        parsed_time = day_after.replace(hour=hour, minute=0, second=0, microsecond=0)
        
        return {
            "parsed_time": parsed_time.strftime('%Y-%m-%dT%H:%M:%S'),
            "confidence": 85,
            "interpreted_as": f"後天{period}{hour}點",
            "ambiguous": False,
            "suggestions": []
        }
    
    async def _parse_with_ai(self, time_text: str) -> Dict:
        """Parse time using AI agent."""
        if not self.ai_agent:
            raise Exception("AI agent not initialized")
        
        try:
            response = await self.ai_agent.run(
                f"請解析這個時間表達式: {time_text}"
            )
            
            # Parse JSON response
            import json
            if hasattr(response, 'data'):
                result = response.data
            else:
                result = json.loads(str(response))
            
            return result
            
        except Exception as e:
            self.logger.error(f"AI parsing failed: {e}")
            raise
    
    def _validate_parsed_time(self, result: Dict) -> Dict:
        """Validate and adjust parsed time result."""
        if not result or not result.get('parsed_time'):
            return result
        
        try:
            # Parse the time string
            parsed_time = datetime.fromisoformat(result['parsed_time'])
            
            # Ensure it's in the future
            now = datetime.now(self.timezone)
            if parsed_time <= now:
                # If in the past, adjust by adding days until future
                days_to_add = 1
                while parsed_time <= now:
                    parsed_time = parsed_time + timedelta(days=days_to_add)
                    days_to_add = 1
                
                result['parsed_time'] = parsed_time.strftime('%Y-%m-%dT%H:%M:%S')
                result['interpreted_as'] += " (已調整至未來時間)"
            
            # Check if too far in future (> 1 year)
            max_future = now + timedelta(days=365)
            if parsed_time > max_future:
                result['confidence'] = max(0, result['confidence'] - 30)
                result['ambiguous'] = True
            
            return result
            
        except Exception as e:
            self.logger.error(f"Time validation failed: {e}")
            result['confidence'] = 0
            result['error'] = "時間格式驗證失敗"
            return result
    
    async def _log_parse_attempt(self, user_id: int, guild_id: int, 
                                original_text: str, result: Dict,
                                model_used: str, success: bool, 
                                error_message: str, processing_time: float):
        """Log parsing attempt for analytics."""
        try:
            log_entry = MeetingParseLog(
                user_id=user_id,
                guild_id=guild_id,
                original_text=original_text,
                ai_model_used=model_used,
                processing_time=processing_time,
                success=success,
                error_message=error_message
            )
            
            if result:
                if result.get('parsed_time'):
                    log_entry.parsed_time = datetime.fromisoformat(result['parsed_time'])
                log_entry.confidence_score = result.get('confidence', 0)
                
            log_entry.save()
            
        except Exception as e:
            self.logger.error(f"Failed to log parse attempt: {e}") 
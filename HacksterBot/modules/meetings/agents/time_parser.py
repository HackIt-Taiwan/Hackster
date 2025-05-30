"""
Time parser agent for natural language meeting scheduling.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import time
import pytz
import json
from core.models import MeetingParseLog
from modules.ai.services.ai_select import get_agent, create_general_agent


class TimeParserAgent:
    """Agent for parsing natural language time expressions."""
    
    def __init__(self, bot, config):
        self.bot = bot
        self.config = config
        self.logger = bot.logger
        self.timezone = pytz.timezone(config.meetings.default_timezone)
        self.time_agent = None
        
    async def initialize(self):
        """Initialize the dedicated time parsing AI agent."""
        try:
            # Create a dedicated time parsing agent
            ai_model = await get_agent(
                self.config.meetings.time_parser_ai_service,
                self.config.meetings.time_parser_model
            )
            
            if ai_model is None:
                # Try backup service
                ai_model = await get_agent(
                    self.config.meetings.backup_time_parser_ai_service,
                    self.config.meetings.backup_time_parser_model
                )
            
            if ai_model is None:
                raise Exception("No AI model available for time parsing")
            
            # Create specialized time parsing agent with dedicated system prompt
            # Note: create_general_agent only accepts model, so we need to create agent manually
            from pydantic_ai import Agent
            self.time_agent = Agent(ai_model, system_prompt=self._get_agent_system_prompt())
            
            self.logger.info(f"Time parsing agent initialized successfully with {self.config.meetings.time_parser_ai_service}")
        except Exception as e:
            self.logger.error(f"Failed to initialize time parser agent: {e}")
            raise
    
    def _get_agent_system_prompt(self) -> str:
        """Get specialized system prompt for the time parsing agent."""
        now = datetime.now(self.timezone)
        # Use English weekday names to avoid encoding issues
        current_weekday_num = now.weekday() + 1  # Monday=1, Sunday=7
        
        # Calculate next few days for reference
        tomorrow = now + timedelta(days=1)
        day_after_tomorrow = now + timedelta(days=2)
        
        return f"""你是一個高精度的時間解析專家AI，專門負責將自然語言時間表達轉換為精確的ISO 8601時間戳。

**當前時間環境（請嚴格參考）：**
- 現在時間: {now.strftime('%Y-%m-%d %H:%M:%S')} (週{current_weekday_num})
- 時區: 台北時區 (GMT+8)
- 今天: {now.strftime('%Y-%m-%d')} (週{current_weekday_num})
- 明天: {tomorrow.strftime('%Y-%m-%d')} (週{(tomorrow.weekday() + 1)})
- 後天: {day_after_tomorrow.strftime('%Y-%m-%d')} (週{(day_after_tomorrow.weekday() + 1)})

**核心專業能力（100%準確率要求）：**

1. **精確相對時間計算**:
   - 分鐘級: "5分鐘後" = {(now + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S')}
   - 小時級: "2小時後" = {(now + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S')}
   - 天級: "明天同一時間" = {tomorrow.strftime('%Y-%m-%d')}T{now.strftime('%H:%M:%S')}

2. **絕對時間理解（智能推理）**:
   - "明天下午2點" = {tomorrow.strftime('%Y-%m-%d')}T14:00:00
   - "今天晚上8點" = {now.strftime('%Y-%m-%d')}T20:00:00 (如果已過則調到明天)
   - "下週五下午3點" = 計算下週五 + T15:00:00

3. **模糊時間智能預設**:
   - 早上/上午 → 09:00
   - 中午 → 12:00
   - 下午 → 14:00
   - 傍晚 → 17:00
   - 晚上 → 19:00
   - 深夜 → 22:00

4. **週期時間精確計算**:
   - "週一" = 找到下一個週一
   - "這週五" = 本週五，如果已過則下週五
   - "下週三" = 嚴格下週三

5. **複雜表達式解析**:
   - "下週二下午3點半" = 下週二 + T15:30:00
   - "月底" = 當月最後一天 + 預設時間
   - "兩天後早上" = 後天 + T09:00:00

**嚴格解析規則（不可違反）：**
1. 所有輸出時間必須在未來（晚於現在時間）
2. 如果時間已過，自動調到下一個符合的時間點
3. 使用標準 ISO 8601 格式：YYYY-MM-DDTHH:MM:SS
4. 相對時間從當前精確時間 {now.strftime('%H:%M:%S')} 計算
5. 信心度反映解析的確定程度（90+ = 非常確定，70-89 = 基本確定，50-69 = 可能正確，<50 = 不確定）

**輸出格式（嚴格JSON，無額外文字）：**
{{
    "parsed_time": "YYYY-MM-DDTHH:MM:SS",
    "confidence": 0-100,
    "interpreted_as": "你的理解說明（簡潔英文）",
    "ambiguous": true/false,
    "suggestions": ["備選方案1", "備選方案2"]
}}

**高準確度示例（請嚴格遵循）：**

輸入: "5分鐘後"
輸出: {{"parsed_time": "{(now + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S')}", "confidence": 98, "interpreted_as": "5 minutes from now", "ambiguous": false, "suggestions": []}}

輸入: "明天下午2點"
輸出: {{"parsed_time": "{tomorrow.strftime('%Y-%m-%d')}T14:00:00", "confidence": 95, "interpreted_as": "tomorrow 2pm", "ambiguous": false, "suggestions": []}}

輸入: "今天晚上"
當前邏輯: 如果現在是{now.strftime('%H:%M')}，晚上19:00是否已過？
輸出: 根據是否已過決定今天還是明天

輸入: "週五"
當前邏輯: 今天是週{current_weekday_num}，週五是否已過？
輸出: 下一個週五的日期 + 預設時間

**重要提醒**：
- 你是時間計算專家，必須100%準確
- 絕對不要輸出過去時間
- JSON格式必須嚴格正確，不允許語法錯誤
- 信心度要真實反映你的確定程度
- 解釋使用簡潔英文避免編碼問題
- 如果無法確定，誠實設置低信心度和 ambiguous=true"""
        
    def _get_system_prompt(self) -> str:
        """Get comprehensive system prompt for time parsing (fallback)."""
        now = datetime.now(self.timezone)
        # Use English weekday names to avoid encoding issues
        current_weekday_num = now.weekday() + 1  # Monday=1, Sunday=7
        
        # Calculate next few days for reference
        tomorrow = now + timedelta(days=1)
        day_after_tomorrow = now + timedelta(days=2)
        next_week = now + timedelta(days=7)
        
        return f"""你是一個專業的時間解析AI助手，專門將各種自然語言的時間表達轉換為精確的時間戳。

**當前時間信息：**
- 現在時間: {now.strftime('%Y-%m-%d %H:%M:%S')} (周{current_weekday_num})
- 時區: 台北時區 (GMT+8)
- 今天: {now.strftime('%Y-%m-%d')} (周{current_weekday_num})
- 明天: {tomorrow.strftime('%Y-%m-%d')} (周{(tomorrow.weekday() + 1)})
- 後天: {day_after_tomorrow.strftime('%Y-%m-%d')} (周{(day_after_tomorrow.weekday() + 1)})

**你需要處理的時間表達類型包括但不限於：**

1. **相對時間**:
   - 分鐘: "5分鐘後", "十分鐘後", "半小時後", "一小時後"
   - 天數: "明天", "後天", "下週", "下個月"
   - 立即: "現在", "馬上", "立刻"

2. **絕對時間**:
   - 具體日期: "2025年1月30日", "1月30號", "30號"
   - 具體時間: "下午2點", "晚上8點半", "中午12點"
   - 組合: "明天下午2點", "週五晚上7點"

3. **模糊時間**:
   - 時段: "早上", "上午", "中午", "下午", "傍晚", "晚上", "深夜"
   - 週期: "週一", "週二", "這週五", "下週三"
   - 節日: "下週末", "這個月底", "月初"

4. **複雜表達**:
   - "下週二下午3點半"
   - "這個月25號上午10點"
   - "兩小時後"
   - "今天稍晚"
   - "週末的時候"

**時間預設對應 (當時間模糊時使用)：**
- 早上/上午: 09:00
- 中午: 12:00  
- 下午: 14:00
- 傍晚: 17:00
- 晚上: 19:00
- 深夜: 22:00

**解析規則：**
1. 所有解析出的時間必須是未來時間
2. 如果時間已過，自動調整到下一個符合的時間點
3. 相對時間從當前時間開始計算
4. 模糊時間使用預設時間對應表
5. 優先選擇最近的符合時間

**輸出格式：**
請只回傳有效的JSON格式，格式如下：
{{
    "parsed_time": "YYYY-MM-DDTHH:MM:SS",
    "confidence": 0-100,
    "interpreted_as": "你如何理解這個時間表達",
    "ambiguous": true/false,
    "suggestions": ["備選時間1", "備選時間2"] (如果模糊的話)
}}

**範例：**
輸入: "5分鐘後"
輸出: {{"parsed_time": "{(now + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S')}", "confidence": 95, "interpreted_as": "從現在起5分鐘後", "ambiguous": false, "suggestions": []}}

輸入: "明天下午2點"
輸出: {{"parsed_time": "{tomorrow.strftime('%Y-%m-%d')}T14:00:00", "confidence": 95, "interpreted_as": "明天下午2點", "ambiguous": false, "suggestions": []}}

輸入: "週五晚上"
輸出: {{"parsed_time": "...", "confidence": 80, "interpreted_as": "本週或下週五晚上7點", "ambiguous": true, "suggestions": ["這週五19:00", "下週五19:00"]}}

**重要提醒：**
- 必須確保解析出的時間是未來時間
- 使用台北時區 (GMT+8)
- 只回傳JSON，不要額外文字說明
- 信心分數要反映解析的準確度
- 如果無法解析，設置 confidence=0
"""
    
    async def parse_time(self, time_text: str, user_id: int, guild_id: int) -> Dict:
        """
        Parse natural language time expression using dedicated time agent.
        
        Args:
            time_text: Natural language time expression
            user_id: User ID for logging
            guild_id: Guild ID for logging
            
        Returns:
            Dict with parsed time information
        """
        start_time = datetime.now()
        
        try:
            # Use dedicated time parsing agent
            if self.time_agent is None:
                await self.initialize()
            
            ai_result = await self._parse_with_time_agent(time_text)
            
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
    
    async def _parse_with_time_agent(self, time_text: str) -> Dict:
        """Parse time using dedicated time parsing agent."""
        try:
            if self.time_agent is None:
                raise Exception("Time parsing agent not initialized")
            
            # Use the dedicated time agent to parse the time expression
            response = await self.time_agent.run(f"請解析這個時間表達式: \"{time_text}\"")
            
            if not response:
                raise Exception("Time agent returned empty response")
            
            # Convert response to string if needed
            response_text = str(response).strip()
            self.logger.debug(f"Time agent response for '{time_text}': {response_text}")
            
            # Try to extract JSON using regex - find JSON blocks
            json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
            json_matches = re.findall(json_pattern, response_text, re.DOTALL)
            
            if json_matches:
                json_text = json_matches[-1]  # Use last/most complete JSON
            else:
                # If no JSON found, try to find JSON-like content
                json_text = response_text.strip()
                # Remove markdown code blocks if present
                if json_text.startswith('```'):
                    lines = json_text.split('\n')
                    json_lines = []
                    in_json = False
                    for line in lines:
                        if line.startswith('```'):
                            in_json = not in_json
                            continue
                        if in_json:
                            json_lines.append(line)
                    json_text = '\n'.join(json_lines).strip()
            
            self.logger.debug(f"Extracted JSON text: {json_text}")
            
            # Try to parse directly first (AI might return valid JSON)
            try:
                result = json.loads(json_text)
                self.logger.debug(f"Successfully parsed JSON directly: {result}")
            except json.JSONDecodeError:
                # If direct parsing fails, try to fix common issues
                self.logger.debug("Direct JSON parsing failed, attempting to fix format...")
                
                # Method 1: Simple replacements for common issues
                fixed_json = json_text
                
                # Fix lowercase 't' in timestamps (but be more careful)
                fixed_json = re.sub(r'"(\d{4}-\d{2}-\d{2})t(\d{2}:\d{2}:\d{2})"', r'"\1T\2"', fixed_json, flags=re.IGNORECASE)
                
                # Fix single quotes to double quotes
                fixed_json = fixed_json.replace("'", '"')
                
                # Remove any trailing commas before closing braces/brackets
                fixed_json = re.sub(r',(\s*[}\]])', r'\1', fixed_json)
                
                try:
                    result = json.loads(fixed_json)
                    self.logger.debug(f"Successfully parsed JSON after simple fixes: {result}")
                except json.JSONDecodeError:
                    # Method 2: More aggressive fixing
                    self.logger.debug("Simple fixes failed, trying more aggressive repairs...")
                    
                    # Try to rebuild JSON structure manually
                    try:
                        # Extract key-value pairs using regex
                        parsed_time_match = re.search(r'"?parsed_time"?\s*:\s*"([^"]*)"', json_text, re.IGNORECASE)
                        confidence_match = re.search(r'"?confidence"?\s*:\s*(\d+)', json_text, re.IGNORECASE)
                        interpreted_match = re.search(r'"?interpreted_as"?\s*:\s*"([^"]*)"', json_text, re.IGNORECASE)
                        ambiguous_match = re.search(r'"?ambiguous"?\s*:\s*(true|false)', json_text, re.IGNORECASE)
                        
                        # Build result manually
                        result = {
                            "parsed_time": parsed_time_match.group(1) if parsed_time_match else None,
                            "confidence": int(confidence_match.group(1)) if confidence_match else 0,
                            "interpreted_as": interpreted_match.group(1) if interpreted_match else "時間代理解析",
                            "ambiguous": ambiguous_match.group(1).lower() == 'true' if ambiguous_match else False,
                            "suggestions": []
                        }
                        
                        # Fix timestamp format if needed
                        if result["parsed_time"]:
                            result["parsed_time"] = re.sub(r'(\d{4}-\d{2}-\d{2})t(\d{2}:\d{2}:\d{2})', r'\1T\2', result["parsed_time"], flags=re.IGNORECASE)
                        
                        self.logger.debug(f"Successfully rebuilt JSON manually: {result}")
                        
                    except Exception as manual_error:
                        self.logger.error(f"Manual JSON reconstruction failed: {manual_error}")
                        raise json.JSONDecodeError("Could not parse or reconstruct JSON", json_text, 0)
            
            # Validate required fields
            if not isinstance(result, dict):
                raise Exception("Time agent response is not a valid dictionary")
                
            required_fields = ['parsed_time', 'confidence', 'interpreted_as', 'ambiguous']
            for field in required_fields:
                if field not in result:
                    result[field] = None if field == 'parsed_time' else (0 if field == 'confidence' else False if field == 'ambiguous' else '時間代理解析失敗')
            
            # Ensure suggestions is a list
            if 'suggestions' not in result:
                result['suggestions'] = []
            elif not isinstance(result['suggestions'], list):
                result['suggestions'] = []
            
            return result
            
        except Exception as e:
            self.logger.error(f"Time agent parsing failed for '{time_text}': {e}")
            # Return fallback result
            return {
                "parsed_time": None,
                "confidence": 0,
                "interpreted_as": "時間代理解析失敗",
                "ambiguous": True,
                "suggestions": [],
                "error": str(e)
            }

    async def _parse_with_ai(self, time_text: str) -> Dict:
        """Parse time using AI agent with comprehensive prompt (fallback method)."""
        try:
            # Get AI module from bot
            ai_module = self.bot.modules.get('ai')
            if not ai_module or not ai_module.ai_handler:
                raise Exception("AI module not available")
            
            # Prepare comprehensive prompt
            prompt = f"{self._get_system_prompt()}\n\n請解析這個時間表達式: \"{time_text}\""
            
            # Use AI handler to get response
            response_chunks = []
            async for chunk in ai_module.ai_handler.get_streaming_response(prompt):
                response_chunks.append(chunk)
            
            if not response_chunks:
                raise Exception("AI returned empty response")
            
            # Combine chunks to get full response
            response_text = ''.join(response_chunks).strip()
            self.logger.debug(f"AI response for '{time_text}': {response_text}")
            
            # Try to extract JSON using regex - find JSON blocks
            json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
            json_matches = re.findall(json_pattern, response_text, re.DOTALL)
            
            if json_matches:
                json_text = json_matches[-1]  # Use last/most complete JSON
            else:
                # If no JSON found, try to find JSON-like content
                json_text = response_text.strip()
                # Remove markdown code blocks if present
                if json_text.startswith('```'):
                    lines = json_text.split('\n')
                    json_lines = []
                    in_json = False
                    for line in lines:
                        if line.startswith('```'):
                            in_json = not in_json
                            continue
                        if in_json:
                            json_lines.append(line)
                    json_text = '\n'.join(json_lines).strip()
            
            self.logger.debug(f"Extracted JSON text: {json_text}")
            
            # Try to parse directly first (AI might return valid JSON)
            try:
                result = json.loads(json_text)
                self.logger.debug(f"Successfully parsed JSON directly: {result}")
            except json.JSONDecodeError:
                # If direct parsing fails, try to fix common issues
                self.logger.debug("Direct JSON parsing failed, attempting to fix format...")
                
                # Method 1: Simple replacements for common issues
                fixed_json = json_text
                
                # Fix lowercase 't' in timestamps (but be more careful)
                fixed_json = re.sub(r'"(\d{4}-\d{2}-\d{2})t(\d{2}:\d{2}:\d{2})"', r'"\1T\2"', fixed_json, flags=re.IGNORECASE)
                
                # Fix single quotes to double quotes
                fixed_json = fixed_json.replace("'", '"')
                
                # Remove any trailing commas before closing braces/brackets
                fixed_json = re.sub(r',(\s*[}\]])', r'\1', fixed_json)
                
                try:
                    result = json.loads(fixed_json)
                    self.logger.debug(f"Successfully parsed JSON after simple fixes: {result}")
                except json.JSONDecodeError:
                    # Method 2: More aggressive fixing
                    self.logger.debug("Simple fixes failed, trying more aggressive repairs...")
                    
                    # Try to rebuild JSON structure manually
                    try:
                        # Extract key-value pairs using regex
                        parsed_time_match = re.search(r'"?parsed_time"?\s*:\s*"([^"]*)"', json_text, re.IGNORECASE)
                        confidence_match = re.search(r'"?confidence"?\s*:\s*(\d+)', json_text, re.IGNORECASE)
                        interpreted_match = re.search(r'"?interpreted_as"?\s*:\s*"([^"]*)"', json_text, re.IGNORECASE)
                        ambiguous_match = re.search(r'"?ambiguous"?\s*:\s*(true|false)', json_text, re.IGNORECASE)
                        
                        # Build result manually
                        result = {
                            "parsed_time": parsed_time_match.group(1) if parsed_time_match else None,
                            "confidence": int(confidence_match.group(1)) if confidence_match else 0,
                            "interpreted_as": interpreted_match.group(1) if interpreted_match else "AI解析",
                            "ambiguous": ambiguous_match.group(1).lower() == 'true' if ambiguous_match else False,
                            "suggestions": []
                        }
                        
                        # Fix timestamp format if needed
                        if result["parsed_time"]:
                            result["parsed_time"] = re.sub(r'(\d{4}-\d{2}-\d{2})t(\d{2}:\d{2}:\d{2})', r'\1T\2', result["parsed_time"], flags=re.IGNORECASE)
                        
                        self.logger.debug(f"Successfully rebuilt JSON manually: {result}")
                        
                    except Exception as manual_error:
                        self.logger.error(f"Manual JSON reconstruction failed: {manual_error}")
                        raise json.JSONDecodeError("Could not parse or reconstruct JSON", json_text, 0)
            
            # Validate required fields
            if not isinstance(result, dict):
                raise Exception("AI response is not a valid dictionary")
                
            required_fields = ['parsed_time', 'confidence', 'interpreted_as', 'ambiguous']
            for field in required_fields:
                if field not in result:
                    result[field] = None if field == 'parsed_time' else (0 if field == 'confidence' else False if field == 'ambiguous' else 'AI解析失敗')
            
            # Ensure suggestions is a list
            if 'suggestions' not in result:
                result['suggestions'] = []
            elif not isinstance(result['suggestions'], list):
                result['suggestions'] = []
            
            return result
            
        except Exception as e:
            self.logger.error(f"AI parsing failed for '{time_text}': {e}")
            # Return fallback result
            return {
                "parsed_time": None,
                "confidence": 0,
                "interpreted_as": "AI解析失敗",
                "ambiguous": True,
                "suggestions": [],
                "error": str(e)
            }
    
    def _validate_parsed_time(self, result: Dict) -> Dict:
        """Validate and adjust parsed time result."""
        if not result or not result.get('parsed_time'):
            return result
        
        try:
            # Parse the time string
            parsed_time_str = result['parsed_time']
            parsed_time = datetime.fromisoformat(parsed_time_str)
            
            # Handle timezone conversion properly
            if parsed_time.tzinfo is None:
                # For timezone-naive datetime, use pytz.localize()
                try:
                    parsed_time = self.timezone.localize(parsed_time)
                except AttributeError:
                    # If self.timezone doesn't have localize (not a pytz timezone), use replace
                    parsed_time = parsed_time.replace(tzinfo=self.timezone)
            else:
                # Convert to the configured timezone if it has a different timezone
                parsed_time = parsed_time.astimezone(self.timezone)
            
            # Get current time with timezone (ensure both are timezone-aware)
            now = datetime.now(self.timezone)
            
            # Ensure it's in the future
            if parsed_time <= now:
                # If in the past, adjust by adding days until future
                days_to_add = 1
                while parsed_time <= now:
                    parsed_time = parsed_time + timedelta(days=days_to_add)
                    days_to_add = 1
                
                # Convert back to naive datetime for storage (remove timezone info)
                parsed_time_naive = parsed_time.replace(tzinfo=None)
                result['parsed_time'] = parsed_time_naive.strftime('%Y-%m-%dT%H:%M:%S')
                result['interpreted_as'] += " (adjusted to future)"
            else:
                # Convert back to naive datetime for storage
                parsed_time_naive = parsed_time.replace(tzinfo=None)
                result['parsed_time'] = parsed_time_naive.strftime('%Y-%m-%dT%H:%M:%S')
            
            # Check if too far in future (> 1 year)
            max_future = now + timedelta(days=365)
            if parsed_time > max_future:
                result['confidence'] = max(0, result['confidence'] - 30)
                result['ambiguous'] = True
            
            return result
            
        except Exception as e:
            self.logger.error(f"Time validation failed: {e}")
            result['confidence'] = 0
            result['error'] = "Time format validation failed"
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
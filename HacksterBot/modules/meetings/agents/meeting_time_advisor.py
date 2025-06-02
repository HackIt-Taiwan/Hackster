"""
Meeting Time Advisor Agent - AI service for recommending meeting times based on availability.
"""

import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic_ai import Agent
from modules.ai.services.ai_select import get_agent, create_general_agent
from core.models import Meeting


class MeetingTimeAdvisor:
    """AI agent for analyzing available times and recommending optimal meeting times."""
    
    def __init__(self, bot, config):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.ai_agent = None
        
    async def initialize(self):
        """Initialize the AI agent."""
        try:
            # Get AI model instance
            ai_model = await get_agent(
                self.config.meetings.time_parser_ai_service,
                self.config.meetings.time_parser_model
            )
            
            if not ai_model:
                self.logger.error("No AI model available for meeting time advisor")
                return False
                
            # Create the AI agent with specialized system prompt
            from pydantic_ai import Agent
            self.ai_agent = Agent(ai_model, system_prompt=self._get_system_prompt())
            
            self.logger.info("Meeting time advisor AI agent initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize meeting time advisor: {e}")
            return False
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for meeting time recommendations."""
        return """你是一個專業的會議時間協調助手。你的任務是分析用戶的有空時間，並推薦最合適的會議時間。

## 輸入格式
你會收到以下資訊：
1. 原會議時間
2. 無法出席用戶的其他有空時間描述
3. 會議時長（分鐘）
4. 當前日期時間

## 分析要求
1. 仔細分析每個用戶提供的有空時間
2. 尋找所有用戶都可能有空的時間段
3. 考慮原會議時間的相似性（同一天、相近時間等）
4. 考慮一般的會議習慣（工作時間、避免深夜等）

## 輸出要求
你必須返回一個標準的JSON格式，包含以下欄位：

```json
{
    "recommendations": [
        {
            "datetime": "2024-01-20T14:00:00",
            "reason": "週六下午都有空",
            "confidence": 85
        },
        {
            "datetime": "2024-01-22T10:00:00", 
            "reason": "週一上午時段",
            "confidence": 75
        },
        {
            "datetime": "2024-01-23T19:00:00",
            "reason": "週二晚上時段",
            "confidence": 65
        }
    ],
    "analysis": "分析了3位無法出席用戶的時間偏好，發現週末下午和平日晚上是最佳選擇",
    "conflicts": "部分用戶提到週四不方便，已避開此時段"
}
```

## 重要規則
1. 必須提供恰好3個建議時間
2. 時間格式必須是ISO 8601格式（YYYY-MM-DDTHH:MM:SS）
3. 信心度分數在1-100之間
4. 推薦時間必須在未來
5. 考慮台灣時區（UTC+8）
6. 如果找不到完美匹配，提供最佳妥協方案
7. 絕對不要返回過去的時間
8. **原因說明必須簡潔，最多10個字**

分析時要特別注意：
- 「週一到週五」表示工作日
- 「晚上」通常指19:00-22:00
- 「下午」通常指14:00-18:00  
- 「上午」通常指09:00-12:00
- 避免太早（08:00前）或太晚（22:00後）的時間"""

    async def recommend_times(self, meeting: Meeting, current_time: datetime) -> Optional[Dict[str, Any]]:
        """
        Analyze available times and recommend 3 optimal meeting times.
        
        Args:
            meeting: Meeting object with attendee information
            current_time: Current datetime for reference
            
        Returns:
            Dict containing recommendations, analysis, and conflicts
        """
        try:
            if not self.ai_agent:
                await self.initialize()
                if not self.ai_agent:
                    return None
            
            # Collect available times from attendees who can't attend
            unavailable_attendees = []
            for attendee in meeting.attendees:
                if attendee.status == 'not_attending' and attendee.available_times:
                    unavailable_attendees.append({
                        'user_id': attendee.user_id,
                        'username': attendee.username or f"User {attendee.user_id}",
                        'available_times': attendee.available_times
                    })
            
            if not unavailable_attendees:
                self.logger.info("No unavailable attendees with available times data")
                return None
            
            # Prepare input for AI
            input_data = {
                'original_meeting_time': meeting.scheduled_time.isoformat(),
                'meeting_duration_minutes': meeting.duration_minutes or 60,
                'current_datetime': current_time.isoformat(),
                'unavailable_attendees': unavailable_attendees,
                'meeting_title': meeting.title
            }
            
            prompt = f"""請分析以下會議資訊並推薦3個最佳的替代時間：

## 會議資訊
- 會議標題：{meeting.title}
- 原定時間：{meeting.scheduled_time.strftime('%Y/%m/%d %H:%M')}
- 會議時長：{meeting.duration_minutes or 60}分鐘
- 當前時間：{current_time.strftime('%Y/%m/%d %H:%M')}

## 無法出席用戶的其他有空時間
"""
            
            for i, attendee in enumerate(unavailable_attendees, 1):
                prompt += f"\n### 用戶 {i}：{attendee['username']}\n"
                prompt += f"有空時間：{attendee['available_times']}\n"
            
            prompt += "\n請根據以上資訊推薦3個最合適的會議時間。"
            
            self.logger.debug(f"Sending prompt to AI: {prompt}")
            
            # Get AI recommendation
            result = await self.ai_agent.run(prompt)
            
            if not result or not result.data:
                self.logger.error("AI agent returned empty result")
                return None
            
            # Parse AI response
            response_text = str(result.data).strip()
            self.logger.debug(f"AI response: {response_text}")
            
            # Try to extract JSON from response
            try:
                # Look for JSON in the response
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group()
                    recommendation_data = json.loads(json_str)
                else:
                    # Try to parse the entire response as JSON
                    recommendation_data = json.loads(response_text)
                
                # Validate the response structure
                if not self._validate_recommendation(recommendation_data):
                    self.logger.error("Invalid recommendation structure from AI")
                    return None
                
                self.logger.info(f"Successfully generated {len(recommendation_data.get('recommendations', []))} time recommendations")
                return recommendation_data
                
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to parse AI response as JSON: {e}")
                self.logger.error(f"Response was: {response_text}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error in recommend_times: {e}")
            return None
    
    def _validate_recommendation(self, data: Dict[str, Any]) -> bool:
        """Validate the AI recommendation response structure."""
        try:
            if not isinstance(data, dict):
                return False
            
            recommendations = data.get('recommendations', [])
            if not isinstance(recommendations, list) or len(recommendations) != 3:
                return False
            
            for rec in recommendations:
                if not isinstance(rec, dict):
                    return False
                
                # Check required fields
                if 'datetime' not in rec or 'reason' not in rec or 'confidence' not in rec:
                    return False
                
                # Validate datetime format
                try:
                    datetime.fromisoformat(rec['datetime'])
                except:
                    return False
                
                # Validate confidence score
                confidence = rec.get('confidence', 0)
                if not isinstance(confidence, (int, float)) or confidence < 1 or confidence > 100:
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating recommendation: {e}")
            return False 
import re
import json
import asyncio
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands
from core.module_base import ModuleBase
from core.models import BridgeSession, BridgeResponse
from modules.ai.services.ai_select import get_agent

# GMT+8 時區
GMT_PLUS_8 = timezone(timedelta(hours=8))

async def create_module(bot, config):
    return BridgeTimeModule(bot, config)


class BridgeFailureView(discord.ui.View):
    """View for handling AI analysis failures."""
    
    def __init__(self, session_id: str, bot, bridge_module):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.session_id = session_id
        self.bot = bot
        self.bridge_module = bridge_module
    
    @discord.ui.button(label="重試 AI 分析", style=discord.ButtonStyle.primary, emoji="🔄")
    async def retry_analysis(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Retry AI analysis."""
        await interaction.response.defer()
        
        session = self.bridge_module.sessions.get(self.session_id)
        if not session:
            await interaction.followup.send("會議已結束或不存在", ephemeral=True)
            return
        
        # Disable buttons during retry
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)
        
        # Retry analysis
        await self.bridge_module._analyze_session(session, retry_attempt=True)
    
    @discord.ui.button(label="提早總結", style=discord.ButtonStyle.secondary, emoji="📝")
    async def early_summary(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Provide early summary without AI analysis."""
        await interaction.response.defer()
        
        session = self.bridge_module.sessions.get(self.session_id)
        if not session:
            await interaction.followup.send("會議已結束或不存在", ephemeral=True)
            return
        
        # Generate manual summary
        summary_data = {
            "manual_summary": True,
            "responses": [{"user": r.username, "content": r.content} for r in session.responses]
        }
        
        await self.bridge_module._send_result(session, summary_data)
        await interaction.edit_original_response(content="已提供提早總結", view=None)


class BridgeTimeModule(ModuleBase):
    """Collect available meeting times from users and suggest options."""

    def __init__(self, bot, config):
        super().__init__(bot, config)
        self.sessions = {}
        self.ai_agent = None
        self.max_retries = 3
        self.retry_delay = 2  # seconds

    async def setup(self):
        await super().setup()
        await self._initialize_ai()
        await self._load_sessions()
        self.bot.add_listener(self._on_message, 'on_message')
        await self._register_commands()
        self.logger.info("BridgeTime module setup complete")

    async def teardown(self):
        self.bot.remove_listener(self._on_message, 'on_message')
        await super().teardown()

    async def _initialize_ai(self):
        model = await get_agent(
            self.config.bridge_time.ai_service,
            self.config.bridge_time.ai_model
        )
        if model:
            from pydantic_ai import Agent
            self.ai_agent = Agent(model, system_prompt=self._system_prompt())
        else:
            self.logger.warning("BridgeTime AI model unavailable")

    async def _load_sessions(self):
        for session in BridgeSession.objects(completed=False):
            self.sessions[str(session.id)] = session
        if self.sessions:
            self.logger.info(f"Loaded {len(self.sessions)} active bridge sessions")

    async def _register_commands(self):
        @self.bot.tree.command(name="bridge_time", description="橋會議時間")
        async def bridge_time_cmd(interaction: discord.Interaction, 參與者: str):
            await self._create_session(interaction, 參與者)

    def _parse_mentions(self, interaction: discord.Interaction, text: str):
        ids = [int(x) for x in re.findall(r'<@!?(\d+)>', text)]
        members = []
        for uid in ids:
            m = interaction.guild.get_member(uid)
            if m:
                members.append(m)
        return members

    async def _create_session(self, interaction: discord.Interaction, participants_str: str):
        await interaction.response.defer(ephemeral=True)
        members = self._parse_mentions(interaction, participants_str)
        
        # Add the command initiator as a participant if not already included
        initiator = interaction.user
        if initiator not in members:
            members.append(initiator)
        
        if not members:
            await interaction.followup.send("❌ 未找到參與者", ephemeral=True)
            return
        mention_text = ' '.join(m.mention for m in members)
        embed = discord.Embed(
            title="🕑 會議時間調查",
            description="請回覆此訊息，告訴我你有空的時間範圍。",
            color=discord.Color.blue()
        )
        embed.add_field(name="參與者", value=mention_text, inline=False)
        message = await interaction.channel.send(mention_text, embed=embed)
        session = BridgeSession(
            organizer_id=interaction.user.id,
            guild_id=interaction.guild.id,
            channel_id=message.channel.id,
            message_id=message.id,
            participant_ids=[m.id for m in members]
        )
        session.save()
        self.sessions[str(session.id)] = session
        await self._update_embed(session)
        await interaction.followup.send("已建立時間調查，請在上方訊息回覆", ephemeral=True)

    async def _on_message(self, message: discord.Message):
        if message.author.bot or not message.reference:
            return
        for session in list(self.sessions.values()):
            if session.message_id == message.reference.message_id and not session.completed:
                await self._handle_response(session, message)
                break

    async def _handle_response(self, session: BridgeSession, message: discord.Message):
        if message.author.id not in session.participant_ids:
            return
        resp = session.get_response(message.author.id)
        if resp:
            resp.content = message.content
            resp.responded_at = datetime.utcnow()
        else:
            resp = BridgeResponse(
                user_id=message.author.id,
                username=message.author.display_name,
                content=message.content,
                responded_at=datetime.utcnow()
            )
            session.responses.append(resp)
        session.save()
        await self._update_embed(session)
        responded_ids = [r.user_id for r in session.responses]
        if all(uid in responded_ids for uid in session.participant_ids):
            session.completed = True
            session.completed_at = datetime.utcnow()
            session.save()
            await self._update_embed(session, completed=True)
            await self._analyze_session(session)

    async def _update_embed(self, session: BridgeSession, completed: bool = False):
        channel = self.bot.get_channel(session.channel_id)
        if not channel:
            return
        try:
            message = await channel.fetch_message(session.message_id)
        except Exception:
            return
        embed = message.embeds[0] if message.embeds else discord.Embed(title="🕑 會議時間調查")
        responded = [f"<@{r.user_id}>" for r in session.responses]
        pending = [f"<@{uid}>" for uid in session.participant_ids if uid not in [r.user_id for r in session.responses]]
        embed.clear_fields()
        embed.add_field(name="已回覆", value='\n'.join(responded) if responded else '無', inline=False)
        embed.add_field(name="未回覆", value='\n'.join(pending) if pending else '無', inline=False)
        if completed:
            embed.add_field(name="狀態", value="已收集所有回覆，分析中...", inline=False)
            embed.color = discord.Color.green()
        await message.edit(embed=embed)

    def _system_prompt(self) -> str:
        return (
            "你是專業的會議時間協調助手，請根據成員提供的敘述找出可能的共同空檔。"
            "請分析所有參與者的時間安排，找出大家都有空的時間段。"
            
            "**關鍵規則**："
            "1. 建議時間必須在所有人的可用時間重疊範圍內"
            "2. 絕對禁止建議早上時間（06:00-12:00），除非所有人明確說早上有空"
            "3. 絕對禁止建議深夜時間（00:00-06:00），除非所有人明確說深夜有空"
            "4. 如果重疊時間是晚上，就建議晚上時間，不要建議其他時段"
            
            "輸出JSON格式：{\"times\":[{\"datetime\":\"YYYY-MM-DDTHH:MM:SS\",\"reason\":\"簡潔說明重疊時間範圍\"},...]}"
            "請提供最多3個建議時間，確保每個建議都在所有參與者的時間交集內。"
        )

    def _format_time_gmt8(self, iso_datetime_str: str) -> str:
        """
        Convert ISO datetime string to formatted string without timezone suffix.
        
        Args:
            iso_datetime_str: ISO format datetime string
            
        Returns:
            Formatted datetime string
        """
        try:
            # Parse the ISO datetime
            if iso_datetime_str.endswith('Z'):
                # UTC format
                dt = datetime.fromisoformat(iso_datetime_str.replace('Z', '+00:00'))
                # Convert to GMT+8
                gmt8_dt = dt.astimezone(GMT_PLUS_8)
            elif '+' in iso_datetime_str or iso_datetime_str.count('-') > 2:
                # Already has timezone info
                dt = datetime.fromisoformat(iso_datetime_str)
                gmt8_dt = dt.astimezone(GMT_PLUS_8)
            else:
                # No timezone info - assume it's already GMT+8 (what we requested from AI)
                dt = datetime.fromisoformat(iso_datetime_str)
                # Don't convert timezone since AI should provide GMT+8 directly
                gmt8_dt = dt.replace(tzinfo=GMT_PLUS_8)
            
            # Format as readable string without GMT+8 suffix
            weekdays = ['週一', '週二', '週三', '週四', '週五', '週六', '週日']
            weekday = weekdays[gmt8_dt.weekday()]
            
            formatted = f"{gmt8_dt.strftime('%Y/%m/%d')} ({weekday}) {gmt8_dt.strftime('%H:%M')}"
            
            # Debug logging
            self.logger.debug(f"Formatted time: {iso_datetime_str} -> {formatted}")
            
            return formatted
        except Exception as e:
            self.logger.error(f"Failed to format time {iso_datetime_str}: {e}")
            return iso_datetime_str

    async def _analyze_session(self, session: BridgeSession, retry_attempt: bool = False):
        """Analyze session with retry mechanism."""
        if not self.ai_agent:
            await self._send_result(session, "AI 模型不可用")
            return
        
        # Get current time in GMT+8
        current_time = datetime.now(GMT_PLUS_8)
        current_time_str = current_time.strftime("%Y/%m/%d (%a) %H:%M")
        current_weekday = current_time.strftime("%A")  # Full weekday name
        
        # Format user responses with timestamps
        formatted_responses = []
        for r in session.responses:
            # Convert response timestamp to GMT+8 if available
            if hasattr(r, 'responded_at') and r.responded_at:
                response_time = r.responded_at.astimezone(GMT_PLUS_8)
                time_str = response_time.strftime("%Y/%m/%d %H:%M")
            else:
                time_str = "時間未知"
            
            formatted_responses.append(f"[{time_str}] {r.username}: {r.content}")
        
        # Create enhanced prompt with context
        responses_text = "\n".join(formatted_responses)
        prompt = f"""當前時間：{current_time_str} (GMT+8)
今天是：{current_weekday}

以下是參與者在不同時間提供的有空時間安排：

{responses_text}

## 🚫 絕對禁止的建議：
- **禁止建議早上時間（06:00-12:00）**，除非所有人明確說早上有空
- **禁止建議深夜時間（00:00-06:00）**，除非所有人明確說深夜有空
- **禁止建議午休時間（12:00-14:00）**，除非所有人明確說午休有空
- **建議時間必須在所有人的可用時間重疊範圍內**

## ⏰ 時區和格式要求：
- **所有datetime必須使用GMT+8時區**
- **格式必須是：YYYY-MM-DDTHH:MM:SS**
- **不要使用UTC或其他時區**
- **如果建議22:00，datetime應該是 "2025-06-07T22:00:00"**
- **如果建議21:30，datetime應該是 "2025-06-07T21:30:00"**

## 分析步驟：
1. **解析每個人的具體時間範圍**：
   - "今天都還ok" = 當天從現在到23:59
   - "這個小時都還可以" = 當前小時到下個小時
   - "下午七點後" = 該日19:00之後到23:59
   - "晚上九點後~十一點" = 該日21:00-23:00
   - "明天" = {(datetime.now(GMT_PLUS_8) + timedelta(days=1)).strftime('%Y-%m-%d')}
   - "後天" = {(datetime.now(GMT_PLUS_8) + timedelta(days=2)).strftime('%Y-%m-%d')}

2. **計算重疊時間範圍**：
   - 找出所有人都有空的**最晚開始時間**到**最早結束時間**
   - 當前時間：{current_time_str}
   - 如果現在是21:35，有人說"今天都ok"，另人說"這個小時可以"
   - 重疊範圍是：21:35-22:00（這個小時的剩餘時間）

3. **在重疊範圍內選擇建議時間**：
   - **建議時間必須在重疊範圍內，不能在範圍外**
   - 優先選擇整點或半點時間
   - 確保是合理的會議時間（非深夜、非清晨）

## ✅ 正確範例（當前時間21:35）：
如果重疊時間是「今晚21:35-22:30」，正確建議：
- {(datetime.now(GMT_PLUS_8)).strftime('%Y-%m-%d')}T22:00:00 ✅（今晚22點）
- {(datetime.now(GMT_PLUS_8)).strftime('%Y-%m-%d')}T22:15:00 ✅（今晚22點15分）

## ❌ 絕對錯誤範例：
- {(datetime.now(GMT_PLUS_8)).strftime('%Y-%m-%d')}T06:00:00 ❌（早上6點，完全錯誤！）
- {(datetime.now(GMT_PLUS_8)).strftime('%Y-%m-%d')}T14:00:00 ❌（下午2點，不在重疊範圍）
- {(datetime.now(GMT_PLUS_8) + timedelta(days=1)).strftime('%Y-%m-%d')}T22:00:00 ❌（明天，不是今天）

## 重要指示：
**如果找不到重疊時間或合適的會議時段，請回覆空的times陣列：**
{{"times": [], "analysis": "說明為什麼找不到合適時間的具體原因"}}

**如果找到合適時間，請回覆（所有datetime使用GMT+8，格式YYYY-MM-DDTHH:MM:SS）：**
{{"times": [{{"datetime": "YYYY-MM-DDTHH:MM:SS", "reason": "具體的重疊時間分析"}}, ...], "analysis": "時間重疊分析說明"}}

**再次強調**：
1. datetime格式必須是YYYY-MM-DDTHH:MM:SS（如：2025-06-07T22:00:00）
2. 時區必須是GMT+8，不要轉換成UTC
3. 如果分析說建議22:00，datetime就必須是22:00:00，不能是06:00:00
4. 建議時間必須在所有參與者可用時間的交集內"""
        
        # Try analysis with retries
        for attempt in range(self.max_retries):
            try:
                self.logger.info(f"AI analysis attempt {attempt + 1}/{self.max_retries}")
                
                result = await self.ai_agent.run(prompt)
                text = str(result.data).strip() if result and result.data else ""
                match = re.search(r"\{.*\}", text, re.DOTALL)
                data = json.loads(match.group()) if match else json.loads(text)
                
                # Success! Send result
                await self._send_result(session, data)
                return
                
            except Exception as e:
                self.logger.error(f"AI analysis attempt {attempt + 1} failed: {e}")
                
                # If this is the last attempt, show failure options
                if attempt == self.max_retries - 1:
                    if not retry_attempt:  # Only show buttons on first failure, not retry
                        await self._send_failure_options(session, str(e))
                    else:
                        await self._send_result(session, f"AI 分析連續失敗: {str(e)}")
                    return
                
                # Wait before retry
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))  # Exponential backoff

    async def _send_failure_options(self, session: BridgeSession, error_message: str):
        """Send failure message with retry and early summary options."""
        channel = self.bot.get_channel(session.channel_id)
        if not channel:
            return
            
        try:
            message = await channel.fetch_message(session.message_id)
        except Exception:
            return
            
        embed = message.embeds[0] if message.embeds else discord.Embed(title="🕑 會議時間調查")
        embed.clear_fields()
        embed.add_field(
            name="⚠️ AI 分析失敗", 
            value=f"分析遇到問題：{error_message}\n\n請選擇下一步動作：", 
            inline=False
        )
        embed.color = discord.Color.orange()
        
        view = BridgeFailureView(str(session.id), self.bot, self)
        await message.edit(embed=embed, view=view)

    async def _send_result(self, session: BridgeSession, data):
        channel = self.bot.get_channel(session.channel_id)
        if not channel:
            return
        try:
            message = await channel.fetch_message(session.message_id)
        except Exception:
            return
        embed = message.embeds[0] if message.embeds else discord.Embed(title="🕑 會議時間調查")
        embed.clear_fields()
        
        if isinstance(data, dict):
            if data.get('manual_summary'):
                # Manual summary format
                response_list = []
                for resp in data.get('responses', []):
                    response_list.append(f"**{resp['user']}**: {resp['content']}")
                
                embed.add_field(
                    name="📝 提早總結", 
                    value='\n\n'.join(response_list), 
                    inline=False
                )
                embed.add_field(
                    name="💡 建議", 
                    value="請根據以上回覆手動安排合適的會議時間", 
                    inline=False
                )
                embed.color = discord.Color.blue()
            elif 'times' in data:
                # AI analysis format
                times_list = data.get('times', [])
                if times_list:
                    formatted_times = []
                    for t in times_list:
                        datetime_str = t.get('datetime', '')
                        reason = t.get('reason', '')
                        
                        # Format the time
                        formatted_time = self._format_time_gmt8(datetime_str)
                        formatted_times.append(f"**{formatted_time}**\n└ {reason}")
                    
                    embed.add_field(name="🎯 建議會議時間", value='\n\n'.join(formatted_times), inline=False)
                    embed.color = discord.Color.green()
                else:
                    # AI responded but found no suitable times
                    analysis = data.get('analysis', '無法找到大家都有空的時間重疊')
                    embed.add_field(
                        name="⚠️ 無法找到合適時間", 
                        value=f"AI 分析結果：{analysis}\n\n可能解決方案：\n• 調整時間範圍要求\n• 考慮更彈性的會議時段\n• 重新確認大家的空檔時間", 
                        inline=False
                    )
                    embed.color = discord.Color.orange()
                    
                    # Show failure options for no suitable times
                    view = BridgeFailureView(str(session.id), self.bot, self)
                    await message.edit(embed=embed, view=view)
                    return
            else:
                embed.add_field(name="結果", value=str(data), inline=False)
                embed.color = discord.Color.red()
        else:
            embed.add_field(name="結果", value=str(data), inline=False)
            embed.color = discord.Color.red()
            
        await message.edit(embed=embed, view=None)  # Remove any existing view
        if str(session.id) in self.sessions:
            del self.sessions[str(session.id)]


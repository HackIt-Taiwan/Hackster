import re
import json
from datetime import datetime
import discord
from discord.ext import commands
from core.module_base import ModuleBase
from core.models import BridgeSession, BridgeResponse
from modules.ai.services.ai_select import get_agent


async def create_module(bot, config):
    return BridgeTimeModule(bot, config)


class BridgeTimeModule(ModuleBase):
    """Collect available meeting times from users and suggest options."""

    def __init__(self, bot, config):
        super().__init__(bot, config)
        self.sessions = {}
        self.ai_agent = None

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
            "輸出JSON格式：{\"times\":[{\"datetime\":\"YYYY-MM-DDTHH:MM:SS\",\"reason\":\"說明\"},...]}"
        )

    async def _analyze_session(self, session: BridgeSession):
        if not self.ai_agent:
            await self._send_result(session, "AI 模型不可用")
            return
        lines = [f"{r.username}: {r.content}" for r in session.responses]
        prompt = "\n".join(lines)
        prompt = (
            "以下是參與者提供的有空時間，請找出三個所有人都可能有空的會議時間，"\
            "以JSON回覆。\n" + prompt
        )
        try:
            result = await self.ai_agent.run(prompt)
            text = str(result.data).strip() if result and result.data else ""
            match = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(match.group()) if match else json.loads(text)
        except Exception as e:
            self.logger.error(f"AI analysis failed: {e}")
            await self._send_result(session, text if 'text' in locals() else "分析失敗")
            return
        await self._send_result(session, data)

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
            times = [f"{t.get('datetime')} - {t.get('reason','')}" for t in data.get('times', [])]
            embed.add_field(name="建議時間", value='\n'.join(times) if times else '無法解析', inline=False)
        else:
            embed.add_field(name="結果", value=str(data), inline=False)
        embed.color = discord.Color.purple()
        await message.edit(embed=embed)
        if str(session.id) in self.sessions:
            del self.sessions[str(session.id)]


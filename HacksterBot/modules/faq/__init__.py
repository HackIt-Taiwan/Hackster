"""
FAQ module: auto-thread user questions, search Notion database for answers,
and manage resolution state with a persistent button.
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import discord
from discord import Message
from discord.ext import commands
from discord.ui import Button, View
from bson import ObjectId

from core.module_base import ModuleBase
from core.config import Config
from core.models import FAQQuestion

from .services.notion_faq import NotionFAQService, NotionFAQItem


logger = logging.getLogger(__name__)


# Emoji constants
QUESTION_FOUND_EMOJI = "💡"
QUESTION_RESOLVED_EMOJI = "✅"


@dataclass
class EventFAQConfig:
    event_id: str
    name: str
    question_channel_id: int
    staff_role_id: int
    notion_page_id: str


class ResolveQuestionButton(Button):
    def __init__(self, question_id: str, staff_role_id: int, author_id: int, disabled: bool = False):
        super().__init__(
            style=discord.ButtonStyle.green if not disabled else discord.ButtonStyle.secondary,
            label="標記已完成" if not disabled else "已完成",
            custom_id=f"faq_resolve_{question_id}",
            disabled=disabled,
        )
        self.question_id = question_id
        self.staff_role_id = staff_role_id
        self.author_id = author_id

    async def callback(self, interaction: discord.Interaction):
        # Permission: staff role or original author
        has_staff_role = any(role.id == self.staff_role_id for role in getattr(interaction.user, "roles", []))
        is_author = interaction.user.id == self.author_id
        if not (has_staff_role or is_author):
            await interaction.response.send_message("此操作僅限工作人員或提問者", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            oid = None
            try:
                oid = ObjectId(self.question_id)
            except Exception:
                oid = self.question_id
            question = FAQQuestion.objects(id=oid).first()
            if not question or question.resolved_at is not None:
                await interaction.followup.send("此問題已處理或不存在", ephemeral=True)
                return

            # Mark resolved
            from datetime import datetime
            question.resolved_at = datetime.utcnow()
            question.resolved_by = interaction.user.id
            question.resolution_type = question.resolution_type or "manual"
            question.save()

            # Disable buttons in current view
            if self.view:
                for item in self.view.children:
                    item.disabled = True
                await interaction.message.edit(view=self.view)

            # Add check emoji to original message and clear others
            guild = interaction.guild
            if guild:
                channel = guild.get_channel(question.channel_id)
                if channel:
                    try:
                        original_msg = await channel.fetch_message(question.message_id)
                        if original_msg:
                            try:
                                await original_msg.clear_reactions()
                            except Exception:
                                pass
                            try:
                                await original_msg.add_reaction(QUESTION_RESOLVED_EMOJI)
                            except Exception:
                                pass
                    except Exception:
                        pass

            await interaction.followup.send("✨ 已標記為完成", ephemeral=True)
            await interaction.channel.send("✨ 此問題已標記為完成")
        except Exception as e:
            logger.exception("Error resolving FAQ question: %s", e)
            try:
                await interaction.followup.send("處理時發生錯誤，請稍後再試", ephemeral=True)
            except Exception:
                pass


class ResolveQuestionView(View):
    def __init__(self, question_id: str, staff_role_id: int, author_id: int, is_resolved: bool):
        super().__init__(timeout=None)
        self.add_item(ResolveQuestionButton(question_id, staff_role_id, author_id, disabled=is_resolved))


class FAQModule(ModuleBase):
    def __init__(self, bot: commands.Bot, config: Config):
        super().__init__(bot, config)
        self.events: Dict[int, EventFAQConfig] = {}
        self.notion_services: Dict[str, NotionFAQService] = {}

    async def setup(self) -> None:
        await super().setup()
        self._load_event_config()
        self.bot.add_listener(self._on_message, "on_message")
        await self._register_persistent_views()
        logger.info("FAQModule setup complete with %d events", len(self.events))

    async def teardown(self) -> None:
        try:
            self.bot.remove_listener(self._on_message, "on_message")
        except Exception:
            pass
        await super().teardown()

    def _load_event_config(self) -> None:
        config_path = Path(self.config.data_dir) / "faq_config.json"
        if not config_path.exists():
            logger.warning("faq_config.json not found at %s", config_path)
            return
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            events: List[dict] = data.get("events", [])
            for item in events:
                notion_page_id = item.get("notion_page_id") or item.get("notion_page_url") or ""
                # Normalize page/database id (allow full URL-like string)
                notion_page_id = str(notion_page_id).split("-")[-1] if notion_page_id else ""
                ev = EventFAQConfig(
                    event_id=str(item.get("event_id", "")),
                    name=str(item.get("name", "Event")),
                    question_channel_id=int(item.get("question_channel_id", 0)),
                    staff_role_id=int(item.get("staff_role_id", 0)),
                    notion_page_id=notion_page_id,
                )
                if ev.question_channel_id:
                    self.events[ev.question_channel_id] = ev
                    self.notion_services[ev.event_id] = NotionFAQService(
                        api_key=self.config.faq.notion_api_key,
                        database_id=ev.notion_page_id,
                    )
        except Exception as e:
            logger.exception("Failed to load faq_config.json: %s", e)

    async def _register_persistent_views(self) -> None:
        try:
            unresolved = FAQQuestion.objects(resolved_at=None)
            for q in unresolved:
                # Find event by channel id to obtain staff role
                ev = self.events.get(q.channel_id)
                if not ev:
                    continue
                view = ResolveQuestionView(str(q.id), ev.staff_role_id, q.user_id, is_resolved=False)
                self.bot.add_view(view)
        except Exception as e:
            logger.exception("Error registering persistent views: %s", e)

    async def _on_message(self, message: Message):
        # Skip bots and DMs
        if message.author.bot or not message.guild:
            return

        # Not a configured question channel
        ev = self.events.get(message.channel.id)
        if not ev:
            return

        try:
            # Create thread for the question
            # Build thread name from user's question, prefixed by event name
            raw_content = message.content.strip() if message.content else ""
            question_line = raw_content.splitlines()[0].strip() if raw_content else "提問"
            # Discord thread name maximum length is 100 characters
            prefix = f"{ev.name}｜"
            max_total = 100
            max_question_len = max_total - len(prefix)
            if len(question_line) > max_question_len:
                question_line = question_line[:max(1, max_question_len)]
            thread_name = f"{prefix}{question_line}"
            thread = await message.create_thread(name=thread_name)

            # Save question record
            q = FAQQuestion(
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                message_id=message.id,
                thread_id=thread.id,
                user_id=message.author.id,
                content=message.content,
            )
            q.save()

            # Post initial info with resolve button (Embed)
            view = ResolveQuestionView(str(q.id), ev.staff_role_id, message.author.id, is_resolved=False)
            ack_embed = discord.Embed(
                title="已收到您的問題",
                description=(
                    "我們的工作人員會盡快前來協助。\n"
                    "若恰好在 FAQ 中找到相符資訊，我們也會在此補充提供參考。"
                ),
                colour=discord.Colour.from_rgb(0, 122, 255),
            )
            await thread.send(embed=ack_embed, view=view)

            # Search Notion
            service = self.notion_services.get(ev.event_id)
            matched: Optional[NotionFAQItem] = None
            if service:
                try:
                    matched = await service.find_matching_faq(self.config, message.content)
                except Exception:
                    matched = None

            if matched:
                # Reply with the found Q&A using an Embed
                answer_embed = discord.Embed(
                    title="可能的 FAQ 解答",
                    description="以下內容供快速參考；實際回覆以工作人員說明為準。",
                    colour=discord.Colour.from_rgb(52, 199, 89),
                )
                answer_embed.add_field(name="問題", value=matched.question, inline=False)
                # Ensure answer is not empty; fallback just in case
                answer_text = matched.answer or "目前沒有可用的答案"
                answer_embed.add_field(name="解答", value=answer_text, inline=False)
                if getattr(matched, "category", None):
                    answer_embed.add_field(name="類別", value=matched.category, inline=True)
                await thread.send(embed=answer_embed)
                # Mark FAQ response timestamp
                from datetime import datetime
                q.faq_response_at = datetime.utcnow()
                q.faq_status = "matched"
                q.resolution_type = "faq"
                q.save()

                # Add informative emoji (not check) on original message
                try:
                    await message.add_reaction(QUESTION_FOUND_EMOJI)
                except Exception:
                    pass
            else:
                # No match: notify staff in the thread
                try:
                    await thread.send(content=f"<@&{ev.staff_role_id}> 請協助此問題，暫未找到相符的 FAQ。")
                except Exception:
                    pass
        except Exception as e:
            logger.exception("Error handling FAQ message: %s", e)


def create_module(bot: commands.Bot, config: Config) -> FAQModule:
    return FAQModule(bot, config)



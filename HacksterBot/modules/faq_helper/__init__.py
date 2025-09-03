"""
FAQ Helper Module

功能：
- 監聽指定活動的「我有問題」頻道訊息
- 自動以該訊息建立 thread
- 從 Notion 公開頁面抓 FAQ（不使用 Notion API）
- 以 AI 進行語意匹配找出最接近的 Q/A，自動回覆
- 若無匹配，@ 工作人員請求協助
- 提供「標記已完成」持久化按鈕（限工作人員或提問本人可按）
- 標記完成後停用按鈕，並在原始訊息加上 ✅（先移除其他反應）
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import discord
from discord.ext import commands

from core.module_base import ModuleBase
from core.exceptions import ModuleError
from modules.ai.services.ai_select import create_general_ai_agent
try:
    from notion_client import AsyncClient as NotionAsyncClient  # type: ignore
except Exception:  # pragma: no cover
    NotionAsyncClient = None  # type: ignore


logger = logging.getLogger(__name__)


# -----------------------------
# Data classes and config
# -----------------------------


@dataclass
class FaqEventConfig:
    event_id: str
    name: str
    question_channel_id: int
    staff_role_id: int
    notion_page_url: str
    notion_api_key: Optional[str] = None


def _load_faq_config(config_data_dir: str) -> List[FaqEventConfig]:
    """Load FAQ module configuration from data/faq_config.json.

    The JSON format:
    {
      "events": [
        {
          "event_id": "hackday2025",
          "name": "HackDay 2025",
          "question_channel_id": 1234567890,
          "staff_role_id": 9876543210,
          "notion_page_url": "https://www.notion.so/..."
        }
      ]
    }
    """
    path = Path(config_data_dir) / "faq_config.json"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    events: List[FaqEventConfig] = []
    for item in data.get("events", []):
        try:
            events.append(
                FaqEventConfig(
                    event_id=str(item.get("event_id")),
                    name=str(item.get("name")),
                    question_channel_id=int(item.get("question_channel_id")),
                    staff_role_id=int(item.get("staff_role_id")),
                    notion_page_url=str(item.get("notion_page_url")),
                    notion_api_key=str(item.get("notion_api_key")) if item.get("notion_api_key") else None,
                )
            )
        except Exception:  # pragma: no cover - resilient parsing
            logger.warning("Invalid faq_config item skipped: %s", item)
    return events


# -----------------------------
# Notion public page scraper (simple)
# -----------------------------


class NotionAPIFaq:
    """Fetch FAQ items from Notion database using official API."""

    def __init__(self, api_key: Optional[str]):
        self.api_key = api_key
        self.client = None
        if api_key and NotionAsyncClient is not None:
            self.client = NotionAsyncClient(auth=api_key)

    async def fetch_pairs(self, database_id_or_url: str) -> List[Tuple[str, str]]:
        if self.client is None:
            logger.warning("Notion API client is not initialized")
            return []
        database_id = self._extract_database_id(database_id_or_url)
        if not database_id:
            logger.warning("Invalid Notion database id/url: %s", database_id_or_url)
            return []
        try:
            faqs: List[Tuple[str, str]] = []
            cursor = None
            while True:
                resp = await self.client.databases.query(database_id=database_id, start_cursor=cursor)
                for page in resp.get("results", []):
                    props = page.get("properties", {})
                    q = self._get_text(props.get("Question")) or self._get_text(props.get("問題"))
                    a = self._get_text(props.get("Answer")) or self._get_text(props.get("答案")) or self._get_text(props.get("回答"))
                    if q:
                        faqs.append((q, a or ""))
                if not resp.get("has_more"):
                    break
                cursor = resp.get("next_cursor")
            # Deduplicate
            unique = []
            seen = set()
            for q, a in faqs:
                key = (q.strip(), (a or "").strip())
                if key in seen:
                    continue
                seen.add(key)
                unique.append((q.strip(), (a or "").strip()))
            return unique
        except Exception as e:
            logger.error("Error querying Notion: %s", e)
            return []

    def _extract_database_id(self, value: str) -> Optional[str]:
        # Accept raw database_id or notion URL; database id is last 32 chars alphanumeric with dashes removed in API
        m = re.search(r"([0-9a-fA-F]{32})", value.replace("-", ""))
        if m:
            return m.group(1)
        return None

    def _get_text(self, prop: Optional[Dict[str, Any]]) -> str:
        if not prop or "type" not in prop:
            return ""
        t = prop["type"]
        try:
            if t == "title":
                return " ".join([r.get("plain_text", "") for r in prop.get("title", [])]).strip()
            if t == "rich_text":
                return " ".join([r.get("plain_text", "") for r in prop.get("rich_text", [])]).strip()
        except Exception:
            return ""
        return ""


# -----------------------------
# Discord UI Views
# -----------------------------


class MarkDoneView(discord.ui.View):
    """Compatibility persistent view for legacy single-button messages."""

    def __init__(self, *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)

    @discord.ui.button(label="標記已完成", style=discord.ButtonStyle.primary, custom_id="faq_done")
    async def mark_done(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore[override]
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("請使用最新的 FAQ 動作按鈕。", ephemeral=True)


# -----------------------------
# Main module
# -----------------------------


class FaqHelperModule(ModuleBase):
    """FAQ helper module implementing the described workflow."""

    def __init__(self, bot, config):
        super().__init__(bot, config)
        self.name = "faq_helper"
        self._events: List[FaqEventConfig] = []
        self._channel_map: Dict[int, FaqEventConfig] = {}
        self._ai_agent = None
        # Notion client will be created per-event using JSON-provided key
        self._notion = None

    async def setup(self) -> None:
        try:
            # Load JSON config
            self._events = _load_faq_config(self.config.data_dir)
            self._channel_map = {e.question_channel_id: e for e in self._events}

            if not self._events:
                logger.warning("faq_helper: no events configured in data/faq_config.json")

            # Prepare AI agent (general agent)
            self._ai_agent = await create_general_ai_agent(self.config)

            # Register persistent views so buttons remain active after restart
            self.bot.add_view(FAQActionsRuntime(self))

            # Listen to message events
            self.bot.add_listener(self.on_message, "on_message")

            await super().setup()
            logger.info("faq_helper module setup completed (%d events)", len(self._events))
        except Exception as e:
            logger.error("Failed to setup faq_helper: %s", e)
            raise ModuleError(f"faq_helper setup failed: {e}")

    async def teardown(self) -> None:
        try:
            self.bot.remove_listener(self.on_message, "on_message")
        except Exception:
            pass
        await super().teardown()

    # -------------------------
    # Event handling
    # -------------------------

    async def on_message(self, message: discord.Message):
        # Ignore bot/self
        if message.author.bot:
            return
        if message.guild is None:
            return

        event_cfg = self._channel_map.get(message.channel.id)
        if not event_cfg:
            return

        # Create a thread for this question
        thread_name = (message.content[:40] or event_cfg.name).replace("\n", " ")
        try:
            thread = await message.create_thread(name=f"Q: {thread_name}")
        except discord.Forbidden:
            await message.channel.send("我沒有建立討論串的權限，請聯絡管理員。")
            return
        except Exception as e:
            logger.error("Create thread failed: %s", e)
            return

        # Process in background to keep responsive
        asyncio.create_task(self._process_question_in_thread(message, thread, event_cfg))

    async def _process_question_in_thread(self, origin_message: discord.Message, thread: discord.Thread, event_cfg: FaqEventConfig):
        user_question = origin_message.content.strip()
        # Fetch FAQ via Notion API using per-event key
        notion = NotionAPIFaq(event_cfg.notion_api_key)
        pairs = await notion.fetch_pairs(event_cfg.notion_page_url)

        matched_answer: Optional[str] = None
        matched_question: Optional[str] = None

        if pairs:
            try:
                matched_question, matched_answer = await self._semantic_pick(user_question, pairs)
            except Exception as e:
                logger.warning("AI semantic pick failed, will fallback to simple contains: %s", e)
                matched_question, matched_answer = self._fallback_contains(user_question, pairs)
        else:
            logger.info("No FAQ pairs parsed from Notion page")

        # Compose response and UI
        # If找到匹配，會顯示含反饋的按鈕；否則僅提供標記完成
        actions_view = self._build_actions_view(has_match=bool(matched_answer))

        if matched_answer:
            # Mark with an informative emoji (not checkmark)
            try:
                await origin_message.add_reaction("💡")
            except Exception:
                pass

            embed = discord.Embed(title="智能解答", description=matched_answer, colour=discord.Colour.blurple())
            embed.add_field(name="相關問題", value=matched_question or "N/A", inline=False)
            embed.set_footer(text=f"{event_cfg.name} · FAQ 自動回覆")
            await thread.send(content=f"{origin_message.author.mention} 我找到可能的答案：\n若已解決請按下方按鈕，若需要更多協助也請回報。", embed=embed, view=actions_view)
        else:
            mention = f"<@&{event_cfg.staff_role_id}>"
            await thread.send(content=(
                f"{origin_message.author.mention} 我暫時找不到合適答案，已通知 {mention} 協助回覆。\n"
                "按下下方按鈕可在問題解決後標記完成。"
            ), view=actions_view)

    def _build_actions_view(self, *, has_match: bool) -> discord.ui.View:
        return FAQActionsRuntime(self, include_feedback=has_match)

    async def _semantic_pick(self, user_question: str, pairs: List[Tuple[str, str]]) -> Tuple[Optional[str], Optional[str]]:
        if not self._ai_agent:
            return self._fallback_contains(user_question, pairs)

        # Build compressed list to control token usage
        items = [
            {"q": q[:300], "a": a[:600]}
            for q, a in pairs[:50]
        ]
        prompt = (
            "You are a FAQ matcher. Given a user question and a list of Q/A, "
            "pick the single best match that can answer the user. If none is suitable, reply with JSON {\"match\": false}. "
            "Otherwise reply JSON {\"match\": true, \"q\": question, \"a\": answer}. "
            "Only output JSON."
        )
        query = {
            "user_question": user_question,
            "faq": items,
        }
        try:
            result = await self._ai_agent.run(prompt + "\n" + json.dumps(query, ensure_ascii=False))
            text = str(result.data)
        except Exception as e:
            logger.error("AI agent error: %s", e)
            return None, None

        # Parse JSON in the output
        m = re.search(r"\{.*\}$", text, re.S)
        if not m:
            return None, None
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return None, None
        if not obj.get("match"):
            return None, None
        return obj.get("q"), obj.get("a")

    def _fallback_contains(self, user_question: str, pairs: List[Tuple[str, str]]):
        uq = user_question.lower()
        for q, a in pairs:
            if q and q.lower() in uq or uq in q.lower():
                return q, a
        return None, None


class FAQActionsRuntime(discord.ui.View):
    """Runtime actions view with persistent custom_ids.

    Buttons:
    - faq_done: staff or author can mark as resolved
    - faq_feedback_resolved: author reports FAQ solved it
    - faq_feedback_need_help: author requests more help (ping staff)
    """

    def __init__(self, module: FaqHelperModule, *, include_feedback: bool = True, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.module = module
        self.include_feedback = include_feedback

    @discord.ui.button(label="標記已完成", style=discord.ButtonStyle.success, custom_id="faq_done")
    async def _done(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore[override]
        try:
            # Context from thread and config
            assert interaction.guild is not None
            member = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
            if not isinstance(member, discord.Member):
                await interaction.response.send_message("無法驗證身分。", ephemeral=True)
                return

            channel = interaction.channel
            if not isinstance(channel, discord.Thread):
                await interaction.response.send_message("請在討論串內操作。", ephemeral=True)
                return

            parent = channel.parent
            if parent is None:
                await interaction.response.send_message("找不到父頻道。", ephemeral=True)
                return

            # Resolve event config by question channel id
            event_cfg = self.module._channel_map.get(parent.id)
            staff_role_id = event_cfg.staff_role_id if event_cfg else 0

            # Starter/original message of the thread
            origin_message = None
            origin_msg_author_id: Optional[int] = None
            try:
                origin_message = await channel.starter_message()
                if origin_message is not None:
                    origin_msg_author_id = origin_message.author.id
            except Exception:
                origin_message = None

            has_staff = any(r.id == staff_role_id for r in member.roles) if staff_role_id else False
            is_author = (origin_msg_author_id is not None and member.id == origin_msg_author_id)
            if not (has_staff or is_author):
                await interaction.response.send_message("只有工作人員或提問者可以標記完成。", ephemeral=True)
                return

            # Disable button in this message
            for ch in self.children:
                if isinstance(ch, discord.ui.Button):
                    ch.disabled = True

            if interaction.response.is_done():
                await interaction.followup.edit_message(interaction.message.id, view=self)
            else:
                await interaction.response.edit_message(view=self)

            # Clear other reactions and add check on original message
            try:
                if origin_message is not None:
                    # Remove all reactions
                    for reaction in list(origin_message.reactions):
                        try:
                            await reaction.clear()
                        except Exception:
                            pass
                    await origin_message.add_reaction("✅")
            except Exception as e:
                logger.warning("Failed to update reactions: %s", e)

        except Exception as e:
            logger.error("Mark done failed: %s", e)
            if interaction.response.is_done():
                await interaction.followup.send("標記時發生錯誤，請稍後再試。", ephemeral=True)
            else:
                await interaction.response.send_message("標記時發生錯誤，請稍後再試。", ephemeral=True)

    @discord.ui.button(label="✨ 已解決問題", style=discord.ButtonStyle.primary, custom_id="faq_feedback_resolved")
    async def _feedback_resolved(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore[override]
        try:
            if not self.include_feedback:
                await interaction.response.send_message("此按鈕目前不可用。", ephemeral=True)
                return
            if not isinstance(interaction.channel, discord.Thread):
                await interaction.response.send_message("請在討論串內操作。", ephemeral=True)
                return
            origin = None
            try:
                origin = await interaction.channel.starter_message()
            except Exception:
                origin = None
            if origin is None:
                await interaction.response.send_message("找不到原始訊息。", ephemeral=True)
                return
            if interaction.user.id != origin.author.id:
                await interaction.response.send_message("只有提問者可以回報已解決。", ephemeral=True)
                return
            # Reuse _done
            await self._done.callback(self, interaction)  # type: ignore
        except Exception as e:
            logger.error("FAQ feedback resolved failed: %s", e)
            if interaction.response.is_done():
                await interaction.followup.send("處理失敗，請稍後重試。", ephemeral=True)
            else:
                await interaction.response.send_message("處理失敗，請稍後重試。", ephemeral=True)

    @discord.ui.button(label="💭 需要更多協助", style=discord.ButtonStyle.secondary, custom_id="faq_feedback_need_help")
    async def _feedback_need_help(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore[override]
        try:
            if not self.include_feedback:
                await interaction.response.send_message("此按鈕目前不可用。", ephemeral=True)
                return
            if not isinstance(interaction.channel, discord.Thread):
                await interaction.response.send_message("請在討論串內操作。", ephemeral=True)
                return
            thread = interaction.channel
            parent = thread.parent
            if parent is None:
                await interaction.response.send_message("找不到父頻道。", ephemeral=True)
                return
            origin = None
            try:
                origin = await thread.starter_message()
            except Exception:
                origin = None
            if origin is None:
                await interaction.response.send_message("找不到原始訊息。", ephemeral=True)
                return
            if interaction.user.id != origin.author.id:
                await interaction.response.send_message("只有提問者可以回報需要協助。", ephemeral=True)
                return

            event_cfg = self.module._channel_map.get(parent.id)
            staff_mention = f"<@&{event_cfg.staff_role_id}>" if event_cfg else "工作人員"

            # Disable feedback buttons only
            for ch in self.children:
                if isinstance(ch, discord.ui.Button) and ch.custom_id in {"faq_feedback_resolved", "faq_feedback_need_help"}:
                    ch.disabled = True
            if interaction.response.is_done():
                await interaction.followup.edit_message(interaction.message.id, view=self)
            else:
                await interaction.response.edit_message(view=self)

            try:
                await origin.add_reaction("🆘")
            except Exception:
                pass

            await thread.send(f"{staff_mention} 提問者表示需要更多協助，請協助回覆。")
            await interaction.followup.send("已通知工作人員協助，感謝回饋。", ephemeral=True)
        except Exception as e:
            logger.error("FAQ feedback need help failed: %s", e)
            if interaction.response.is_done():
                await interaction.followup.send("處理失敗，請稍後重試。", ephemeral=True)
            else:
                await interaction.response.send_message("處理失敗，請稍後重試。", ephemeral=True)


def create_module(bot, config):
    """Entry point used by the module loader."""
    return FaqHelperModule(bot, config)



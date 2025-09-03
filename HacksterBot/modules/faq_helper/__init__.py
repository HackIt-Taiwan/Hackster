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
                )
            )
        except Exception:  # pragma: no cover - resilient parsing
            logger.warning("Invalid faq_config item skipped: %s", item)
    return events


# -----------------------------
# Notion public page scraper (simple)
# -----------------------------


class NotionPublicFaq:
    """Fetch and parse a Notion public page that contains FAQ entries.

    目標：盡量以最簡單方式擷取頁面文字，萃取 (question, answer) 對。
    - 先嘗試抓取 <table> 結構（若 page 使用資料庫表格公開顯示）
    - 若無表格，備援：從全文中以常見欄位關鍵字切片（例如 問題/答案 或 Question/Answer）
    - 不使用 Notion API，僅以公開網址 HTML 解析
    """

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self._session = session

    async def fetch_pairs(self, url: str, timeout: float = 10.0) -> List[Tuple[str, str]]:
        headers = {"User-Agent": self.USER_AGENT}
        close_session = False
        session = self._session
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True
        try:
            async with session.get(url, headers=headers, timeout=timeout) as resp:
                html = await resp.text()
        except Exception as e:
            logger.error("Failed to fetch Notion page: %s", e)
            html = ""
        finally:
            if close_session:
                await session.close()

        if not html:
            return []

        pairs = self._parse_table_pairs(html)
        if pairs:
            return pairs
        return self._parse_text_pairs(html)

    def _parse_table_pairs(self, html: str) -> List[Tuple[str, str]]:
        from bs4 import BeautifulSoup  # lazy import

        soup = BeautifulSoup(html, "html.parser")
        pairs: List[Tuple[str, str]] = []

        for table in soup.find_all("table"):
            # Try to detect header columns resembling question/answer
            header_cells = table.find("thead")
            q_idx, a_idx = -1, -1
            if header_cells:
                headers = [c.get_text(strip=True) for c in header_cells.find_all("th")]
                for idx, text in enumerate(headers):
                    lt = text.lower()
                    if q_idx == -1 and ("question" in lt or "問題" in lt):
                        q_idx = idx
                    if a_idx == -1 and ("answer" in lt or "回答" in lt or "答案" in lt):
                        a_idx = idx
            # Fallback: assume first two columns
            if q_idx == -1 or a_idx == -1:
                q_idx, a_idx = 0, 1

            body = table.find("tbody") or table
            for tr in body.find_all("tr"):
                cells = [c.get_text("\n", strip=True) for c in tr.find_all(["td", "th"])]
                if len(cells) < max(q_idx, a_idx) + 1:
                    continue
                question = cells[q_idx].strip()
                answer = cells[a_idx].strip() if a_idx < len(cells) else ""
                if question:
                    pairs.append((question, answer))
        return self._dedupe_pairs(pairs)

    def _parse_text_pairs(self, html: str) -> List[Tuple[str, str]]:
        # Extremely simple heuristic: look for lines like "Q:" and "A:" or bullet pairs
        text = re.sub(r"<[^>]+>", "\n", html)
        text = re.sub(r"\n+", "\n", text)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        pairs: List[Tuple[str, str]] = []
        current_q: Optional[str] = None
        current_a_parts: List[str] = []
        for ln in lines:
            low = ln.lower()
            if re.match(r"^(q[:：]|問題[:：])", low):
                # flush previous
                if current_q is not None:
                    pairs.append((current_q, "\n".join(current_a_parts).strip()))
                    current_a_parts = []
                current_q = re.sub(r"^(q[:：]|問題[:：])\s*", "", ln, flags=re.IGNORECASE)
            elif re.match(r"^(a[:：]|答案[:：]|回答[:：])", low):
                current_a_parts.append(re.sub(r"^(a[:：]|答案[:：]|回答[:：])\s*", "", ln, flags=re.IGNORECASE))
            elif current_q is not None:
                current_a_parts.append(ln)
        if current_q is not None:
            pairs.append((current_q, "\n".join(current_a_parts).strip()))
        return self._dedupe_pairs(pairs)

    def _dedupe_pairs(self, pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        seen = set()
        unique: List[Tuple[str, str]] = []
        for q, a in pairs:
            key = (q.strip(), a.strip())
            if key in seen:
                continue
            seen.add(key)
            unique.append((q.strip(), a.strip()))
        return unique


# -----------------------------
# Discord UI View
# -----------------------------


class MarkDoneView(discord.ui.View):
    """Persistent view with a single "標記已完成" button."""

    def __init__(self, *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        # Register a persistent button. custom_id format encodes thread and message ids
        # custom_id = faq_done:{thread_id}:{origin_message_id}:{role_id}
        # The label remains constant in this persistent view; concrete IDs come from message-specific views

    @discord.ui.button(label="標記已完成", style=discord.ButtonStyle.primary, custom_id="faq_done")
    async def mark_done(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore[override]
        # The actual custom_id sent with message will be overridden per-message using a cloned view.
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("此按鈕僅作為持久化註冊，請於實際討論串使用。", ephemeral=True)


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
        self._scraper = NotionPublicFaq()

    async def setup(self) -> None:
        try:
            # Load JSON config
            self._events = _load_faq_config(self.config.data_dir)
            self._channel_map = {e.question_channel_id: e for e in self._events}

            if not self._events:
                logger.warning("faq_helper: no events configured in data/faq_config.json")

            # Prepare AI agent (general agent)
            self._ai_agent = await create_general_ai_agent(self.config)

            # Register persistent view so existing messages' buttons remain active after restart
            self.bot.add_view(MarkDoneRuntime(self))

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
        # Scrape Notion
        pairs = await self._scraper.fetch_pairs(event_cfg.notion_page_url)

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
        view = self._build_runtime_view(thread_id=thread.id, origin_message_id=origin_message.id, staff_role_id=event_cfg.staff_role_id)

        if matched_answer:
            # Mark with an informative emoji (not checkmark)
            try:
                await origin_message.add_reaction("💡")
            except Exception:
                pass

            embed = discord.Embed(title="可能的解答", description=matched_answer, colour=discord.Colour.blurple())
            embed.add_field(name="相關問題", value=matched_question or "N/A", inline=False)
            embed.set_footer(text=f"{event_cfg.name} · FAQ 自動回覆")
            await thread.send(content=f"{origin_message.author.mention} 我找到可能的答案：", embed=embed, view=view)
        else:
            mention = f"<@&{event_cfg.staff_role_id}>"
            await thread.send(content=(
                f"{origin_message.author.mention} 我暫時找不到合適答案，已通知 {mention} 協助回覆。\n"
                "按下下方按鈕可在問題解決後標記完成。"
            ), view=view)

    def _build_runtime_view(self, *, thread_id: int, origin_message_id: int, staff_role_id: int) -> discord.ui.View:
        view = MarkDoneRuntime(self)
        # Override button custom_id per message to encode context
        # We rely on a single button in the view at index 0
        for child in view.children:
            if isinstance(child, discord.ui.Button):
                child.custom_id = f"faq_done:{thread_id}:{origin_message_id}:{staff_role_id}"
        return view

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


class MarkDoneRuntime(discord.ui.View):
    """Runtime view used per-message with encoded custom_id.

    Button custom_id format: faq_done:{thread_id}:{origin_message_id}:{role_id}
    """

    def __init__(self, module: FaqHelperModule, *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.module = module

    @discord.ui.button(label="標記已完成", style=discord.ButtonStyle.success, custom_id="faq_done:runtime")
    async def _done(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore[override]
        try:
            # Extract ids
            cid = button.custom_id or ""
            if not cid.startswith("faq_done:"):
                await interaction.response.send_message("按鈕資訊有誤。", ephemeral=True)
                return
            parts = cid.split(":")
            if len(parts) != 4:
                await interaction.response.send_message("按鈕參數缺失。", ephemeral=True)
                return
            thread_id = int(parts[1])
            origin_message_id = int(parts[2])
            staff_role_id = int(parts[3])

            # Permission: staff role OR original author
            assert interaction.guild is not None
            member = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
            if not isinstance(member, discord.Member):
                await interaction.response.send_message("無法驗證身分。", ephemeral=True)
                return

            origin_msg_author_id: Optional[int] = None
            # Fetch parent channel and original message
            channel = interaction.channel
            if isinstance(channel, discord.Thread):
                parent = channel.parent
                if parent is None:
                    await interaction.response.send_message("找不到父頻道。", ephemeral=True)
                    return
                try:
                    origin_message = await parent.fetch_message(origin_message_id)
                    origin_msg_author_id = origin_message.author.id
                except Exception:
                    origin_message = None
            else:
                await interaction.response.send_message("請在討論串內操作。", ephemeral=True)
                return

            has_staff = any(r.id == staff_role_id for r in member.roles)
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


def create_module(bot, config):
    """Entry point used by the module loader."""
    return FaqHelperModule(bot, config)



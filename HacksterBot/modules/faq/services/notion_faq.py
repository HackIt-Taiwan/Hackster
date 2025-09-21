"""
Service to fetch FAQs from Notion and find matches using the existing AI stack.
"""
from dataclasses import dataclass
from typing import List, Optional

from notion_client import Client

from core.config import Config
from modules.ai.services.ai_select import create_general_ai_agent


@dataclass
class NotionFAQItem:
    question: str
    answer: str
    category: Optional[str] = None


class NotionFAQService:
    def __init__(self, api_key: Optional[str], database_id: str):
        self.client = Client(auth=api_key) if api_key else None
        self.database_id = database_id

    def _get_text(self, prop) -> str:
        try:
            t = prop.get("type")
            if t == "title":
                return " ".join([x["text"]["content"] for x in prop.get("title", [])])
            if t == "rich_text":
                return " ".join([x["text"]["content"] for x in prop.get("rich_text", [])])
            return ""
        except Exception:
            return ""

    def _extract_items(self, results) -> List[NotionFAQItem]:
        items: List[NotionFAQItem] = []
        for page in results or []:
            props = page.get("properties", {})
            q = self._get_text(props.get("Question", {})) or self._get_text(props.get("問題", {}))
            a = self._get_text(props.get("Answer", {})) or self._get_text(props.get("答案", {}))
            c = self._get_text(props.get("Category", {})) or self._get_text(props.get("分類", {}))
            if q and a:
                items.append(NotionFAQItem(question=q.strip(), answer=a.strip(), category=c.strip() if c else None))
        return items

    async def get_all_faqs(self) -> List[NotionFAQItem]:
        if not self.client or not self.database_id:
            return []
        try:
            resp = self.client.databases.query(database_id=self.database_id)
            return self._extract_items(resp.get("results", []))
        except Exception:
            return []

    async def find_matching_faq(self, config: Config, question: str) -> Optional[NotionFAQItem]:
        items = await self.get_all_faqs()
        if not items:
            return None

        formatted = []
        for idx, it in enumerate(items, 1):
            part = f"{idx}. Q: {it.question}\nA: {it.answer}"
            formatted.append(part)
        prompt = (
            "以下是我們的 FAQ 列表：\n\n" + "\n\n".join(formatted) +
            f"\n\n使用者問題：{question}\n\n"
            "請判斷上面哪一題最能解答此問題。如果有明顯對應，請只輸出該題目前面的整數序號；"
            "如果沒有合適的題目就輸出 0。請不要輸出其他文字。"
        )

        agent = await create_general_ai_agent(config)
        print(">>>>>> Agent created")
        if not agent:
            print(">>>>>> No agent")
            return None
        try:
            async with agent.run_stream(prompt) as result:
                out = ""
                async for chunk in result.stream_text(delta=True):
                    out += chunk
                    print(">>>>>> Chunk: ", chunk)
            out = (out or "").strip()
            print(">>>>>> Output: ", out)
            try:
                idx = int(out)
                if 1 <= idx <= len(items):
                    return items[idx - 1]
            except Exception as e:
                print(">>>>>> Error: ", e)
                return None
        except Exception as e:
            print(">>>>>> Error: ", e)
            return None
        return None



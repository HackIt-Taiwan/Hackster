"""
Message classifier agent for HacksterBot.
Classifies user messages into different types for appropriate handling.
"""
from pydantic_ai import Agent

CLASSIFIER_PROMPT = """
你是一個訊息分類器，你的工作是將用戶的訊息分類為以下類型之一：
- search: 需要搜尋網路上的資訊來回答
- chat: 一般的閒聊或情感交流
- general: 需要正經回答的問題或任務
- unknown: 無法明確分類的訊息

請只回傳分類結果（小寫），不要有任何其他文字。

分類範例：
用戶：今天天氣如何？
回覆：search

用戶：你好啊！
回覆：chat

用戶：幫我找一下最近的新聞
回覆：search

用戶：我好難過
回覆：chat

用戶：你覺得人工智能會取代人類嗎
回覆：general

用戶：解釋一下區塊鏈的運作原理
回覆：general

用戶：寫一首詩
回覆：general

現在請分類這個訊息：{message}
"""


async def create_classifier_agent(model) -> Agent:
    """
    Create a message classifier agent with the specified model.
    
    Args:
        model: AI model instance
        
    Returns:
        Configured Agent instance
    """
    # Set up the agent with classification-specific settings
    if hasattr(model, 'temperature'):
        model.temperature = 0.3
    if hasattr(model, 'max_tokens'):
        model.max_tokens = 10
    
    # Create agent with the classifier prompt
    agent = Agent(model, system_prompt=CLASSIFIER_PROMPT)
    return agent 
"""
Violation Categories Mapping for OpenAI Moderation API.
Maps English violation categories to Traditional Chinese for better user experience.
"""

# OpenAI Moderation API 違規類型繁體中文映射（帶表情符號）
VIOLATION_CATEGORY_MAPPING = {
    # 主要類型 - 底線格式（API返回格式）
    "harassment": "😡 騷擾內容",
    "harassment_threatening": "🔪 威脅性騷擾",
    "hate": "💢 仇恨言論",
    "hate_threatening": "⚠️ 威脅性仇恨言論",
    "self_harm": "💔 自我傷害相關內容",
    "self_harm_intent": "🆘 自我傷害意圖",
    "self_harm_instructions": "⛔ 自我傷害指導",
    "sexual": "🔞 性相關內容",
    "sexual_minors": "🚫 未成年相關性內容",
    "violence": "👊 暴力內容",
    "violence_graphic": "🩸 圖像化暴力內容",
    "illicit": "🚫 不法行為",
    "illicit_violent": "💣 暴力不法行為",
    
    # 斜線格式（原始格式）
    "harassment/threatening": "🔪 威脅性騷擾",
    "hate/threatening": "⚠️ 威脅性仇恨言論",
    "self-harm": "💔 自我傷害相關內容",
    "self-harm/intent": "🆘 自我傷害意圖",
    "self-harm/instructions": "⛔ 自我傷害指導",
    "sexual/minors": "🚫 未成年相關性內容",
    "violence/graphic": "🩸 圖像化暴力內容",
    "illicit/violent": "💣 暴力不法行為",
    
    # URL 安全類型
    "phishing": "🎣 釣魚網站",
    "malware": "🦠 惡意軟體",
    "scam": "💸 詐騙內容",
    "suspicious": "❓ 可疑內容",
    
    # 其他類型
    "spam": "📧 垃圾訊息",
    "fraud": "💰 詐騙內容",
    "url_safety": "🔗 不安全連結",
    "blacklisted_domain": "🚫 黑名單網域",
    
    # 默認類型
    "other": "❌ 其他違規",
    "unknown": "❓ 未知違規類型"
}

# 違規嚴重程度映射
VIOLATION_SEVERITY_MAPPING = {
    # 高風險類型
    "sexual/minors": 5,
    "hate/threatening": 5, 
    "violence/graphic": 5,
    "harassment/threatening": 5,
    "harassment_threatening": 5,  # 底線版本
    "self-harm/intent": 5,
    "self_harm/intent": 5,  # 底線版本
    "self_harm_intent": 5,  # 完全底線版本
    "illicit/violent": 5,
    
    # 中高風險類型
    "sexual": 4,
    "hate": 4,
    "violence": 4,
    "self-harm": 4,
    "self_harm": 4,  # 底線版本
    "illicit": 4,
    
    # 中風險類型
    "harassment": 3,
    "self-harm/instructions": 3,
    "self_harm/instructions": 3,  # 底線版本
    "self_harm_instructions": 3,  # 完全底線版本
    
    # 低風險類型
    "spam": 2,
    "fraud": 2,
    "url_safety": 2,
    
    # 其他
    "other": 1,
    "unknown": 1
}

# 詳細描述映射
VIOLATION_DESCRIPTION_MAPPING = {
    "sexual": "包含性相關內容，如性活動描述或性服務推廣（性教育和健康除外）",
    "hate": "基於種族、性別、種族、宗教、國籍、性取向、殘疾狀況或種姓表達、煽動或促進仇恨的內容",
    "violence": "促進或美化暴力或慶祝他人痛苦或羞辱的內容",
    "harassment": "可能在現實生活中用於折磨或騷擾個人，或使騷擾更容易發生的內容",
    "self-harm": "促進、鼓勵或描述自我傷害行為的內容，如自殺、割傷和飲食失調",
    "self_harm": "促進、鼓勵或描述自我傷害行為的內容，如自殺、割傷和飲食失調",
    "sexual/minors": "涉及18歲以下個人的性內容",
    "hate/threatening": "包含針對目標群體的暴力或嚴重傷害的仇恨內容",
    "violence/graphic": "以極其血腥細節描述死亡、暴力或嚴重身體傷害的暴力內容",
    "harassment/threatening": "包含威脅成分的騷擾內容",
    "harassment_threatening": "包含威脅成分的騷擾內容",
    "self-harm/intent": "表達自我傷害意圖的內容",
    "self_harm/intent": "表達自我傷害意圖的內容",
    "self_harm_intent": "表達自我傷害意圖的內容",
    "self-harm/instructions": "提供自我傷害指導的內容",
    "self_harm/instructions": "提供自我傷害指導的內容",
    "self_harm_instructions": "提供自我傷害指導的內容",
    "illicit": "涉及非法活動的內容",
    "illicit/violent": "涉及暴力非法活動的內容",
    "url_safety": "包含不安全或惡意連結",
    "spam": "垃圾訊息或重複發送的內容",
    "fraud": "詐騙或欺騙性內容",
    "other": "其他類型的違規內容",
    "unknown": "無法分類的違規內容"
}


def get_chinese_category(english_category: str) -> str:
    """
    將英文違規類型轉換為繁體中文。
    
    Args:
        english_category: 英文違規類型
        
    Returns:
        繁體中文違規類型
    """
    return VIOLATION_CATEGORY_MAPPING.get(english_category, english_category)


def get_violation_severity(category: str) -> int:
    """
    獲取違規類型的嚴重程度。
    
    Args:
        category: 違規類型
        
    Returns:
        嚴重程度（1-5，5為最嚴重）
    """
    return VIOLATION_SEVERITY_MAPPING.get(category, 1)


def get_violation_description(category: str) -> str:
    """
    獲取違規類型的詳細描述。
    
    Args:
        category: 違規類型
        
    Returns:
        詳細描述
    """
    return VIOLATION_DESCRIPTION_MAPPING.get(category, "未知的違規類型")


def get_chinese_description(category: str) -> str:
    """
    獲取違規類型的中文描述（別名函數）。
    
    Args:
        category: 違規類型
        
    Returns:
        中文描述
    """
    return get_violation_description(category)


def format_violation_categories(categories: list) -> str:
    """
    格式化違規類型列表為繁體中文字符串。
    
    Args:
        categories: 英文違規類型列表
        
    Returns:
        格式化的繁體中文字符串
    """
    if not categories:
        return "無"
    
    chinese_categories = [get_chinese_category(cat) for cat in categories]
    return "、".join(chinese_categories)


def get_violation_summary(categories: list) -> dict:
    """
    獲取違規摘要信息。
    
    Args:
        categories: 違規類型列表
        
    Returns:
        包含中文類型、最高嚴重程度和總數的字典
    """
    if not categories:
        return {
            "chinese_categories": [],
            "formatted_string": "無",
            "max_severity": 0,
            "total_count": 0,
            "high_severity_count": 0
        }
    
    chinese_categories = [get_chinese_category(cat) for cat in categories]
    severities = [get_violation_severity(cat) for cat in categories]
    max_severity = max(severities) if severities else 0
    high_severity_count = sum(1 for s in severities if s >= 4)
    
    return {
        "chinese_categories": chinese_categories,
        "formatted_string": "、".join(chinese_categories),
        "max_severity": max_severity,
        "total_count": len(categories),
        "high_severity_count": high_severity_count
    } 
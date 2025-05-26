"""
Community guidelines for HacksterBot moderation.
"""
from typing import List


def get_full_guidelines() -> str:
    """
    Get the complete community guidelines text.
    
    Returns:
        Complete guidelines as a formatted string
    """
    return """
# HackIt 社群規範

## 1. 基本原則
- 1.1 尊重與包容：尊重所有社群成員，不論其背景、經驗水平或觀點。
- 1.2 建設性溝通：提供建設性的反饋，避免無意義的批評。
- 1.3 真誠互助：鼓勵互相幫助和知識分享。
- 1.4 共同責任：共同維護社群秩序。

## 2. 禁止行為
- 2.1 騷擾與霸凌：禁止任何形式的騷擾、霸凌或威脅行為。
- 2.2 仇恨言論：禁止基於個人特徵的仇恨或歧視言論。
- 2.3 不當內容：禁止分享色情、暴力或血腥內容。
- 2.4 個人隱私：禁止未經許可分享他人個人信息。
- 2.5 垃圾訊息：禁止發送垃圾訊息或過度標記他人。
- 2.6 損害性行為：禁止分享可能造成傷害的內容。
- 2.7 非法活動：禁止討論或促進非法活動。
- 2.8 惡意軟體：禁止分享惡意軟體或釣魚網站。

## 3. 內容指南
- 3.1 適當討論主題：確保討論主題與頻道相關。
- 3.2 敏感話題處理：保持客觀、尊重的態度。
- 3.3 知識產權尊重：分享內容時尊重知識產權。
- 3.4 語言使用：避免過度使用冒犯性語言，但理解台灣文化中的誇張表達（如「想死」、「笑死」等）通常是無害的。
- 3.5 圖片與媒體：避免分享不當圖片或媒體。
- 3.6 連結分享：確保分享的連結安全且適當。

## 4. 違規處理與文化理解
- 4.1 違規等級：五級處罰機制（5分鐘→12小時→7天→7天→28天）
- 4.2 申訴與文化理解：考慮台灣/華語文化背景的口語表達和語境。

## 5. 社群參與
- 5.1 積極參與：鼓勵成員積極參與討論和活動。
- 5.2 建設性反饋：歡迎對社群的建設性建議。
- 5.3 協助新成員：幫助新成員融入社群。

## 6. 申訴流程
- 6.1 申訴權利：所有成員都有權對處罰提出申訴。
- 6.2 申訴方式：通過指定管道聯繫管理團隊。
- 6.3 公正處理：所有申訴將得到公正、透明的處理。
"""


def get_guidelines_for_violations(violation_categories: List[str]) -> List[str]:
    """
    Get relevant guideline sections for specific violation categories.
    
    Args:
        violation_categories: List of violation category names
        
    Returns:
        List of relevant guideline section numbers
    """
    category_mapping = {
        'harassment': ['2.1', '4.1'],
        'hate_speech': ['2.2', '4.1'],
        'graphic_content': ['2.3', '3.5'],
        'privacy': ['2.4'],
        'spam': ['2.5'],
        'harmful': ['2.6'],
        'illegal': ['2.7'],
        'malware': ['2.8'],
        'inappropriate': ['3.1', '3.2', '3.4'],
        'copyright': ['3.3'],
        'unsafe_links': ['2.8', '3.6']
    }
    
    relevant_sections = set()
    for category in violation_categories:
        if category in category_mapping:
            relevant_sections.update(category_mapping[category])
    
    return sorted(list(relevant_sections))


def format_mute_reason(violation_count: int, violation_categories: List[str]) -> str:
    """
    Format a mute reason based on violation count and categories.
    
    Args:
        violation_count: Number of violations for the user
        violation_categories: List of violation categories
        
    Returns:
        Formatted mute reason string
    """
    guidelines = get_guidelines_for_violations(violation_categories)
    guidelines_text = f"違反社群規則 {', '.join(guidelines)}" if guidelines else "違反社群規則"
    
    ordinal_map = {
        1: "第一次",
        2: "第二次", 
        3: "第三次",
        4: "第四次",
        5: "第五次"
    }
    
    ordinal = ordinal_map.get(violation_count, f"第{violation_count}次")
    
    return f"{ordinal}違規 - {guidelines_text}。請遵守社群規範，營造良好討論環境。" 
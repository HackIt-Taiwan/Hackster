# HacksterBot

一個為 HackIt 社群設計的模組化 Discord 機器人，整合了原先 AIHacker 和 AITicket 的所有功能。

## 🚀 特色功能

- **模組化架構**：每個功能都是獨立的模組，可以單獨啟用/停用
- **AI 智慧對話**：支援多種 AI 服務 (Azure OpenAI, Gemini, Anthropic)
- **內容審核**：自動檢測和處理不當內容
- **票務系統**：完整的客服票券管理
- **會議系統**：智慧會議安排與錄製管理
- **邀請管理**：追蹤和管理伺服器邀請連結
- **歡迎系統**：自動歡迎新成員
- **遊戲功能**：內建 21 點等遊戲
- **URL 安全檢查**：檢測惡意連結
- **彈性配置**：透過環境變數輕鬆配置

## 📁 專案架構

```
HacksterBot/
├── core/                          # 核心系統
│   ├── __init__.py
│   ├── bot.py                     # 主要bot類別
│   ├── config.py                  # 配置管理
│   ├── database.py                # 資料庫基礎類別
│   └── exceptions.py              # 自定義例外
├── modules/                       # 功能模組
│   ├── __init__.py
│   ├── ai/                        # AI 相關功能
│   │   ├── __init__.py
│   │   ├── handler.py
│   │   ├── agents/
│   │   ├── services/
│   │   └── classifiers/
│   ├── moderation/                # 審核系統
│   ├── tickets/                   # 票務系統
│   ├── welcome/                   # 歡迎系統
│   └── url_safety/                # URL 安全檢查
├── config/                        # 配置文件
│   ├── __init__.py
│   ├── settings.py
│   └── logging.py
├── data/                          # 資料儲存
├── logs/                          # 日誌
├── docs/                          # 文檔
├── tests/                         # 測試
├── main.py                        # 主入口
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## 🛠 安裝與設定

### 1. 環境需求

- Python 3.9+
- Discord Bot Token
- 各種 AI 服務的 API Keys (可選)

### 2. 安裝步驟

```bash
# 克隆專案
git clone <repository_url>
cd HacksterBot

# 建立虛擬環境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows

# 安裝依賴
pip install -r requirements.txt

# 複製配置文件
cp .env.example .env
```

### 3. 配置設定

編輯 `.env` 文件，填入您的配置：

```env
# 必需配置
DISCORD_TOKEN=your_discord_token_here

# AI 服務 (至少配置一個)
AZURE_OPENAI_API_KEY=your_azure_key
AZURE_OPENAI_ENDPOINT=your_azure_endpoint
GEMINI_API_KEY=your_gemini_key

# 其他服務 (可選)
TAVILY_API_KEY=your_tavily_key
NOTION_API_KEY=your_notion_key
URL_SAFETY_API_KEY=your_virustotal_key
```

### 4. 啟動機器人

```bash
python main.py
```

## 🔧 模組說明

### AI 模組 (`modules/ai`)
- **功能**：智慧對話、訊息分類、搜尋整合
- **配置**：`PRIMARY_AI_SERVICE`, `CLASSIFIER_AI_SERVICE`
- **依賴**：AI API Keys

### 審核模組 (`modules/moderation`)
- **功能**：內容審核、自動禁言、違規記錄
- **配置**：`CONTENT_MODERATION_ENABLED`
- **依賴**：OpenAI API (用於內容審核)

### 票務模組 (`modules/tickets`)
- **功能**：客服票券、頻道管理、對話記錄
- **配置**：`TICKET_ENABLED`
- **依賴**：無

### 歡迎模組 (`modules/welcome`)
- **功能**：新成員歡迎、重試機制
- **配置**：`WELCOME_ENABLED`, `WELCOME_CHANNEL_IDS`
- **依賴**：無

### 會議模組 (`modules/meetings`)
- **功能**：自然語言會議安排、自動提醒、語音頻道管理、會議錄製
- **配置**：`MEETINGS_ENABLED`, `MEETINGS_TIME_PARSER_AI_SERVICE`
- **依賴**：AI API Keys (用於時間解析)

### 錄製模組 (`modules/recording`)
- **功能**：多機器人會議錄製、音軌分離、自動清理
- **配置**：`RECORDING_BOT_TOKENS`
- **依賴**：多個 Discord Bot Tokens

### 邀請模組 (`modules/invites`)
- **功能**：邀請追蹤統計、每日報告、成長圖表
- **配置**：`INVITES_ENABLED`, `INVITES_DAILY_REPORTS_ENABLED`
- **依賴**：無

### 遊戲模組 (`modules/blackjack`)
- **功能**：21點遊戲、統計追蹤、排行榜
- **配置**：無特定配置
- **依賴**：無

### 票券系統模組 (`modules/tickets_system`)
- **功能**：活動票券管理、獎勵系統
- **配置**：無特定配置
- **依賴**：無

### URL 安全模組 (`modules/url_safety`)
- **功能**：惡意連結檢測、黑名單管理
- **配置**：`URL_SAFETY_CHECK_ENABLED`
- **依賴**：VirusTotal API

## 🎛 管理命令

### 會議管理
- 安排會議：`/meet <時間> <參與者> [標題] [描述]`
- 查看會議：`/meetings`
- 會議詳情：`/meeting_info <會議ID>`

### 遊戲功能
- 開始21點：`/blackjack`
- 遊戲統計：`/bj_stats`
- 重置遊戲：`/bj_reset`

### 票券系統
- 查看票券：`/tickets`

### 模組管理
- 查看已載入模組：`/modules list`
- 重新載入模組：`/modules reload <module_name>`
- 模組狀態：`/modules status`

### 審核管理
- 暫時禁言：`/timeout <user> <duration>`
- 解除禁言：`/remove_timeout <user>`

## 🔄 開發指南

### 新增模組

1. 在 `modules/` 下建立新資料夾
2. 實作模組類別：

```python
from core.bot import ModuleBase

class Module(ModuleBase):
    async def setup(self):
        await super().setup()
        # 模組初始化邏輯
        
    async def teardown(self):
        # 清理邏輯
        await super().teardown()
```

3. 在 `core/config.py` 中新增配置
4. 在 `core/bot.py` 的 `_is_module_enabled` 中新增啟用檢查

### 資料庫操作

```python
from core.database import BaseModel

class MyModel(BaseModel):
    def create_tables(self):
        query = """
        CREATE TABLE IF NOT EXISTS my_table (
            id INTEGER PRIMARY KEY,
            data TEXT
        )
        """
        self.execute_query(query)
```

### 事件處理

```python
async def setup(self):
    # 註冊事件監聽器
    self.bot.add_listener(self._on_message, 'on_message')

async def _on_message(self, message):
    # 處理訊息事件
    pass
```

## 🐛 疑難排解

### 常見問題

1. **模組載入失敗**
   - 檢查模組是否有 `Module` 類別或 `setup` 函數
   - 確認相依套件已安裝

2. **AI 服務錯誤**
   - 驗證 API Keys 是否正確
   - 檢查網路連接和 API 限制

3. **資料庫錯誤**
   - 確認 `data/` 目錄存在且有寫入權限
   - 檢查 SQLite 檔案是否損壞

### 日誌檢查

```bash
# 查看即時日誌
tail -f logs/hacksterbot.log

# 查看錯誤日誌
tail -f logs/error.log
```

## 📝 更新紀錄

### v1.0.0
- 整合 AIHacker 和 AITicket 功能
- 實作模組化架構
- 統一配置管理
- 改善錯誤處理和日誌

## 🤝 貢獻

歡迎提交 Issue 和 Pull Request！

## 📄 授權

MIT License 
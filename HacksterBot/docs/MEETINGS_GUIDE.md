# HacksterBot 會議系統使用指南

## 概述

HacksterBot 的會議系統提供完整的會議管理功能，包括自然語言時間解析、自動提醒、語音頻道創建和會議錄製。

## 主要功能

### 📅 會議安排 (`/meet`)

使用自然語言安排會議：

```
/meet 明天下午2點 @用戶1 @用戶2 會議標題 會議描述
```

**支援的時間表達式：**
- `明天下午2點`
- `後天上午10點30分`
- `今天晚上7點`
- `週五早上9點`

**參與者設定：**
- 直接 @ 提及用戶
- 使用 `公開` 創建公開會議

### 👥 會議管理

**查看我的會議：**
```
/meetings
```

**查看會議詳情：**
```
/meeting_info <會議ID>
```

### 🎯 會議控制

會議主辦人可以通過按鈕進行管理：

- **🚀 開始會議**：創建語音頻道並開始錄製
- **🔴 結束會議**：停止錄製並清理頻道
- **❌ 取消會議**：取消會議並通知參與者

### 🔔 自動提醒

系統會自動發送提醒：
- **24小時前提醒**：通知所有參與者
- **5分鐘前提醒**：最終提醒

### 🎥 會議錄製

- 會議開始時自動開始錄製
- 支援多機器人並行錄製
- 每個參與者獨立音軌
- 會議結束時自動停止錄製

### 🏠 自動化功能

- **語音頻道自動創建**：會議開始時在指定分類下創建
- **空閒自動結束**：語音頻道空閒1分鐘後自動結束會議
- **自動清理**：會議結束後自動刪除空的語音頻道

## 配置選項

在 `.env` 檔案中配置會議系統：

```env
# 會議系統啟用
MEETINGS_ENABLED=true

# 頻道設定
MEETINGS_SCHEDULING_CHANNELS=general,會議安排
MEETINGS_CATEGORY_NAME=會議
MEETINGS_ANNOUNCEMENT_CHANNEL_ID=your_channel_id

# AI 時間解析
MEETINGS_TIME_PARSER_AI_SERVICE=gemini
MEETINGS_TIME_PARSER_MODEL=gemini-2.0-flash

# 時區設定
MEETINGS_DEFAULT_TIMEZONE=Asia/Taipei

# 提醒設定
MEETINGS_REMINDER_24H_ENABLED=true
MEETINGS_REMINDER_5MIN_ENABLED=true

# 語音頻道設定
MEETINGS_AUTO_CREATE_VOICE_CHANNEL=true
MEETINGS_AUTO_START_RECORDING=true
MEETINGS_VOICE_CHANNEL_DELETE_DELAY=30

# 會議管理
MEETINGS_MAX_DURATION_HOURS=8
MEETINGS_ALLOW_USER_RESCHEDULE=true
MEETINGS_ALLOW_USER_CANCEL=true
```

## 使用範例

### 基本會議安排

```
/meet 明天下午2點 @Alice @Bob 每週例會 討論專案進度
```

### 公開會議

```
/meet 後天上午10點 公開 技術分享會 歡迎所有人參加
```

### 查看和管理

1. 使用 `/meetings` 查看所有會議
2. 複製會議ID
3. 使用 `/meeting_info <ID>` 查看詳情
4. 透過按鈕開始/結束/取消會議

## 注意事項

- 只有會議主辦人可以開始、結束或取消會議
- 自然語言解析支援繁體中文
- 錄製需要配置多個機器人 Token
- 語音頻道會在設定的分類下創建
- 會議結束後錄製檔案會自動保存

## 疑難排解

**時間解析失敗：**
- 檢查 AI 模型配置
- 使用更明確的時間表達式

**錄製無法開始：**
- 確認錄製機器人 Token 配置
- 檢查機器人權限

**提醒未發送：**
- 檢查提醒服務是否啟用
- 確認頻道權限設定 
import asyncio
import logging
import os
import subprocess
import threading
from queue import Queue
from typing import Optional, Dict, Any
from datetime import datetime

import discord

try:
    from discord.ext import voice_recv
    VOICE_RECV_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    VOICE_RECV_AVAILABLE = False
    voice_recv = None


# ===================== 🎧 MP3 轉換工具 =====================

def convert_pcm_to_mp3(pcm_path: str,
                       mp3_path: Optional[str] = None,
                       sample_rate: int = 48000,
                       channels: int = 2,
                       sample_format: str = "s16le") -> bool:
    """將 PCM 檔轉 MP3，使用 ffmpeg。"""
    if not mp3_path:
        mp3_path = os.path.splitext(pcm_path)[0] + ".mp3"

    command = [
        "ffmpeg",
        "-y",
        "-f", sample_format,
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "-i", pcm_path,
        mp3_path
    ]

    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[✔] 成功轉檔：{mp3_path}")
        # Clean up PCM file after successful conversion
        try:
            os.remove(pcm_path)
        except OSError:
            pass
        return True
    except subprocess.CalledProcessError:
        print(f"[✘] 轉檔失敗：{pcm_path}")
        return False


# ===================== 🎙️ 錄音器實作 =====================

class MultiUserRecorder(voice_recv.AudioSink if VOICE_RECV_AVAILABLE else object):
    """
    簡潔的多用戶錄音器，每個用戶獨立的 Queue 和處理線程，完全避免線程間競爭
    使用 discord-ext-voice-recv 官方 API 而非自製實現
    """
    
    def __init__(self, output_dir: str):
        if VOICE_RECV_AVAILABLE:
            super().__init__()
        
        self.output_dir = output_dir
        self.buffers = {}
        self.threads = {}
        self.lock = threading.Lock()
        self.logger = logging.getLogger(__name__)
        
        os.makedirs(output_dir, exist_ok=True)
        self.logger.info(f"🎙️ MultiUserRecorder initialized: {output_dir}")

    def wants_opus(self) -> bool:
        """使用原始 PCM 格式錄音，避免 Opus 解碼複雜性"""
        return False

    def write(self, user: discord.User, data):
        """
        為每個用戶創建獨立的隊列和處理線程
        完全並行處理，無共享資源衝突
        """
        with self.lock:
            if user.id not in self.buffers:
                # 為每個用戶創建獨立的隊列和線程
                self.buffers[user.id] = Queue()
                t = threading.Thread(
                    target=self._save_audio, 
                    args=(user.id, user.display_name),
                    daemon=True,
                    name=f"AudioSaver-{user.id}"
                )
                t.start()
                self.threads[user.id] = t
                self.logger.info(f"🎵 Started recording for user: {user.display_name} ({user.id})")
            
            # 非阻塞寫入到用戶專用隊列
            try:
                self.buffers[user.id].put_nowait(data.pcm)
            except:
                # 隊列滿時丟棄封包，避免阻塞
                pass

    def _save_audio(self, user_id: int, username: str):
        """
        用戶專用的音頻保存線程
        每個用戶完全獨立，無共享資源
        """
        pcm_path = os.path.join(self.output_dir, f"user_{user_id}_{username}.pcm")
        
        try:
            with open(pcm_path, "wb") as f:
                while True:
                    try:
                        # 10秒超時，如果沒有新數據則結束
                        chunk = self.buffers[user_id].get(timeout=10)
                        if chunk is None:  # Sentinel value to stop
                            break
                        f.write(chunk)
                    except:
                        # 超時或其他錯誤，結束該用戶的錄音
                        break
                        
            # 轉換為 MP3 並清理 PCM 文件
            if os.path.getsize(pcm_path) > 0:
                convert_pcm_to_mp3(pcm_path)
                self.logger.info(f"🎵 Completed recording for user: {username}")
            else:
                # 刪除空的 PCM 文件
                try:
                    os.remove(pcm_path)
                except OSError:
                    pass
                    
        except Exception as e:
            self.logger.error(f"❌ Error saving audio for user {username}: {e}")

    def cleanup(self):
        """
        清理所有資源，發送停止信號並等待線程結束
        """
        self.logger.info("🧹 Cleaning up MultiUserRecorder...")
        
        # 發送停止信號給所有用戶隊列
        for user_id in self.buffers:
            try:
                self.buffers[user_id].put_nowait(None)  # Sentinel value
            except:
                pass
        
        # 等待所有線程結束
        for user_id, thread in self.threads.items():
            try:
                thread.join(timeout=5.0)
                if thread.is_alive():
                    self.logger.warning(f"⚠️ Thread for user {user_id} did not finish in time")
            except Exception as e:
                self.logger.error(f"❌ Error joining thread for user {user_id}: {e}")
        
        self.logger.info("✅ MultiUserRecorder cleanup completed")


class MeetingRecorder:
    """
    會議錄製管理器，整合 MultiUserRecorder 到現有的會議系統
    保持所有現有功能：會議室、多bot、會議論壇
    """
    
    def __init__(self, bot, config) -> None:
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.active_recordings: Dict[int, Dict[str, Any]] = {}

    async def record_meeting_audio(self, voice_channel_id: int) -> None:
        """
        開始錄製會議音頻，使用新的 MultiUserRecorder 架構
        """
        try:
            guild = self.bot.guilds[0] if self.bot.guilds else None
            if not guild:
                self.logger.error("Bot not in any guild")
                return

            voice_channel = guild.get_channel(voice_channel_id)
            if not voice_channel:
                self.logger.error(f"Voice channel {voice_channel_id} not found")
                return

            # 創建錄音目錄
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # 使用專案根目錄下的 recordings 資料夾
            recordings_dir = os.path.join(os.getcwd(), "recordings")
            recording_dir = os.path.join(
                recordings_dir,
                f"recording_{voice_channel_id}_{timestamp}_simple"
            )
            
            # 加入語音頻道（使用 VoiceRecvClient）
            voice_client = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
            
            # 創建錄音器
            recorder = MultiUserRecorder(recording_dir)
            
            # 開始錄音
            voice_client.listen(recorder)
            
            # 儲存錄音信息
            self.active_recordings[voice_channel_id] = {
                'voice_client': voice_client,
                'recorder': recorder,
                'recording_dir': recording_dir,
                'start_time': datetime.now()
            }
            
            self.logger.info(f"🎙️ Started recording meeting in channel: {voice_channel.name}")
            
            # 等待直到頻道空閒或被手動停止
            await self._monitor_voice_channel(voice_channel, voice_client, recorder)
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start recording: {e}")
            await self._cleanup_recording(voice_channel_id)

    async def _monitor_voice_channel(self, voice_channel, voice_client, recorder):
        """
        監控語音頻道，當沒有用戶時自動停止錄音
        """
        empty_duration = 0
        max_empty_duration = 300  # 5 minutes of emptiness before stopping
        
        while voice_client.is_connected():
            try:
                # 檢查頻道中是否有用戶（排除機器人）
                human_members = [m for m in voice_channel.members if not m.bot]
                
                if not human_members:
                    empty_duration += 10
                    if empty_duration >= max_empty_duration:
                        self.logger.info("📭 Voice channel empty for 5 minutes, stopping recording")
                        break
                else:
                    empty_duration = 0
                    
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                self.logger.error(f"❌ Error monitoring voice channel: {e}")
                break
        
        # 停止錄音
        await self._stop_and_cleanup(voice_client, recorder)

    async def _stop_and_cleanup(self, voice_client, recorder):
        """
        停止錄音並清理資源
        """
        try:
            # 停止監聽
            if voice_client.is_connected():
                voice_client.stop_listening()
                
            # 清理錄音器
            if recorder:
                recorder.cleanup()
                
            # 斷開語音連接
            if voice_client.is_connected():
                await voice_client.disconnect()
                
            self.logger.info("🛑 Recording stopped and cleaned up")
            
        except Exception as e:
            self.logger.error(f"❌ Error during cleanup: {e}")

    async def stop_recording(self, voice_channel_id: int) -> bool:
        """
        手動停止指定頻道的錄音
        """
        if voice_channel_id not in self.active_recordings:
            self.logger.warning(f"No active recording for channel {voice_channel_id}")
            return False
            
        recording_info = self.active_recordings[voice_channel_id]
        voice_client = recording_info['voice_client']
        recorder = recording_info['recorder']
        
        await self._stop_and_cleanup(voice_client, recorder)
        await self._cleanup_recording(voice_channel_id)
        
        return True

    async def _cleanup_recording(self, voice_channel_id: int):
        """
        清理錄音記錄
        """
        if voice_channel_id in self.active_recordings:
            del self.active_recordings[voice_channel_id]

    def get_recording_status(self, voice_channel_id: int) -> dict:
        """
        獲取錄音狀態
        """
        if voice_channel_id in self.active_recordings:
            recording_info = self.active_recordings[voice_channel_id]
            return {
                'is_recording': True,
                'start_time': recording_info['start_time'],
                'recording_dir': recording_info['recording_dir']
            }
        else:
            return {'is_recording': False}

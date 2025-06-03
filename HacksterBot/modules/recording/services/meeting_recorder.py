import asyncio
import logging
import os
import time
import wave
from datetime import datetime
from typing import Dict

import discord

try:
    from discord.ext import voice_recv
    from discord import opus

    VOICE_RECV_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    VOICE_RECV_AVAILABLE = False
    voice_recv = None


class UserRecorder:
    """Handle recording for a single user."""

    def __init__(self, user_id: int, username: str, folder: str,
                 sample_rate: int, channels: int, sample_width: int,
                 session_start: float) -> None:
        self.user_id = user_id
        self.username = username
        self.folder = folder
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.session_start = session_start

        safe_name = "".join(c for c in username if c.isalnum() or c in ('_', '-'))
        self.filepath = os.path.join(folder, f"user_{user_id}_{safe_name}.wav")

        self.wav = wave.open(self.filepath, "wb")
        self.wav.setnchannels(channels)
        self.wav.setsampwidth(sample_width)
        self.wav.setframerate(sample_rate)

        self.join_time = None
        self.last_time = None

    def initialize(self, join_time: float) -> None:
        self.join_time = join_time
        self.last_time = join_time
        if join_time > self.session_start:
            gap_frames = int((join_time - self.session_start) * self.sample_rate)
            self._write_silence(gap_frames)

    def _write_silence(self, frames: int) -> None:
        if frames <= 0:
            return
        self.wav.writeframes(b"\x00" * frames * self.channels * self.sample_width)

    def add_audio(self, data: bytes, timestamp: float) -> None:
        if self.last_time is None:
            self.initialize(timestamp)
        else:
            gap = timestamp - self.last_time
            if gap > 0.1:
                self._write_silence(int(gap * self.sample_rate))
        self.wav.writeframes(data)
        self.last_time = timestamp

    def finalize(self, session_end: float) -> None:
        if self.last_time is None:
            self.initialize(session_end)
        if session_end > self.last_time:
            self._write_silence(int((session_end - self.last_time) * self.sample_rate))
        self.wav.close()


class RecordingSink(voice_recv.AudioSink if VOICE_RECV_AVAILABLE else object):
    """Audio sink that writes individual tracks for each user."""

    def __init__(self, folder: str) -> None:
        if VOICE_RECV_AVAILABLE:
            super().__init__()
        self.folder = folder
        self.start_time = time.time()
        self.sample_rate = 48000
        self.channels = 2
        self.sample_width = 2
        self.recorders: Dict[int, UserRecorder] = {}
        self.decoders: Dict[int, opus.Decoder] = {}
        self.logger = logging.getLogger(__name__)
        os.makedirs(folder, exist_ok=True)

    def wants_opus(self) -> bool:
        return True

    def write(self, user: discord.User, voice_data) -> None:  # type: ignore[override]
        if not voice_data or not VOICE_RECV_AVAILABLE:
            return


        opus_frame = getattr(voice_data, "opus", None)
        if not opus_frame:
            return

        decoder = self.decoders.get(user.id)
        if decoder is None:
            try:
                decoder = opus.Decoder()
            except Exception as e:  # pragma: no cover - decoder init shouldn't fail
                self.logger.error("Failed to create Opus decoder: %s", e)
                return
            self.decoders[user.id] = decoder

        try:
            pcm = decoder.decode(opus_frame)
        except opus.OpusError as e:
            # Ignore decode errors but log at debug level for diagnostics
            self.logger.debug("Opus decode failed for user %s: %s", user.id, e)
            return


        pcm = getattr(voice_data, "pcm", None) or getattr(voice_data, "data", None)
        if not pcm:
            return

        now = time.time()
        recorder = self.recorders.get(user.id)
        if recorder is None:
            username = user.display_name or user.name or str(user.id)
            recorder = UserRecorder(
                user.id,
                username,
                self.folder,
                self.sample_rate,
                self.channels,
                self.sample_width,
                self.start_time,
            )
            recorder.initialize(now)
            self.recorders[user.id] = recorder
        recorder.add_audio(pcm, now)


    @voice_recv.AudioSink.listener()
    def on_voice_member_disconnect(self, member: discord.Member, ssrc: int | None) -> None:
        if member:
            self.mark_user_leave(member.id, time.time())

    def mark_user_leave(self, user_id: int, leave_time: float) -> None:
        recorder = self.recorders.get(user_id)
        if recorder:
            recorder.last_time = leave_time

    def mark_user_rejoin(self, user_id: int, rejoin_time: float) -> None:
        recorder = self.recorders.get(user_id)
        if recorder and recorder.last_time:
            gap = rejoin_time - recorder.last_time
            if gap > 0:
                recorder._write_silence(int(gap * recorder.sample_rate))
            recorder.last_time = rejoin_time

    def cleanup(self) -> None:
        end_time = time.time()
        for recorder in self.recorders.values():
            recorder.finalize(end_time)


class MeetingRecorder:
    """Manage recording of a Discord voice channel."""

    def __init__(self, bot, config) -> None:
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.audio_sink: RecordingSink | None = None

    async def record_meeting_audio(self, voice_channel_id: int) -> None:
        if not VOICE_RECV_AVAILABLE:
            self.logger.error("discord-ext-voice-recv not installed")
            return

        meeting_info = self.bot.meeting_voice_channel_info.get(voice_channel_id, {})

        guild = self.bot.guilds[0] if self.bot.guilds else None
        if not guild:
            self.logger.error("Guild not found for recording")
            return

        voice_channel = guild.get_channel(voice_channel_id)
        if not isinstance(voice_channel, discord.VoiceChannel):
            self.logger.error(f"Voice channel {voice_channel_id} not found")
            return

        voice_client = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
        folder = os.path.join(
            "recordings",
            f"recording_{voice_channel_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        )
        self.audio_sink = RecordingSink(folder)
        voice_client.listen(self.audio_sink)

        meeting_info.update(
            {
                "recording_folder": folder,
                "recording_start_time": time.time(),
                "voice_client": voice_client,
                "audio_sink": self.audio_sink,
            }
        )

        self.logger.info(f"Started recording voice channel {voice_channel.name}")
        try:
            while True:
                await asyncio.sleep(5)
                channel = guild.get_channel(voice_channel_id)
                if not channel or not any(m for m in channel.members if not m.bot):
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await self._stop_and_cleanup(voice_client)
            self.logger.info(f"Recording finished: files saved in {folder}")

    async def _stop_and_cleanup(self, voice_client) -> None:
        try:
            if voice_client and voice_client.is_connected():
                if hasattr(voice_client, "stop_listening"):
                    voice_client.stop_listening()
                await voice_client.disconnect()
        except Exception:
            pass

        if self.audio_sink:
            self.audio_sink.cleanup()

    async def stop_recording(self, voice_channel_id: int) -> bool:
        meeting_info = self.bot.meeting_voice_channel_info.get(voice_channel_id, {})
        voice_client = meeting_info.get("voice_client")
        if not voice_client:
            self.logger.warning(f"No active recording for channel {voice_channel_id}")
            return False

        if hasattr(voice_client, "stop_listening"):
            voice_client.stop_listening()
        return True

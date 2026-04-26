import logging
from typing import Any, Dict, Optional

from backend.config import settings

logger = logging.getLogger(__name__)


class SpeechService:
    """Speech-to-text adapter based on Feishu ASR only."""

    def __init__(self):
        self.enabled = settings.VOICE_TRANSCRIPTION_ENABLED

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and settings.FEISHU_ASR_ENABLED)

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "voice.ogg",
        content_type: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"success": False, "error": "Voice transcription is disabled."}
        if not audio_bytes:
            return {"success": False, "error": "Audio file is empty."}
        if not settings.FEISHU_ASR_ENABLED:
            return {"success": False, "error": "Feishu ASR is disabled."}

        return await self._transcribe_with_feishu(audio_bytes, filename, content_type)

    async def _transcribe_with_feishu(
        self,
        audio_bytes: bytes,
        filename: str,
        content_type: Optional[str],
    ) -> Dict[str, Any]:
        try:
            from backend.services.lark_bot_service import lark_bot_service

            if not lark_bot_service.is_configured:
                return {"success": False, "error": "Feishu ASR is enabled but Lark OpenAPI is not configured."}

            guessed_format = self._guess_feishu_format(filename, content_type)
            trial_formats = [guessed_format, "pcm"]
            seen = set()
            errors = []

            for audio_format in trial_formats:
                if audio_format in seen:
                    continue
                seen.add(audio_format)
                result = await lark_bot_service.recognize_speech_file(
                    audio_bytes=audio_bytes,
                    file_id=filename,
                    audio_format=audio_format,
                )
                if result.get("success"):
                    return result
                errors.append(f"{audio_format}: {result.get('error') or 'unknown error'}")

            return {"success": False, "error": " ; ".join(errors)}
        except Exception as exc:
            logger.exception("Feishu ASR failed")
            return {"success": False, "error": str(exc)}

    def _guess_feishu_format(self, filename: str, content_type: Optional[str]) -> str:
        value = f"{filename or ''} {content_type or ''}".lower()
        if "wav" in value:
            return "wav"
        if "pcm" in value:
            return "pcm"
        if "mp3" in value or "mpeg" in value:
            return "mp3"
        if "m4a" in value or "mp4" in value:
            return "m4a"
        if "opus" in value or "ogg" in value:
            return "opus"
        return settings.FEISHU_ASR_FORMAT


speech_service = SpeechService()

from __future__ import annotations

import numpy as np
from faster_whisper import WhisperModel


class STT:
    """Speech-to-text using faster-whisper with optimized settings."""

    def __init__(
        self,
        model_size_or_path: str = "tiny.en",
        download_root: str | None = None,
        language: str = "en",
    ):
        self.model = WhisperModel(
            model_size_or_path,
            device="cpu",
            compute_type="int8",
            download_root=download_root,
            cpu_threads=4,
        )
        self.language = language

    def transcribe(self, audio_data: np.ndarray, language: str | None = None) -> str:
        """Transcribe float32 audio data at 16kHz."""
        lang = language or self.language
        segments, info = self.model.transcribe(
            audio_data,
            beam_size=5,
            language=lang,
            temperature=0.0,
            condition_on_previous_text=True,
            vad_filter=False,
        )
        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())
        return " ".join(text_parts).strip()

    def transcribe_with_timestamps(self, audio_data: np.ndarray) -> list[dict]:
        """Transcribe and return segments with start/end timestamps."""
        segments, info = self.model.transcribe(
            audio_data,
            beam_size=5,
            language=self.language,
            word_timestamps=True,
        )
        results = []
        for segment in segments:
            results.append({
                "text": segment.text.strip(),
                "start": segment.start,
                "end": segment.end,
                "words": [
                    {"word": w.word, "start": w.start, "end": w.end, "confidence": w.probability}
                    for w in (segment.words or [])
                ],
            })
        return results

    def transcribe_file(self, file_path: str) -> str:
        """Transcribe an audio file directly."""
        segments, info = self.model.transcribe(
            file_path,
            beam_size=5,
            language=self.language,
        )
        return " ".join(s.text.strip() for s in segments).strip()

from __future__ import annotations

import random
import re
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
from piper import PiperVoice
from piper.config import SynthesisConfig


class TTS:
    """Text-to-speech using Piper with Indian English voice and humanized output."""

    def __init__(self, model_path: str, config_path: str):
        self.voice = PiperVoice.load(model_path, config_path)
        self._lock = threading.Lock()
        self._is_speaking = False
        self._stop_event = threading.Event()
        self.sample_rate = self.voice.config.sample_rate

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    def _preprocess_text(self, text: str) -> str:
        """Clean and normalize text for better TTS output."""
        text = text.strip()
        if not text:
            return ""
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"#{1,6}\s*", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"---", " to ", text)
        text = re.sub(r"\n{2,}", ". ", text)
        text = text.replace("\n", ". ")
        text = text.replace("e.g.,", "for example,")
        text = text.replace("i.e.,", "that is,")
        text = text.replace("etc.", "and so on.")
        text = text.replace("vs.", "versus")
        text = re.sub(r"(\d+)%", r"\1 percent", text)
        text = re.sub(r"(\d+)x(\d+)", r"\1 by \2", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _split_into_sentences(self, text: str) -> list[str]:
        """Split text into speakable sentences."""
        text = self._preprocess_text(text)
        if not text:
            return []
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in sentences if s.strip()]

    def _synthesize(self, text: str) -> np.ndarray | None:
        """Synthesize text to audio array."""
        try:
            ls = random.uniform(1.0, 1.15)
            ns = random.uniform(0.65, 0.8)
            nw = random.uniform(0.75, 0.9)
            syn_config = SynthesisConfig(
                length_scale=ls,
                noise_scale=ns,
                noise_w_scale=nw,
            )
            audio_stream = self.voice.synthesize(text, syn_config=syn_config)
            chunks = []
            for chunk in audio_stream:
                if hasattr(chunk, "audio_int16_array"):
                    chunks.append(chunk.audio_int16_array.astype(np.float32) / 32768.0)
            if chunks:
                return np.concatenate(chunks)
        except Exception:
            try:
                audio_stream = self.voice.synthesize(text)
                chunks = []
                for chunk in audio_stream:
                    if hasattr(chunk, "audio_int16_array"):
                        chunks.append(chunk.audio_int16_array.astype(np.float32) / 32768.0)
                if chunks:
                    return np.concatenate(chunks)
            except Exception:
                pass
        return None

    def speak(self, text: str) -> None:
        """Synthesize and play audio (blocking)."""
        text = self._preprocess_text(text)
        if not text:
            return
        with self._lock:
            self._is_speaking = True
            self._stop_event.clear()
            try:
                audio = self._synthesize(text)
                if audio is not None and not self._stop_event.is_set():
                    sd.play(audio, self.sample_rate)
                    sd.wait()
            finally:
                self._is_speaking = False

    def speak_stream(self, text: str) -> None:
        """Synthesize and play text sentence by sentence for lower latency."""
        sentences = self._split_into_sentences(text)
        if not sentences:
            return
        with self._lock:
            self._is_speaking = True
            self._stop_event.clear()
            all_audio = []
            for sentence in sentences:
                if self._stop_event.is_set():
                    break
                audio = self._synthesize(sentence)
                if audio is not None:
                    all_audio.append(audio)
                    sd.play(audio, self.sample_rate)
                    sd.wait()
            self._is_speaking = False

    def stop(self) -> None:
        """Stop current speech."""
        self._stop_event.set()
        try:
            sd.stop()
        except Exception:
            pass
        self._is_speaking = False

    def speak_async(self, text: str, stream: bool = True) -> None:
        """Synthesize and play audio in a background thread."""
        target = self.speak_stream if stream else self.speak
        threading.Thread(target=target, args=(text,), daemon=True).start()

    def save_to_file(self, text: str, output_path: str) -> bool:
        """Synthesize text and save to WAV file."""
        text = self._preprocess_text(text)
        if not text:
            return False
        audio = self._synthesize(text)
        if audio is None:
            return False
        import wave
        import struct
        audio_int16 = (audio * 32767).astype(np.int16)
        with wave.open(output_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_int16.tobytes())
        return True


if __name__ == "__main__":
    BASE = Path(__file__).parent.parent
    tts = TTS(
        str(BASE / "assets/models/piper/en_IN_voice.onnx"),
        str(BASE / "assets/models/piper/en_IN_voice.onnx.json"),
    )
    tts.speak("I'm checking the data for you now. Just a moment.")

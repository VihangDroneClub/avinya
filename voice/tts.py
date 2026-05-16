from __future__ import annotations

import asyncio
import io
import random
import re
import tempfile
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd


class EdgeTTS:
    """High-quality Indian English female voice using Microsoft Edge TTS (free).

    Uses en-IN-NeerjaNeural — a warm, natural young Indian female voice.
    Requires internet connection. Falls back to Piper if offline.
    """

    VOICE = "en-IN-NeerjaNeural"
    RATE = "+0%"
    PITCH = "+2Hz"
    VOLUME = "+0%"

    def __init__(self):
        self._available = None
        self._check_availability()

    def _check_availability(self):
        try:
            import edge_tts
            self._available = True
        except ImportError:
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    def _preprocess_for_ssml(self, text: str) -> str:
        """Convert text to SSML with natural prosody for Indian English."""
        text = text.strip()
        text = re.sub(r"\*\*([^*]+)\*\*", r"<emphasis level='moderate'>\1</emphasis>", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"#{1,6}\s*", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"---", " to ", text)
        text = text.replace("\n\n", "<break time='500ms'/>")
        text = text.replace("\n", "<break time='250ms'/>")
        text = text.replace("e.g.,", "for example,")
        text = text.replace("i.e.,", "that is,")
        text = text.replace("etc.", "and so on.")
        text = text.replace("vs.", "versus")
        text = re.sub(r"(\d+)%", r"\1 percent", text)
        text = re.sub(r"(\d+)x(\d+)", r"\1 by \2", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    async def _synthesize_async(self, text: str) -> bytes | None:
        """Synthesize text to audio bytes using edge-tts."""
        if not self._available:
            return None
        try:
            import edge_tts
            communicate = edge_tts.Communicate(
                text,
                self.VOICE,
                rate=self.RATE,
                pitch=self.PITCH,
                volume=self.VOLUME,
            )
            audio_data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]
            return audio_data if audio_data else None
        except Exception:
            return None

    def synthesize(self, text: str) -> bytes | None:
        """Synchronous wrapper for async synthesis."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self._synthesize_async(text))
            finally:
                loop.close()
        except Exception:
            return None

    def synthesize_to_file(self, text: str, output_path: str) -> bool:
        """Synthesize and save as MP3 file."""
        if not self._available:
            return False
        try:
            import edge_tts
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    edge_tts.Communicate(
                        text,
                        self.VOICE,
                        rate=self.RATE,
                        pitch=self.PITCH,
                    ).save(output_path)
                )
                return True
            finally:
                loop.close()
        except Exception:
            return False


class PiperTTS:
    """Offline TTS using Piper. Fallback when Edge TTS is unavailable."""

    def __init__(self, model_path: str, config_path: str):
        from piper import PiperVoice
        self.voice = PiperVoice.load(model_path, config_path)
        self.sample_rate = self.voice.config.sample_rate

    def synthesize(self, text: str) -> np.ndarray | None:
        """Synthesize text to audio array."""
        try:
            from piper.config import SynthesisConfig
            ls = random.uniform(1.0, 1.15)
            ns = random.uniform(0.65, 0.8)
            nw = random.uniform(0.75, 0.9)
            syn_config = SynthesisConfig(length_scale=ls, noise_scale=ns, noise_w_scale=nw)
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


class TTS:
    """Unified TTS with Edge TTS (primary) and Piper (fallback).

    Edge TTS uses en-IN-NeerjaNeural — a warm, natural young Indian female voice.
    Automatically falls back to Piper when offline.
    """

    def __init__(
        self,
        piper_model_path: str | None = None,
        piper_config_path: str | None = None,
        prefer_edge: bool = True,
    ):
        self._lock = threading.Lock()
        self._is_speaking = False
        self._stop_event = threading.Event()
        self._use_edge = prefer_edge
        self.sample_rate = 24000

        self.edge_tts = EdgeTTS() if prefer_edge else None
        self.piper_tts = None
        if piper_model_path and piper_config_path:
            try:
                self.piper_tts = PiperTTS(piper_model_path, piper_config_path)
            except Exception:
                pass

        if self.edge_tts and self.edge_tts.is_available:
            print("[TTS] Using Edge TTS (en-IN-NeerjaNeural) — young Indian female voice")
        elif self.piper_tts:
            print("[TTS] Using Piper TTS (offline fallback)")
        else:
            print("[TTS] WARNING: No TTS engine available")

    def _active_engine(self):
        if self._use_edge and self.edge_tts and self.edge_tts.is_available:
            return "edge"
        if self.piper_tts:
            return "piper"
        return None

    def _preprocess_text(self, text: str) -> str:
        """Clean text for speech output."""
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
        text = self._preprocess_text(text)
        if not text:
            return []
        return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

    def _synthesize_edge(self, text: str) -> np.ndarray | None:
        """Synthesize using Edge TTS and return audio array."""
        if not self.edge_tts or not self.edge_tts.is_available:
            return None
        audio_bytes = self.edge_tts.synthesize(text)
        if audio_bytes is None:
            return None
        try:
            import pydub
            audio_segment = pydub.AudioSegment.from_mp3(io.BytesIO(audio_bytes))
            samples = np.array(audio_segment.get_array_of_samples(), dtype=np.float32)
            samples = samples / 32768.0
            self.sample_rate = audio_segment.frame_rate
            return samples
        except ImportError:
            try:
                import wave
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp.write(audio_bytes)
                    tmp.flush()
                    import subprocess
                    wav_path = tmp.name.replace(".mp3", ".wav")
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", tmp.name, "-ar", "24000", "-ac", "1", wav_path],
                        capture_output=True,
                        timeout=30,
                    )
                    with wave.open(wav_path, "rb") as wf:
                        frames = wf.readframes(wf.getnframes())
                        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                        self.sample_rate = wf.getframerate()
                    Path(wav_path).unlink(missing_ok=True)
                    return samples
            except Exception:
                return None

    def _synthesize_piper(self, text: str) -> np.ndarray | None:
        if not self.piper_tts:
            return None
        return self.piper_tts.synthesize(text)

    def speak(self, text: str) -> None:
        """Synthesize and play audio (blocking)."""
        text = self._preprocess_text(text)
        if not text:
            return
        with self._lock:
            self._is_speaking = True
            self._stop_event.clear()
            try:
                engine = self._active_engine()
                if engine == "edge":
                    audio = self._synthesize_edge(text)
                elif engine == "piper":
                    audio = self._synthesize_piper(text)
                else:
                    return
                if audio is not None and len(audio) > 0 and not self._stop_event.is_set():
                    sd.play(audio, self.sample_rate)
                    sd.wait()
            finally:
                self._is_speaking = False

    def speak_stream(self, text: str) -> None:
        """Synthesize and play sentence by sentence for lower latency."""
        sentences = self._split_into_sentences(text)
        if not sentences:
            return
        with self._lock:
            self._is_speaking = True
            self._stop_event.clear()
            for sentence in sentences:
                if self._stop_event.is_set():
                    break
                self._play_sentence(sentence)
            self._is_speaking = False

    def _play_sentence(self, text: str) -> None:
        """Play a single sentence."""
        engine = self._active_engine()
        if engine == "edge":
            audio = self._synthesize_edge(text)
        elif engine == "piper":
            audio = self._synthesize_piper(text)
        else:
            return
        if audio is not None and len(audio) > 0 and not self._stop_event.is_set():
            sd.play(audio, self.sample_rate)
            sd.wait()

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
        """Synthesize text and save as audio file."""
        text = self._preprocess_text(text)
        if not text:
            return False
        if self._active_engine() == "edge" and self.edge_tts:
            return self.edge_tts.synthesize_to_file(text, output_path)
        if self._active_engine() == "piper" and self.piper_tts:
            audio = self._synthesize_piper(text)
            if audio is None:
                return False
            import wave
            audio_int16 = (audio * 32767).astype(np.int16)
            with wave.open(output_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_int16.tobytes())
            return True
        return False


if __name__ == "__main__":
    BASE = Path(__file__).parent.parent
    tts = TTS(
        piper_model_path=str(BASE / "assets/models/piper/en_IN_voice.onnx"),
        piper_config_path=str(BASE / "assets/models/piper/en_IN_voice.onnx.json"),
        prefer_edge=True,
    )
    tts.speak("Hi, I'm Avinya. I'm here to help you with everything about the club.")

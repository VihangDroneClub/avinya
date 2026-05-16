from __future__ import annotations

import queue

import numpy as np
import sounddevice as sd
import openwakeword
from openwakeword.model import Model


class WakeWordDetector:
    """Detects wake words using openWakeWord with configurable keywords and sensitivity."""

    def __init__(
        self,
        model_path: str | None = None,
        keywords: list[str] | None = None,
        threshold: float = 0.5,
        sample_rate: int = 16000,
    ):
        if keywords is None:
            keywords = ["hey_jarvis"]

        self.keywords = keywords
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.chunk_size = 1280
        self.audio_queue: queue.Queue = queue.Queue()
        self._stream = None

        model_paths = []
        for kw in keywords:
            pretrained = openwakeword.get_pretrained_model_paths()
            matches = [p for p in pretrained if kw.replace(" ", "_") in p or kw in p]
            if matches:
                model_paths.append(matches[0])

        if not model_paths:
            fallback = openwakeword.get_pretrained_model_paths()
            if fallback:
                model_paths = [fallback[0]]
            else:
                raise RuntimeError("No openWakeWord models found. Install with: pip install openwakeword")

        self.model = Model(wakeword_model_paths=model_paths)
        self.model_names = [m.replace(".onnx", "").split("/")[-1] for m in model_paths]

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            pass
        self.audio_queue.put(indata.copy())

    def listen_for_wake_word(self, timeout: float | None = None) -> str | None:
        """Block until a wake word is detected. Returns the detected keyword or None on timeout."""
        import time
        start = time.time()

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.chunk_size,
            callback=self._audio_callback,
        ):
            while True:
                if timeout and (time.time() - start) > timeout:
                    return None

                try:
                    audio_chunk = self.audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                self.model.predict(audio_chunk.flatten())

                for mdl in self.model.prediction_buffer:
                    scores = list(self.model.prediction_buffer[mdl])
                    if scores[-1] > self.threshold:
                        return mdl

    def listen_async(self, callback) -> None:
        """Listen for wake word in background and call callback(keyword) when detected."""
        import threading

        def _listen():
            while True:
                keyword = self.listen_for_wake_word()
                if keyword:
                    callback(keyword)

        threading.Thread(target=_listen, daemon=True).start()

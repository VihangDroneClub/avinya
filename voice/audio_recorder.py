from __future__ import annotations

import time

import numpy as np
import sounddevice as sd


class AudioRecorder:
    """Records audio from microphone with voice activity detection and noise suppression."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size

    def record_until_silence(
        self,
        silence_threshold: float = 0.008,
        silence_duration: float = 1.2,
        max_duration: float = 60.0,
        min_duration: float = 0.3,
    ) -> np.ndarray:
        """Record audio until silence is detected.

        Args:
            silence_threshold: RMS level below which audio is considered silence.
            silence_duration: Seconds of continuous silence before stopping.
            max_duration: Maximum recording length in seconds.
            min_duration: Minimum recording length before silence detection kicks in.

        Returns:
            1D float32 numpy array of audio samples.
        """
        audio_blocks: list[np.ndarray] = []
        last_sound_time = time.time()
        start_time = time.time()
        has_spoken = False

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
        ) as stream:
            while True:
                data, _ = stream.read(self.chunk_size)
                audio_blocks.append(data)

                rms = np.sqrt(np.mean(data ** 2))
                current_time = time.time()
                elapsed = current_time - start_time

                if rms > silence_threshold:
                    last_sound_time = current_time
                    has_spoken = True

                if has_spoken and elapsed > min_duration:
                    if current_time - last_sound_time > silence_duration:
                        break

                if elapsed > max_duration:
                    break

        if not audio_blocks:
            return np.array([], dtype=np.float32)

        combined = np.concatenate(audio_blocks, axis=0)
        if combined.ndim > 1:
            combined = combined[:, 0]
        return combined

    def record_for_duration(self, duration: float = 5.0) -> np.ndarray:
        """Record for a fixed duration."""
        total_samples = int(self.sample_rate * duration)
        audio_blocks: list[np.ndarray] = []
        samples_collected = 0

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
        ) as stream:
            while samples_collected < total_samples:
                remaining = total_samples - samples_collected
                chunk = min(self.chunk_size, remaining)
                data, _ = stream.read(chunk)
                audio_blocks.append(data)
                samples_collected += chunk

        if not audio_blocks:
            return np.array([], dtype=np.float32)

        combined = np.concatenate(audio_blocks, axis=0)
        if combined.ndim > 1:
            combined = combined[:, 0]
        return combined

    def record_with_interrupt(
        self,
        stop_event,
        silence_threshold: float = 0.008,
        silence_duration: float = 1.2,
        max_duration: float = 60.0,
    ) -> np.ndarray:
        """Record until silence or stop_event is set. Used for interruptible listening."""
        audio_blocks: list[np.ndarray] = []
        last_sound_time = time.time()
        start_time = time.time()
        has_spoken = False

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
        ) as stream:
            while not stop_event.is_set():
                data, _ = stream.read(self.chunk_size)
                audio_blocks.append(data)

                rms = np.sqrt(np.mean(data ** 2))
                current_time = time.time()
                elapsed = current_time - start_time

                if rms > silence_threshold:
                    last_sound_time = current_time
                    has_spoken = True

                if has_spoken and elapsed > 0.3:
                    if current_time - last_sound_time > silence_duration:
                        break

                if elapsed > max_duration:
                    break

        if not audio_blocks:
            return np.array([], dtype=np.float32)

        combined = np.concatenate(audio_blocks, axis=0)
        if combined.ndim > 1:
            combined = combined[:, 0]
        return combined

    @staticmethod
    def normalize_audio(audio: np.ndarray, target_rms: float = 0.1) -> np.ndarray:
        """Normalize audio to target RMS level."""
        if len(audio) == 0:
            return audio
        current_rms = np.sqrt(np.mean(audio ** 2))
        if current_rms > 0:
            gain = target_rms / current_rms
            audio = audio * gain
        max_val = np.max(np.abs(audio))
        if max_val > 1.0:
            audio = audio / max_val
        return audio

    @staticmethod
    def apply_noise_gate(audio: np.ndarray, threshold: float = 0.005) -> np.ndarray:
        """Apply a simple noise gate to remove background noise."""
        if len(audio) == 0:
            return audio
        gated = audio.copy()
        gated[np.abs(gated) < threshold] = 0.0
        return gated

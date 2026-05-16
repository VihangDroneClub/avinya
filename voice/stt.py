from __future__ import annotations

from pathlib import Path
import numpy as np
from faster_whisper import WhisperModel

class STT:
    def __init__(self, model_size_or_path: str, download_root: str | None = None):
        # We specify CPU and int8 for maximum speed on your machine
        self.model = WhisperModel(
            model_size_or_path, 
            device="cpu", 
            compute_type="int8",
            download_root=download_root
        )
        
    def transcribe(self, audio_data: np.ndarray) -> str:
        """Transcribe float32 audio data."""
        segments, info = self.model.transcribe(audio_data, beam_size=5)
        
        text = ""
        for segment in segments:
            text += segment.text
            
        return text.strip()

if __name__ == "__main__":
    # Test would require audio data
    pass

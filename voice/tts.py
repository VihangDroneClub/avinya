from __future__ import annotations

import random
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from piper import PiperVoice
from piper.config import SynthesisConfig

class TTS:
    def __init__(self, model_path: str, config_path: str):
        self.voice = PiperVoice.load(model_path, config_path)
        self._lock = threading.Lock()
        
    def speak(self, text: str, length_scale: float | None = None, noise_scale: float | None = None, noise_w: float | None = None):
        """Synthesize and play audio (blocking) with dynamic humanisation."""
        if not text.strip():
            return
            
        with self._lock:
            # Humanisation defaults if not provided
            # We add a tiny bit of randomness to make it feel less robotic
            ls = length_scale or random.uniform(1.05, 1.15) 
            ns = noise_scale or random.uniform(0.7, 0.8)
            nw = noise_w or random.uniform(0.8, 0.9)
            
            try:
                # Package into config object
                syn_config = SynthesisConfig(
                    length_scale=ls,
                    noise_scale=ns,
                    noise_w_scale=nw
                )
                
                # Use ONLY the allowed keyword arguments
                audio_stream = self.voice.synthesize(text, syn_config=syn_config)
                
                audio_chunks = []
                for chunk in audio_stream:
                    if hasattr(chunk, 'audio_int16_array'):
                        audio_chunks.append(chunk.audio_int16_array)
                        
                if not audio_chunks:
                    return
                    
                audio_data = np.concatenate(audio_chunks)
                
                # Play
                sd.play(audio_data, self.voice.config.sample_rate)
                sd.wait()
                
                # Natural pause after speaking
                time.sleep(0.2)
                
            except Exception as e:
                print(f"[TTS Error] {e}")
                # Fallback to absolute simplest call if config fails
                try:
                    audio_stream = self.voice.synthesize(text)
                    audio_chunks = [c.audio_int16_array for c in audio_stream]
                    audio_data = np.concatenate(audio_chunks)
                    sd.play(audio_data, self.voice.config.sample_rate)
                    sd.wait()
                except:
                    pass

    def speak_async(self, text: str, **kwargs):
        """Synthesize and play audio in a background thread."""
        threading.Thread(target=self.speak, args=(text,), kwargs=kwargs, daemon=True).start()

if __name__ == "__main__":
    # Test script
    BASE = Path(__file__).parent.parent
    tts = TTS(
        str(BASE / "assets/models/piper/en_IN_voice.onnx"),
        str(BASE / "assets/models/piper/en_IN_voice.onnx.json")
    )
    tts.speak("I'm checking the data for you now. Just a moment.")

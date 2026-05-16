from __future__ import annotations

import queue
import numpy as np
import sounddevice as sd
from openwakeword.model import Model
import openwakeword

class WakeWordDetector:
    def __init__(self, model_path: str | None = None, keywords: list[str] = ["jarvis"]):
        # Find the pretrained hey_jarvis model path
        jarvis_paths = [p for p in openwakeword.get_pretrained_model_paths() if "hey_jarvis" in p]
        if not jarvis_paths:
            raise RuntimeError("Could not find pretrained 'hey_jarvis' model in openwakeword.")
            
        self.model = Model(
            wakeword_model_paths=[jarvis_paths[0]]
        )
        self.sample_rate = 16000
        self.audio_queue = queue.Queue()
        self.chunk_size = 1280 # Standard chunk size for openwakeword

    def _audio_callback(self, indata, frames, time, status):
        """This is called from a separate thread for every audio block."""
        if status:
            print(f"Audio status: {status}")
        self.audio_queue.put(indata.copy())

    def listen_for_wake_word(self):
        """Block until a wake word is detected."""
        print("Listening for 'Hey Jarvis' (openWakeWord)...")
        
        # Open the input stream
        with sd.InputStream(samplerate=self.sample_rate, 
                           channels=1, 
                           dtype='int16',
                           blocksize=self.chunk_size,
                           callback=self._audio_callback):
            while True:
                # Get audio chunk
                audio_chunk = self.audio_queue.get()
                
                # Predict (openwakeword expects (chunk_size,) or (1, chunk_size))
                # audio_chunk from sd is (chunk_size, 1)
                self.model.predict(audio_chunk.flatten())
                
                # Check results
                for mdl in self.model.prediction_buffer:
                    # Get the most recent prediction
                    scores = list(self.model.prediction_buffer[mdl])
                    if scores[-1] > 0.5: # Sensitivity threshold
                        print(f"\n[Detected] Wake word triggered with score {scores[-1]:.2f}")
                        return mdl

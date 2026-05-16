from __future__ import annotations

import numpy as np
import sounddevice as sd
import time

class AudioRecorder:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate

    def record_until_silence(self, silence_threshold: float = 0.01, silence_duration: float = 1.5):
        """Record audio from mic until silence is detected."""
        print("Recording command...")
        
        chunk_size = 1024
        audio_blocks = []
        
        start_time = time.time()
        last_sound_time = time.time()
        
        # Open a stream for recording
        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='float32') as stream:
            while True:
                data, overflowed = stream.read(chunk_size)
                audio_blocks.append(data)
                
                # Check for silence
                # Use RMS to determine if there's sound
                rms = np.sqrt(np.mean(data**2))
                
                current_time = time.time()
                if rms > silence_threshold:
                    last_sound_time = current_time
                
                # If we've been silent for long enough, stop
                if current_time - last_sound_time > silence_duration:
                    break
                
                # Safety timeout (30 seconds)
                if current_time - start_time > 30:
                    break
                    
        return np.concatenate(audio_blocks, axis=0)

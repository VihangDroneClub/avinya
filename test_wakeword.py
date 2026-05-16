import sounddevice as sd
import numpy as np
from openwakeword.model import Model
import openwakeword
import queue

def test_openwakeword():
    # Load model
    jarvis_paths = [p for p in openwakeword.get_pretrained_model_paths() if "hey_jarvis" in p]
    print(f"Loading openWakeWord model from: {jarvis_paths[0]}...")
    owwModel = Model(wakeword_model_paths=[jarvis_paths[0]])
    
    sample_rate = 16000
    chunk_size = 1280
    audio_queue = queue.Queue()

    def callback(indata, frames, time, status):
        audio_queue.put(indata.copy())

    print("\n--- openWakeWord Test ---")
    print("Say 'Hey Jarvis' clearly.")
    print("Press Ctrl+C to stop.\n")

    with sd.InputStream(samplerate=sample_rate, channels=1, dtype='int16',
                        blocksize=chunk_size, callback=callback):
        while True:
            audio_chunk = audio_queue.get()
            audio_data = audio_chunk.flatten()
            
            owwModel.predict(audio_data)
            
            for mdl in owwModel.prediction_buffer:
                scores = list(owwModel.prediction_buffer[mdl])
                score = scores[-1]
                if score > 0.1: # Show low scores for debugging
                    print(f"Score: {score:.4f}  ", end='\r')
                
                if score > 0.5:
                    print(f"\n*** WAKE WORD DETECTED (Score: {score:.4f}) ***")

if __name__ == "__main__":
    try:
        test_openwakeword()
    except KeyboardInterrupt:
        print("\nStopped.")

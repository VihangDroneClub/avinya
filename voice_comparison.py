from __future__ import annotations
from pathlib import Path
from voice.tts import TTS
import time

def compare_voices():
    base_dir = Path(__file__).parent
    
    # 1. Spicor (Original/Raw)
    print("\n--- Playing Voice 1: Spicor (ORIGINAL/RAW) ---")
    spicor = TTS(
        str(base_dir / "assets/models/piper/en_IN_voice.onnx"),
        str(base_dir / "assets/models/piper/en_IN_voice.onnx.json")
    )
    # length_scale=1.0 is the raw library default
    spicor.speak("This is the original Spicor voice without any humanization settings.", length_scale=1.0, noise_scale=0.667, noise_w=0.8)
    
    time.sleep(1)
    
    # 2. Spicor (Humanized - Current Settings)
    print("\n--- Playing Voice 2: Spicor (HUMANIZED / CURRENT) ---")
    # This uses the new defaults I set: length_scale=1.1, etc.
    spicor.speak("This is the humanized Spicor voice. I am speaking ten percent slower with more natural tone variation.")
    
    time.sleep(1)
    
    # 3. Priyamvada (Humanized)
    print("\n--- Playing Voice 3: Priyamvada (HUMANIZED) ---")
    priyamvada = TTS(
        str(base_dir / "assets/models/piper/priyamvada.onnx"),
        str(base_dir / "assets/models/piper/priyamvada.onnx.json")
    )
    priyamvada.speak("This is the Priyamvada voice with humanization. I am a very clear and professional alternative.")

if __name__ == "__main__":
    compare_voices()

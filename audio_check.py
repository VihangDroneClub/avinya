import sounddevice as sd
import numpy as np
import time

def check_audio():
    print("--- Audio Device Diagnostic ---")
    devices = sd.query_devices()
    print(f"Available devices:\n{devices}")
    
    default_input = sd.default.device[0]
    print(f"\nDefault Input Device ID: {default_input}")
    
    if default_input == -1:
        print("ERROR: No default input device found!")
        return

    print("\n--- Testing 3-second Recording ---")
    duration = 3  # seconds
    fs = 16000    # Sample rate
    
    try:
        print("Speak now...")
        recording = sd.rec(int(duration * fs), samplerate=fs, channels=1)
        sd.wait()  # Wait until recording is finished
        
        # Check for signal
        max_val = np.max(np.abs(recording))
        mean_val = np.mean(np.abs(recording))
        
        print(f"Recording finished.")
        print(f"Max Amplitude: {max_val:.4f}")
        print(f"Mean Amplitude: {mean_val:.4f}")
        
        if max_val < 0.001:
            print("WARNING: Very low signal detected. Is your mic muted or volume low?")
        else:
            print("SUCCESS: Audio signal detected!")
            
    except Exception as e:
        print(f"ERROR: Could not record: {e}")

if __name__ == "__main__":
    check_audio()

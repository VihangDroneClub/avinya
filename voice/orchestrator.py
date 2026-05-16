from __future__ import annotations

import threading
import time
from pathlib import Path

from core.prompt_builder import build_full_prompt
from llm.ollama_adapter import generate_text, generate_stream
from llm.router import choose_model
from memory.session_memory import SessionMemory
from rag.retriever import retrieve_query_context

from voice.tts import TTS
from voice.stt import STT
from voice.wake_word import WakeWordDetector
from voice.audio_recorder import AudioRecorder

class VoiceOrchestrator:
    def __init__(self, memory: SessionMemory):
        self.memory = memory
        self.base_dir = Path(__file__).parent.parent
        
        # Initialize voice components
        print("Initializing Jarvis Mode components...")
        self.tts = TTS(
            str(self.base_dir / "assets/models/piper/en_IN_voice.onnx"),
            str(self.base_dir / "assets/models/piper/en_IN_voice.onnx.json")
        )
        self.stt = STT("tiny.en", download_root=str(self.base_dir / "assets/models/whisper"))
        self.wake_detector = WakeWordDetector(
            str(self.base_dir / "assets/models/vosk"),
            keywords=["jarvis", "avinya"]
        )
        self.recorder = AudioRecorder()
        
        self.active = False
        self._thread = None
        self.on_state_change = None # Callback for UI updates
        self.on_message = None # Callback for UI to display text

    def start(self):
        self.active = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.active = False

    def _update_state(self, state: str):
        if self.on_state_change:
            self.on_state_change(state)
        print(f"[Jarvis] State: {state}")

    def _run_loop(self):
        while self.active:
            self._update_state("LISTENING_WAKE_WORD")
            keyword = self.wake_detector.listen_for_wake_word()
            
            if not self.active: break
            
            # Found wake word
            self._update_state("RECORDING_COMMAND")
            # Maybe play a small "beep" or acknowledge
            # self.tts.speak("Yes?") # Might be too slow, let's just record
            
            audio = self.recorder.record_until_silence()
            
            self._update_state("TRANSCRIBING")
            text = self.stt.transcribe(audio)
            
            if not text or len(text) < 2:
                print("No command detected.")
                continue
                
            print(f"User: {text}")
            if self.on_message:
                self.on_message("user", text)
            
            self.memory.add_user_message(text)
            
            self._update_state("THINKING")
            model = choose_model(text)
            retrieval = retrieve_query_context(text, rerank=True)
            prompt = build_full_prompt(text, retrieval.answer_context, self.memory)
            
            self._update_state("SPEAKING")
            
            # Instead of waiting for full response, we can stream and speak sentences.
            # But for simplicity, let's get the full response first for now, 
            # or buffer by sentence.
            
            full_response = ""
            sentence_buffer = ""
            
            for token in generate_stream(prompt, model):
                full_response += token
                sentence_buffer += token
                
                # If we have a complete sentence, speak it
                if any(punct in sentence_buffer for punct in [". ", "? ", "! ", "\n"]):
                    to_speak = sentence_buffer.strip()
                    if to_speak:
                        if self.on_message:
                            self.on_message("assistant_partial", to_speak)
                        self.tts.speak(to_speak)
                    sentence_buffer = ""
            
            # Speak remaining
            if sentence_buffer.strip():
                if self.on_message:
                    self.on_message("assistant_partial", sentence_buffer.strip())
                self.tts.speak(sentence_buffer.strip())
            
            self.memory.add_assistant_message(full_response)
            if self.on_message:
                self.on_message("assistant_final", full_response)
            
            time.sleep(0.5)

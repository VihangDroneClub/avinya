from __future__ import annotations

import threading
import time
from pathlib import Path

from core.prompt_builder import build_full_prompt
from core.session_ops import maybe_roll_summary
from llm.ollama_adapter import generate_stream
from llm.router import choose_model
from memory.session_memory import SessionMemory
from rag.retriever import retrieve_query_context

from voice.tts import TTS
from voice.stt import STT
from voice.wake_word import WakeWordDetector
from voice.audio_recorder import AudioRecorder


class VoiceOrchestrator:
    """Manages the full voice conversation loop: wake word -> listen -> think -> speak."""

    def __init__(self, memory: SessionMemory):
        self.memory = memory
        self.base_dir = Path(__file__).parent.parent

        print("Initializing Jarvis Mode components...")
        self.tts = TTS(
            piper_model_path=str(self.base_dir / "assets/models/piper/en_IN_voice.onnx"),
            piper_config_path=str(self.base_dir / "assets/models/piper/en_IN_voice.onnx.json"),
            prefer_edge=True,
            prefer_kokoro_offline=True,
        )
        self.stt = STT("tiny.en", download_root=str(self.base_dir / "assets/models/whisper"))
        self.wake_detector = WakeWordDetector(
            str(self.base_dir / "assets/models/vosk"),
            keywords=["hey_jarvis", "avinya"],
        )
        self.recorder = AudioRecorder()

        self.active = False
        self._thread = None
        self._interrupt_event = threading.Event()
        self.on_state_change = None
        self.on_message = None

    def start(self):
        self.active = True
        self._interrupt_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.active = False
        self._interrupt_event.set()
        self.tts.stop()

    def interrupt(self):
        """Interrupt current speech and re-listen."""
        self._interrupt_event.set()
        self.tts.stop()
        self._interrupt_event.clear()

    def _update_state(self, state: str):
        if self.on_state_change:
            self.on_state_change(state)
        print(f"[Jarvis] State: {state}")

    def _run_loop(self):
        while self.active:
            self._update_state("LISTENING_WAKE_WORD")
            keyword = self.wake_detector.listen_for_wake_word()

            if not self.active:
                break
            if not keyword:
                continue

            self._update_state("RECORDING_COMMAND")
            audio = self.recorder.record_until_silence()

            if len(audio) < self.recorder.sample_rate * 0.2:
                print("[Jarvis] Audio too short, skipping.")
                continue

            audio = AudioRecorder.normalize_audio(audio)
            audio = AudioRecorder.apply_noise_gate(audio)

            self._update_state("TRANSCRIBING")
            text = self.stt.transcribe(audio)

            if not text or len(text) < 2:
                print("[Jarvis] No speech detected.")
                continue

            print(f"[Jarvis] User: {text}")
            if self.on_message:
                self.on_message("user", text)

            self.memory.add_user_message(text)

            self._update_state("THINKING")
            model = choose_model(text)
            retrieval = retrieve_query_context(text, rerank=True)
            prompt = build_full_prompt(text, retrieval.answer_context, self.memory)

            self._update_state("SPEAKING")

            full_response = ""
            sentence_buffer = ""

            for token in generate_stream(prompt, model):
                if self._interrupt_event.is_set():
                    break

                full_response += token
                sentence_buffer += token

                if any(punct in sentence_buffer for punct in [". ", "? ", "! ", "\n"]):
                    to_speak = sentence_buffer.strip()
                    if to_speak:
                        if self.on_message:
                            self.on_message("assistant_partial", to_speak)
                        self.tts.speak_async(to_speak, stream=False)
                        time.sleep(0.05)
                    sentence_buffer = ""

            if sentence_buffer.strip() and not self._interrupt_event.is_set():
                if self.on_message:
                    self.on_message("assistant_partial", sentence_buffer.strip())
                self.tts.speak(sentence_buffer.strip())

            if full_response and not self._interrupt_event.is_set():
                self.memory.add_assistant_message(full_response)
                if self.on_message:
                    self.on_message("assistant_final", full_response)
                threading.Thread(target=lambda: maybe_roll_summary(self.memory), daemon=True).start()

            self._interrupt_event.clear()
            time.sleep(0.3)

    def ask_once(self, text: str) -> str:
        """Process a single voice query and return the spoken response. No wake word needed."""
        self._update_state("THINKING")
        model = choose_model(text)
        retrieval = retrieve_query_context(text, rerank=True)
        prompt = build_full_prompt(text, retrieval.answer_context, self.memory)

        full_response = ""
        for token in generate_stream(prompt, model):
            full_response += token

        self.memory.add_user_message(text)
        self.memory.add_assistant_message(full_response)

        self._update_state("SPEAKING")
        self.tts.speak_async(full_response, stream=True)

        return full_response

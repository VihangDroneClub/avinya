"""Compatibility wrapper for the laptop-first Avinya desktop UI."""

from __future__ import annotations

from .laptop_desktop import main

if __name__ == "__main__":
    raise SystemExit(main())

import queue
import sys
import threading
from pathlib import Path

import customtkinter as ctk

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import SESSION_MAX_TURNS
from core.prompt_builder import build_full_prompt
from core.session_ops import maybe_roll_summary
from core.startup import initialise_system
from llm.ollama_adapter import OllamaError, check_ollama, generate_stream
from llm.router import choose_model
from memory.session_memory import SessionMemory
from memory.summarizer import summarize_conversation
from retrieval import retrieve_context
from voice.orchestrator import VoiceOrchestrator
from voice.tts import TTS


# --------------------------------------------------------------------------- #
# Design system (8px grid, radii, type scale)
# --------------------------------------------------------------------------- #
class DS:
    XS, S, M, L, XL, XXL = 8, 12, 16, 24, 32, 48
    R_MAIN = 8
    R_SM = 4
    HERO = 36
    HDR = 26
    BODY = 15
    SM = 12
    ANIM_MS = 200


# Platform-appropriate UI stack (Tk picks first available family name)
# Mirrors UI font stacks; Tk uses one family name (no CSS fall-through at render time).
FONT_TRY = (
    "SF Pro Text",
    "Segoe UI",
    "Roboto",
    "Helvetica Neue",
    "Ubuntu",
    "Noto Sans",
    "Cantarell",
    "Inter",
)

WHITE = "#ffffff"
LG = "#f7f7f8"
TEXT = "#0d0d0d"
ACCENT_BLACK = "#1e1e1e"

THEMES = {
    "light": {
        "window": LG,
        "sidebar": "#efefef",
        "sidebar_border": "#e0e0e0",
        "surface": WHITE,
        "surface_border": "#e5e5e5",
        "text": TEXT,
        "text_muted": "#5c5c5c",
        "user_bubble": "#e8e8e8",
        "assistant_bubble": WHITE,
        "accent": ACCENT_BLACK,
        "accent_hover": "#333333",
        "accent_text": WHITE,
        "composer_bg": WHITE,
        "status_bar": "#ececec",
        "fade_from": "#b8b8b8",
    },
    "dark": {
        "window": ACCENT_BLACK,
        "sidebar": "#161616",
        "sidebar_border": "#2a2a2a",
        "surface": "#222222",
        "surface_border": "#333333",
        "text": LG,
        "text_muted": "#9a9a9a",
        "user_bubble": "#2d2d2d",
        "assistant_bubble": WHITE,
        "accent": WHITE,
        "accent_hover": LG,
        "accent_text": ACCENT_BLACK,
        "composer_bg": "#1a1a1a",
        "status_bar": "#202020",
        "fade_from": "#8a8a8a",
    },
}


def _font(size: int, bold: bool = False) -> ctk.CTkFont:
    wt = "bold" if bold else "normal"
    for fam in FONT_TRY:
        try:
            f = ctk.CTkFont(family=fam, size=size, weight=wt)
            # CTkFont may accept invalid names silently — still return
            return f
        except Exception:
            continue
    return ctk.CTkFont(size=size, weight=wt)


class AvinyaApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Avinya")
        self.minsize(980, 680)
        self.geometry("1080x760")

        self._theme_name = "light"
        self._t = THEMES[self._theme_name]
        self.memory = SessionMemory(max_recent=SESSION_MAX_TURNS)
        self._ready = False
        self._streaming = False
        self._stream_queue: queue.Queue = queue.Queue()
        self._stream_acc: str = ""
        self._assistant_failed = False
        self._stream_fade_done = False
        self._active_assistant_label: ctk.CTkLabel | None = None
        self._chat_mousewheel_bound = False
        
        # Jarvis Mode
        self.jarvis = VoiceOrchestrator(self.memory)
        self.jarvis.on_state_change = self._on_jarvis_state
        self.jarvis.on_message = self._on_jarvis_message
        
        # Standalone TTS
        self.tts = TTS(
            str(_ROOT / "assets/models/piper/en_IN_voice.onnx"),
            str(_ROOT / "assets/models/piper/en_IN_voice.onnx.json")
        )

        ctk.set_appearance_mode("light")
        self.configure(fg_color=self._t["window"])

        self._build_layout()
        self.chat_scroll.bind("<Configure>", self._on_chat_configure)
        self.chat_scroll.bind("<Enter>", self._bind_chat_mousewheel)
        self.chat_scroll.bind("<Leave>", self._unbind_chat_mousewheel)
        self._load_backend_async()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _bubble_wraplength(self) -> int:
        try:
            w = max(self.chat_scroll.winfo_width(), 400)
            return max(280, min(720, w - DS.XXL))
        except Exception:
            return 640

    def _on_chat_configure(self, _event=None) -> None:
        wl = self._bubble_wraplength()
        if self._active_assistant_label is not None:
            try:
                self._active_assistant_label.configure(wraplength=wl)
            except Exception:
                pass
        self._scroll_chat_to_bottom()

    def _scroll_chat_to_bottom(self) -> None:
        try:
            canvas = self.chat_scroll._parent_canvas
            canvas.update_idletasks()
            canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _on_mousewheel(self, event) -> str:
        try:
            canvas = self.chat_scroll._parent_canvas
        except Exception:
            return "break"

        delta = 0
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        elif getattr(event, "delta", 0):
            delta = -1 if event.delta > 0 else 1

        try:
            canvas.yview_scroll(delta, "units")
        except Exception:
            pass
        return "break"

    def _bind_chat_mousewheel(self, _event=None) -> None:
        if self._chat_mousewheel_bound:
            return
        self._chat_mousewheel_bound = True
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel)
        self.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_chat_mousewheel(self, _event=None) -> None:
        if not self._chat_mousewheel_bound:
            return
        self._chat_mousewheel_bound = False
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                self.unbind_all(seq)
            except Exception:
                pass

    def _set_theme(self, name: str) -> None:
        if name not in THEMES:
            return
        self._theme_name = name
        self._t = THEMES[name]
        ctk.set_appearance_mode("light" if name == "light" else "dark")
        t = self._t
        self.configure(fg_color=t["window"])
        self.sidebar.configure(fg_color=t["sidebar"])
        self.main_frame.configure(fg_color=t["window"])
        self.chat_scroll.configure(fg_color=t["window"])
        self.composer.configure(fg_color=t["surface"], border_color=t["surface_border"])
        self.input_box.configure(
            fg_color=t["composer_bg"],
            text_color=t["text"],
            border_color=t["surface_border"],
        )
        self.send_btn.configure(
            fg_color=t["accent"],
            hover_color=t["accent_hover"],
            text_color=t["accent_text"],
        )
        self.status_chip.configure(fg_color=t["status_bar"], text_color=t["text_muted"])
        self.theme_seg.configure(
            selected_color=t["accent"],
            selected_hover_color=t["accent_hover"],
            unselected_color=t["surface_border"],
            fg_color=t["surface_border"],
        )

    def _build_layout(self) -> None:
        t = self._t

        self.sidebar = ctk.CTkFrame(
            self,
            width=256,
            corner_radius=0,
            fg_color=t["sidebar"],
            border_width=1,
            border_color=t["sidebar_border"],
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=DS.L, pady=(DS.XL, DS.M))

        ctk.CTkLabel(
            brand,
            text="Avinya",
            font=_font(DS.HERO, True),
            text_color=t["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand,
            text="Grounded assistant · local RAG",
            font=_font(DS.SM),
            text_color=t["text_muted"],
        ).pack(anchor="w", pady=(DS.SM, 0))

        self.theme_seg = ctk.CTkSegmentedButton(
            self.sidebar,
            values=["Light", "Dark"],
            command=self._on_theme_pick,
            font=_font(DS.SM),
            height=36,
            corner_radius=DS.R_SM,
            selected_color=t["accent"],
            selected_hover_color=t["accent_hover"],
            unselected_color=t["sidebar"],
            fg_color=t["surface_border"],
        )
        self.theme_seg.pack(fill="x", padx=DS.L, pady=(DS.S, DS.L))
        self.theme_seg.set("Light")

        ctk.CTkButton(
            self.sidebar,
            text="New conversation",
            font=_font(DS.BODY),
            height=40,
            corner_radius=DS.R_MAIN,
            fg_color=t["surface"],
            text_color=t["text"],
            hover_color=t["status_bar"],
            border_width=1,
            border_color=t["surface_border"],
            command=self._new_chat,
        ).pack(fill="x", padx=DS.L, pady=DS.XS)

        ctk.CTkButton(
            self.sidebar,
            text="Recap to memory",
            font=_font(DS.SM),
            height=36,
            corner_radius=DS.R_MAIN,
            fg_color="transparent",
            text_color=t["text_muted"],
            hover_color=t["surface"],
            command=self._recap,
        ).pack(fill="x", padx=DS.L, pady=(DS.S, DS.XS))

        ctk.CTkButton(
            self.sidebar,
            text="Check Ollama",
            font=_font(DS.SM),
            height=36,
            corner_radius=DS.R_MAIN,
            fg_color="transparent",
            text_color=t["text_muted"],
            hover_color=t["surface"],
            command=self._check_ollama,
        ).pack(fill="x", padx=DS.L, pady=DS.XS)

        # Jarvis Mode Toggle
        self.jarvis_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.jarvis_frame.pack(fill="x", padx=DS.L, pady=(DS.M, DS.XS))
        
        self.jarvis_switch = ctk.CTkSwitch(
            self.jarvis_frame,
            text="Jarvis Mode",
            font=_font(DS.BODY),
            command=self._toggle_jarvis,
            progress_color=t["accent"],
        )
        self.jarvis_switch.pack(side="left", padx=DS.XS)

        # Voice Output Toggle
        self.voice_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.voice_frame.pack(fill="x", padx=DS.L, pady=(0, DS.M))
        
        self.voice_switch = ctk.CTkSwitch(
            self.voice_frame,
            text="Voice Output",
            font=_font(DS.BODY),
            progress_color=t["accent"],
        )
        self.voice_switch.pack(side="left", padx=DS.XS)

        self.boot_label = ctk.CTkLabel(
            self.sidebar,
            text="Loading knowledge base…",
            font=_font(DS.SM),
            text_color=t["text_muted"],
            wraplength=220,
        )
        self.boot_label.pack(side="bottom", fill="x", padx=DS.L, pady=DS.L)

        self.main_frame = ctk.CTkFrame(self, fg_color=t["window"], corner_radius=0)
        self.main_frame.pack(side="right", fill="both", expand=True)

        self.status_chip = ctk.CTkLabel(
            self.main_frame,
            text=" ",
            font=_font(DS.SM),
            text_color=t["text_muted"],
            fg_color=t["status_bar"],
            corner_radius=DS.R_MAIN,
            anchor="w",
            height=36,
        )
        self.status_chip.pack(fill="x", padx=DS.L, pady=(DS.L, DS.S))

        self.chat_scroll = ctk.CTkScrollableFrame(
            self.main_frame,
            fg_color=t["window"],
            corner_radius=0,
        )
        self.chat_scroll.pack(fill="both", expand=True, padx=DS.M, pady=(0, DS.S))

        self.composer = ctk.CTkFrame(
            self.main_frame,
            fg_color=t["surface"],
            corner_radius=DS.R_MAIN,
            border_width=1,
            border_color=t["surface_border"],
        )
        self.composer.pack(fill="x", padx=DS.L, pady=(0, DS.L))

        inner = ctk.CTkFrame(self.composer, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=DS.M, pady=DS.M)

        self.input_box = ctk.CTkTextbox(
            inner,
            height=88,
            font=_font(DS.BODY),
            fg_color=t["composer_bg"],
            text_color=t["text"],
            border_width=1,
            border_color=t["surface_border"],
            corner_radius=DS.R_MAIN,
            wrap="word",
            activate_scrollbars=False,
        )
        self.input_box.pack(side="left", fill="both", expand=True, padx=(0, DS.M))
        self.input_box.bind("<Return>", self._on_return)

        self.send_btn = ctk.CTkButton(
            inner,
            text="Send",
            width=104,
            height=44,
            font=_font(DS.BODY, True),
            corner_radius=DS.R_MAIN,
            fg_color=t["accent"],
            hover_color=t["accent_hover"],
            text_color=t["accent_text"],
            command=self._send,
        )
        self.send_btn.pack(side="right", anchor="s", pady=(0, DS.XS))

    def _on_theme_pick(self, value: str) -> None:
        self._set_theme("light" if value == "Light" else "dark")

    def _on_return(self, event) -> str | None:
        if event.state & 0x0001:
            return None
        self._send()
        return "break"

    def _load_backend_async(self) -> None:
        def work() -> None:
            try:
                initialise_system()
                try:
                    check_ollama()
                    err = None
                except OllamaError as e:
                    err = str(e)
                self.after(0, lambda: self._on_ready(err))
            except Exception as e:
                self.after(0, lambda: self._on_ready(str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_ready(self, ollama_hint: str | None) -> None:
        self._ready = True
        self.boot_label.configure(
            text=(
                ollama_hint
                if ollama_hint
                else "Ready — Ollama connected. Ask anything about the club."
            ),
            text_color=self._t["text_muted"] if not ollama_hint else self._t["text"],
        )

    def _on_close(self) -> None:
        self.destroy()

    def _clear_chat_ui(self) -> None:
        self._active_assistant_label = None
        for w in self.chat_scroll.winfo_children():
            w.destroy()
        self._scroll_chat_to_bottom()

    def _new_chat(self) -> None:
        self.memory.clear()
        self._clear_chat_ui()
        self.status_chip.configure(text="New conversation — context cleared.")
        self._welcome_bubble()

    def _welcome_bubble(self) -> None:
        t = self._t
        row = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        row.pack(fill="x", pady=(DS.XS, DS.XS))
        self._animate_row_in(row)
        inner = ctk.CTkFrame(
            row,
            fg_color=t["assistant_bubble"],
            corner_radius=DS.R_MAIN,
            border_width=1,
            border_color=t["surface_border"],
        )
        inner.pack(side="left", padx=(DS.M, DS.XXL), pady=DS.XS)
        lbl = ctk.CTkLabel(
            inner,
            text=(
                "Welcome. I use your indexed club knowledge base and remember this session.\n"
                "Enter to send · Shift+Enter for a new line."
            ),
            font=_font(DS.BODY),
            text_color=t["text_muted"],
            justify="left",
            wraplength=self._bubble_wraplength(),
        )
        lbl.pack(padx=DS.L, pady=DS.L)
        self._scroll_chat_to_bottom()

    def _animate_row_in(self, row: ctk.CTkFrame) -> None:
        """Approximate 0.2s ease: brief delay then show (Tk has no CSS transitions)."""
        row.pack_configure(pady=(DS.XL, DS.XS))
        self.after(16, lambda: row.pack_configure(pady=(DS.XS, DS.XS)))

    def _add_user_message(self, text: str) -> None:
        t = self._t
        row = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        row.pack(fill="x", pady=DS.XS)
        self._animate_row_in(row)
        inner = ctk.CTkFrame(
            row,
            fg_color=t["user_bubble"],
            corner_radius=DS.R_MAIN,
            border_width=1,
            border_color=t["surface_border"],
        )
        inner.pack(side="right", padx=(DS.XXL, DS.M), pady=DS.XS)
        ctk.CTkLabel(
            inner,
            text=text.strip(),
            font=_font(DS.BODY),
            text_color=t["text"],
            justify="left",
            wraplength=min(520, self._bubble_wraplength()),
        ).pack(padx=DS.L, pady=DS.M)
        self._scroll_chat_to_bottom()

    def _start_assistant_label(self) -> ctk.CTkLabel:
        """Auto-growing label — no inner scrollbar."""
        t = self._t
        row = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        row.pack(fill="x", pady=DS.XS)
        self._animate_row_in(row)
        inner = ctk.CTkFrame(
            row,
            fg_color=t["assistant_bubble"],
            corner_radius=DS.R_MAIN,
            border_width=1,
            border_color=t["surface_border"],
        )
        inner.pack(side="left", padx=(DS.M, DS.XL), pady=DS.XS, fill="x", expand=True)

        lbl = ctk.CTkLabel(
            inner,
            text="",
            font=_font(DS.BODY),
            text_color=t["fade_from"],
            justify="left",
            wraplength=self._bubble_wraplength(),
            anchor="w",
        )
        lbl.pack(fill="x", padx=DS.L, pady=DS.L)
        self._active_assistant_label = lbl
        self._scroll_chat_to_bottom()
        return lbl

    def _update_assistant_label(self, label: ctk.CTkLabel, text: str, streaming: bool) -> None:
        suffix = " ▌" if streaming else ""
        label.configure(text=text + suffix, wraplength=self._bubble_wraplength())
        if not streaming:
            label.configure(text_color=self._t["text"])
        self.update_idletasks()
        self._scroll_chat_to_bottom()

    def _fade_assistant_label(self, label: ctk.CTkLabel) -> None:
        """First-token fade: muted → full text color over ~200ms."""
        t = self._t
        label.configure(text_color=t["fade_from"])
        self.after(
            max(40, DS.ANIM_MS // 2),
            lambda: label.configure(text_color=t["text"]),
        )

    def _send(self) -> None:
        if not self._ready or self._streaming:
            return
        raw = self.input_box.get("1.0", "end").strip()
        if not raw:
            return
        self.input_box.delete("1.0", "end")

        self.memory.add_user_message(raw)
        self._add_user_message(raw)
        self._streaming = True
        self._stream_acc = ""
        self._assistant_failed = False
        self._stream_fade_done = False
        self.send_btn.configure(state="disabled")

        label = self._start_assistant_label()
        self.update_idletasks()

        def worker() -> None:
            try:
                model = choose_model(raw)
                kb, source = retrieve_context(raw)
                prompt = build_full_prompt(raw, kb, self.memory)
                self._stream_queue.put(("meta", model, source))
                for token in generate_stream(prompt, model):
                    self._stream_queue.put(("tok", token))
            except OllamaError as e:
                self._stream_queue.put(("err", str(e)))
            except Exception as e:
                self._stream_queue.put(("err", str(e)))
            finally:
                self._stream_queue.put(("done", ""))

        threading.Thread(target=worker, daemon=True).start()
        self._pump_stream(label)

    def _pump_stream(self, label: ctk.CTkLabel) -> None:
        try:
            while True:
                try:
                    item = self._stream_queue.get_nowait()
                except queue.Empty:
                    self.after(45, lambda: self._pump_stream(label))
                    return

                kind = item[0]
                if kind == "meta":
                    _, model, source = item
                    self.status_chip.configure(
                        text=f"Sources · {source or '—'}     Model · {model}",
                    )
                elif kind == "tok":
                    if not self._stream_fade_done:
                        self._stream_fade_done = True
                        self._fade_assistant_label(label)
                    self._stream_acc += item[1]
                    self._update_assistant_label(label, self._stream_acc, streaming=True)
                elif kind == "err":
                    self._assistant_failed = True
                    self._stream_acc += f"\n\n⚠ {item[1]}"
                    self._update_assistant_label(label, self._stream_acc.strip(), streaming=False)
                elif kind == "done":
                    self._streaming = False
                    self.send_btn.configure(state="normal")
                    body = self._stream_acc.strip()
                    self._update_assistant_label(label, self._stream_acc, streaming=False)
                    
                    # Speak full response if enabled
                    if self.voice_switch.get() and body and not self._assistant_failed:
                        self.tts.speak_async(body)

                    if body and not self._assistant_failed:
                        self.memory.add_assistant_message(self._stream_acc)
                        threading.Thread(
                            target=lambda: maybe_roll_summary(self.memory),
                            daemon=True,
                        ).start()
                    self._stream_acc = ""
                    self._active_assistant_label = None
                    self._scroll_chat_to_bottom()
                    return
        except Exception:
            self._streaming = False
            self.send_btn.configure(state="normal")
            self._active_assistant_label = None

    def _recap(self) -> None:
        block = self.memory.get_recent_context().strip()
        if not block:
            self.status_chip.configure(text="Nothing recent to recap.")
            return

        def work() -> None:
            merged = summarize_conversation(self.memory.get_summary() + "\n\n" + block)
            if merged:
                self.memory.update_summary(merged)
                self.memory.clear_recent_only()
                self.after(0, lambda: self.status_chip.configure(text="Recap saved to long-term memory."))

        threading.Thread(target=work, daemon=True).start()
        self.status_chip.configure(text="Summarizing…")

    def _check_ollama(self) -> None:
        try:
            check_ollama()
            self.status_chip.configure(text="Ollama is reachable.")
        except OllamaError as e:
            self.status_chip.configure(text=str(e)[:120])

    # --------------------------------------------------------------------------- #
    # Jarvis Mode Callbacks
    # --------------------------------------------------------------------------- #
    def _toggle_jarvis(self) -> None:
        if self.jarvis_switch.get():
            self.jarvis.start()
            self.status_chip.configure(text="Jarvis Mode activated.")
        else:
            self.jarvis.stop()
            self.status_chip.configure(text="Jarvis Mode deactivated.")

    def _on_jarvis_state(self, state: str) -> None:
        """Called from orchestrator thread."""
        icons = {
            "LISTENING_WAKE_WORD": "Listening (Hey Avinya)…",
            "RECORDING_COMMAND": "Listening to you…",
            "TRANSCRIBING": "Understanding…",
            "THINKING": "Thinking…",
            "SPEAKING": "Speaking…",
        }
        msg = icons.get(state, state)
        self.after(0, lambda: self.status_chip.configure(text=f"Jarvis Mode: {msg}"))

    def _on_jarvis_message(self, role: str, text: str) -> None:
        """Called from orchestrator thread to update UI."""
        if role == "user":
            self.after(0, lambda: self._add_user_message(text))
        elif role == "assistant_partial":
            # Start a new assistant bubble if needed
            self.after(0, lambda: self._handle_jarvis_partial(text))
        elif role == "assistant_final":
            self.after(0, lambda: self._handle_jarvis_final(text))

    def _handle_jarvis_partial(self, text: str) -> None:
        if self._active_assistant_label is None:
            self._start_assistant_label()

        # Append text to active label
        current = self._active_assistant_label.cget("text")
        new_text = current + " " + text
        self._update_assistant_label(self._active_assistant_label, new_text.strip(), streaming=True)

    def _handle_jarvis_final(self, text: str) -> None:
        if self._active_assistant_label:
            self._update_assistant_label(self._active_assistant_label, text, streaming=False)
            self._active_assistant_label = None
            self._scroll_chat_to_bottom()


def main() -> None:
    app = AvinyaApp()
    app._welcome_bubble()
    app.mainloop()


if __name__ == "__main__":
    main()

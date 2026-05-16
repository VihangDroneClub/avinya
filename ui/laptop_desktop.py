from __future__ import annotations

import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import customtkinter as ctk
import tkinter as tk

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import MODEL_DEFAULT, MODEL_REASONING, SESSION_MAX_TURNS
from core.prompt_builder import build_full_prompt
from core.session_ops import maybe_roll_summary
from core.startup import initialise_system
from llm.ollama_adapter import OllamaError, check_ollama, generate_stream
from llm.router import choose_model
from memory.session_memory import SessionMemory
from memory.summarizer import summarize_conversation
from rag.retriever import retrieve_query_context
from rag.types import QueryResult, SourceChunk
from voice.orchestrator import VoiceOrchestrator


class DS:
    XS, S, M, L, XL, XXL = 8, 12, 16, 24, 32, 48
    R_MAIN = 10
    R_SM = 6
    BODY = 15
    SM = 12
    TITLE = 28
    SUBTITLE = 15
    CHIP = 11


COLORS = {
    "window": "#ffffff",
    "panel": "#ffffff",
    "panel_alt": "#fff7ed",
    "border": "#e7dfd6",
    "border_strong": "#d7c9bb",
    "text": "#111111",
    "muted": "#525252",
    "muted_soft": "#737373",
    "accent": "#f97316",
    "accent_hover": "#ea580c",
    "accent_soft": "#ffedd5",
    "accent_blue": "#111111",
    "accent_blue_soft": "#f5f5f5",
    "warning": "#c2410c",
    "warning_soft": "#ffedd5",
    "danger": "#b91c1c",
    "danger_soft": "#fee2e2",
    "assistant": "#ffffff",
    "user": "#fff3e8",
    "chip_bg": "#fff1e6",
}

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


@dataclass(slots=True)
class BubbleHandle:
    row: ctk.CTkFrame
    bubble: ctk.CTkFrame
    title: ctk.CTkLabel
    body: ctk.CTkLabel
    footer: ctk.CTkLabel | None = None


def _font(size: int, bold: bool = False) -> ctk.CTkFont:
    weight = "bold" if bold else "normal"
    for fam in FONT_TRY:
        try:
            return ctk.CTkFont(family=fam, size=size, weight=weight)
        except Exception:
            continue
    return ctk.CTkFont(size=size, weight=weight)


def _clip(text: str, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _lines(text: str, limit: int = 4) -> str:
    parts = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return "\n".join(parts[:limit])


def _source_title(src: SourceChunk) -> str:
    file_name = Path(src.source).name
    score = f"{src.relevance_score:.2f}" if src.relevance_score is not None else "n/a"
    return f"{file_name} · {score}"


class AvinyaApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Avinya")
        self.geometry("1360x860")
        self.minsize(1200, 780)

        self._t = COLORS
        self.configure(fg_color=self._t["window"])

        self._ready = False
        self._streaming = False
        self._stream_queue: queue.Queue = queue.Queue()
        self._stream_text = ""
        self._assistant_failed = False
        self._active_bubble: BubbleHandle | None = None
        self._current_scroll_canvas = None

        self._last_query = ""
        self._last_model = MODEL_DEFAULT
        self._last_result: QueryResult | None = None
        self._last_elapsed = 0.0
        self._last_error = ""
        self._ollama_status = "checking"
        self._connection_status = "loading"

        self.memory = SessionMemory(max_recent=SESSION_MAX_TURNS)
        self.jarvis = VoiceOrchestrator(self.memory)
        self.jarvis.on_state_change = self._on_jarvis_state
        self.jarvis.on_message = self._on_jarvis_message

        ctk.set_appearance_mode("light")

        self._build_layout()
        self._bind_scroll_support(self.transcript)
        self._bind_scroll_support(self.left_scroll)
        self._bind_scroll_support(self.right_scroll)

        self.after(50, self._focus_composer)
        self._load_backend_async()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ #
    # Layout
    # ------------------------------------------------------------------ #
    def _build_layout(self) -> None:
        self.shell = ctk.CTkFrame(self, fg_color=self._t["window"], corner_radius=0)
        self.shell.pack(fill="both", expand=True)

        self.left_panel = ctk.CTkFrame(
            self.shell,
            width=300,
            corner_radius=0,
            fg_color=self._t["panel"],
            border_width=1,
            border_color=self._t["border"],
        )
        self.left_panel.pack(side="left", fill="y")
        self.left_panel.pack_propagate(False)

        self.center_panel = ctk.CTkFrame(
            self.shell,
            corner_radius=0,
            fg_color=self._t["window"],
        )
        self.center_panel.pack(side="left", fill="both", expand=True)

        self.right_panel = ctk.CTkFrame(
            self.shell,
            width=360,
            corner_radius=0,
            fg_color=self._t["panel"],
            border_width=1,
            border_color=self._t["border"],
        )
        self.right_panel.pack(side="right", fill="y")
        self.right_panel.pack_propagate(False)

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()

    def _build_left_panel(self) -> None:
        brand = ctk.CTkFrame(self.left_panel, fg_color=self._t["panel"], corner_radius=0)
        brand.pack(fill="x", padx=DS.L, pady=(DS.L, DS.S))

        ctk.CTkLabel(
            brand,
            text="Avinya",
            font=_font(DS.TITLE, True),
            text_color=self._t["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand,
            text="Laptop workspace",
            font=_font(DS.SUBTITLE),
            text_color=self._t["muted"],
        ).pack(anchor="w", pady=(DS.XS, 0))

        self.left_scroll = ctk.CTkScrollableFrame(
            self.left_panel,
            fg_color=self._t["panel"],
            corner_radius=0,
        )
        self.left_scroll.pack(fill="both", expand=True, padx=DS.S, pady=(0, DS.S))

        self.status_card = self._card(self.left_scroll, "Connection")
        self.status_line = self._card_line(self.status_card, "Status", "loading")
        self.ollama_line = self._card_line(self.status_card, "Ollama", "checking")
        self.model_line = self._card_line(
            self.status_card,
            "Models",
            f"{MODEL_DEFAULT} / {MODEL_REASONING}",
        )
        self.turn_line = self._card_line(self.status_card, "Turns", "0")

        self.action_card = self._card(self.left_scroll, "Actions")
        self._make_action_button(self.action_card, "New conversation", self._new_chat).pack(
            fill="x", pady=(0, DS.XS)
        )
        self._make_action_button(self.action_card, "Summarize memory", self._recap).pack(
            fill="x", pady=DS.XS
        )
        self._make_action_button(self.action_card, "Check Ollama", self._check_ollama).pack(
            fill="x", pady=DS.XS
        )

        self.voice_switch = ctk.CTkSwitch(
            self.action_card,
            text="Hands-free",
            font=_font(DS.BODY),
            command=self._toggle_jarvis,
            progress_color=self._t["accent"],
        )
        self.voice_switch.pack(anchor="w", pady=(DS.S, 0))

        self.prompt_card = self._card(self.left_scroll, "Shortcuts")
        prompt_grid = ctk.CTkFrame(self.prompt_card, fg_color="transparent")
        prompt_grid.pack(fill="x")
        prompt_pairs = [
            ("Summary", "Summarize the current session and key decisions."),
            ("Budget", "What does the knowledge base say about the budget?"),
            ("Meetings", "Find recent meeting decisions and action items."),
            ("Projects", "Summarize the latest project updates and blockers."),
        ]
        self._shortcut_buttons: list[ctk.CTkButton] = []
        for idx, (label, prompt) in enumerate(prompt_pairs):
            btn = ctk.CTkButton(
                prompt_grid,
                text=label,
                height=34,
                corner_radius=DS.R_SM,
                font=_font(DS.SM),
                fg_color=self._t["panel_alt"],
                text_color=self._t["text"],
                hover_color=self._t["chip_bg"],
                border_width=1,
                border_color=self._t["border"],
                command=lambda p=prompt: self._set_composer_text(p),
            )
            btn.grid(row=idx // 2, column=idx % 2, sticky="ew", padx=(0 if idx % 2 == 0 else DS.XS, 0), pady=(0, DS.XS))
            prompt_grid.grid_columnconfigure(idx % 2, weight=1)
            self._shortcut_buttons.append(btn)

        self.recent_card = self._card(self.left_scroll, "Recent")
        self.recent_stack = ctk.CTkFrame(self.recent_card, fg_color="transparent")
        self.recent_stack.pack(fill="x")
        self._render_recent_stack()

    def _build_center_panel(self) -> None:
        header = ctk.CTkFrame(
            self.center_panel,
            fg_color=self._t["window"],
            corner_radius=0,
        )
        header.pack(fill="x", padx=DS.L, pady=(DS.L, DS.S))

        title_block = ctk.CTkFrame(header, fg_color="transparent")
        title_block.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            title_block,
            text="Workspace",
            font=_font(DS.TITLE, True),
            text_color=self._t["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_block,
            text="Local RAG chat for documents and tasks",
            font=_font(DS.SUBTITLE),
            text_color=self._t["muted"],
        ).pack(anchor="w", pady=(DS.XS, 0))

        chip_row = ctk.CTkFrame(header, fg_color="transparent")
        chip_row.pack(side="right", anchor="e")
        self.connection_chip = self._pill(chip_row, "Loading", self._t["warning_soft"], self._t["warning"])
        self.connection_chip.pack(side="left", padx=(0, DS.XS))
        self.model_chip = self._pill(chip_row, MODEL_DEFAULT, self._t["accent_blue_soft"], self._t["accent_blue"])
        self.model_chip.pack(side="left", padx=(0, DS.XS))
        self.source_chip = self._pill(chip_row, "0 sources", self._t["panel"], self._t["muted"])
        self.source_chip.pack(side="left")

        shortcut_row = ctk.CTkFrame(self.center_panel, fg_color="transparent")
        shortcut_row.pack(fill="x", padx=DS.L, pady=(0, DS.S))
        self.quick_prompt_buttons: list[ctk.CTkButton] = []
        for label, prompt in (
            ("Summarize", "Summarize the current session and key decisions."),
            ("Budget", "What does the knowledge base say about the budget?"),
            ("Meetings", "Find recent meeting decisions and action items."),
            ("Projects", "Summarize the latest project updates and blockers."),
        ):
            btn = ctk.CTkButton(
                shortcut_row,
                text=label,
                width=108,
                height=32,
                corner_radius=DS.R_SM,
                font=_font(DS.SM),
                fg_color=self._t["panel"],
                text_color=self._t["text"],
                hover_color=self._t["panel_alt"],
                border_width=1,
                border_color=self._t["border"],
                command=lambda p=prompt: self._set_composer_text(p),
            )
            btn.pack(side="left", padx=(0, DS.XS))
            self.quick_prompt_buttons.append(btn)

        self.transcript = ctk.CTkScrollableFrame(
            self.center_panel,
            fg_color=self._t["window"],
            corner_radius=0,
        )
        self.transcript.pack(fill="both", expand=True, padx=DS.L, pady=(0, DS.S))
        self.transcript.bind("<Configure>", self._on_transcript_resize)
        self.transcript.bind("<Enter>", lambda _event: self._set_scroll_target(self.transcript))
        self.transcript.bind("<Leave>", lambda _event: self._set_scroll_target(None))

        self.composer_card = ctk.CTkFrame(
            self.center_panel,
            fg_color=self._t["panel"],
            corner_radius=DS.R_MAIN,
            border_width=1,
            border_color=self._t["border"],
        )
        self.composer_card.pack(fill="x", padx=DS.L, pady=(0, DS.L))

        composer_inner = ctk.CTkFrame(self.composer_card, fg_color="transparent")
        composer_inner.pack(fill="both", expand=True, padx=DS.M, pady=DS.M)

        self.input_box = tk.Text(
            composer_inner,
            height=5,
            font=("Segoe UI", 13),
            bg=self._t["panel_alt"],
            fg=self._t["text"],
            insertbackground=self._t["accent"],
            selectbackground=self._t["accent_soft"],
            selectforeground=self._t["text"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self._t["border"],
            highlightcolor=self._t["accent"],
            wrap="word",
            undo=True,
            autoseparators=True,
            maxundo=50,
            padx=12,
            pady=10,
        )
        self.input_box.pack(side="left", fill="both", expand=True, padx=(0, DS.M))
        self.input_box.bind("<Return>", self._on_return)
        self.input_box.bind("<Control-Return>", self._on_ctrl_return)
        self.input_box.bind("<Control-k>", lambda _event: self._focus_composer())
        self.input_box.bind("<Button-1>", lambda _event: self._focus_composer())
        self.input_box.bind("<FocusIn>", lambda _event: self._focus_composer())

        button_column = ctk.CTkFrame(composer_inner, fg_color="transparent")
        button_column.pack(side="right", fill="y")

        self.send_btn = ctk.CTkButton(
            button_column,
            text="Send",
            width=104,
            height=44,
            corner_radius=DS.R_SM,
            font=_font(DS.BODY, True),
            fg_color=self._t["accent"],
            text_color="#ffffff",
            hover_color=self._t["accent_hover"],
            command=self._send,
        )
        self.send_btn.pack(anchor="s")
        self.send_btn.configure(state="disabled")

        self.composer_hint = ctk.CTkLabel(
            button_column,
            text="",
            font=_font(DS.SM),
            text_color=self._t["muted_soft"],
        )
        self.composer_hint.pack(anchor="e", pady=(DS.S, 0))

    def _build_right_panel(self) -> None:
        title = ctk.CTkFrame(self.right_panel, fg_color=self._t["panel"], corner_radius=0)
        title.pack(fill="x", padx=DS.L, pady=(DS.L, DS.S))
        ctk.CTkLabel(
            title,
            text="Inspector",
            font=_font(DS.TITLE, True),
            text_color=self._t["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            title,
            text="Live sources and memory",
            font=_font(DS.SUBTITLE),
            text_color=self._t["muted"],
        ).pack(anchor="w", pady=(DS.XS, 0))

        self.right_scroll = ctk.CTkScrollableFrame(
            self.right_panel,
            fg_color=self._t["panel"],
            corner_radius=0,
        )
        self.right_scroll.pack(fill="both", expand=True, padx=DS.S, pady=(0, DS.S))

        self._render_inspector()

    # ------------------------------------------------------------------ #
    # Small builders
    # ------------------------------------------------------------------ #
    def _card(self, parent: ctk.CTkFrame, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent,
            fg_color=self._t["panel"],
            corner_radius=DS.R_MAIN,
            border_width=1,
            border_color=self._t["border"],
        )
        card.pack(fill="x", padx=DS.XS, pady=(0, DS.S))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=DS.M, pady=DS.M)
        ctk.CTkLabel(
            inner,
            text=title,
            font=_font(DS.BODY, True),
            text_color=self._t["text"],
        ).pack(anchor="w")
        return inner

    def _card_line(self, parent: ctk.CTkFrame, label: str, value: str) -> ctk.CTkLabel:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(DS.XS, 0))
        ctk.CTkLabel(
            row,
            text=label,
            font=_font(DS.SM),
            text_color=self._t["muted"],
        ).pack(side="left")
        value_label = ctk.CTkLabel(
            row,
            text=value,
            font=_font(DS.SM, True),
            text_color=self._t["text"],
            justify="left",
            anchor="e",
            wraplength=240,
        )
        value_label.pack(side="right")
        return value_label

    def _pill(self, parent: ctk.CTkFrame, text: str, bg: str, fg: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text=text,
            font=_font(DS.CHIP, True),
            text_color=fg,
            fg_color=bg,
            corner_radius=999,
            padx=10,
            pady=4,
        )

    def _make_action_button(self, parent: ctk.CTkFrame, text: str, command) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            height=36,
            corner_radius=DS.R_SM,
            font=_font(DS.BODY),
            fg_color=self._t["panel_alt"],
            text_color=self._t["text"],
            hover_color=self._t["chip_bg"],
            border_width=1,
            border_color=self._t["border"],
            command=command,
        )

    # ------------------------------------------------------------------ #
    # Runtime / state
    # ------------------------------------------------------------------ #
    def _focus_composer(self) -> None:
        try:
            self.input_box.focus_set()
            self.after_idle(lambda: self.input_box.focus_set())
        except Exception:
            pass

    def _set_composer_text(self, text: str) -> None:
        self.input_box.delete("1.0", "end")
        self.input_box.insert("1.0", text)
        self._focus_composer()

    def _set_status(self, text: str) -> None:
        self.connection_chip.configure(text=text)
        self.status_line.configure(text=text)

    def _load_backend_async(self) -> None:
        def work() -> None:
            try:
                initialise_system()
                self._connection_status = "ready"
                try:
                    check_ollama()
                    self._ollama_status = "running"
                except OllamaError as exc:
                    self._ollama_status = "down"
                    self._last_error = str(exc)
                self.after(0, self._backend_ready)
            except Exception as exc:
                self._connection_status = "error"
                self._last_error = str(exc)
                self.after(0, self._backend_ready)

        threading.Thread(target=work, daemon=True).start()

    def _backend_ready(self) -> None:
        self._ready = self._connection_status == "ready" and self._ollama_status == "running"
        if self._ready:
            self._set_status("Ready")
        elif self._connection_status == "ready":
            self._set_status("Degraded")
        else:
            self._set_status("Error")
        self.ollama_line.configure(text=self._ollama_status)
        self.turn_line.configure(text=str(self.memory.user_turn_count()))
        self.send_btn.configure(state="normal" if self._ready else "disabled")
        if not self._ready:
            self.composer_hint.configure(text="Waiting for Ollama")
        self._refresh_sidebar_snapshot()
        self._render_inspector()

    def _bind_scroll_support(self, frame: ctk.CTkScrollableFrame) -> None:
        frame.bind("<Enter>", lambda _event, f=frame: self._set_scroll_target(f))
        frame.bind("<Leave>", lambda _event: self._set_scroll_target(None))
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel)
        self.bind_all("<Button-5>", self._on_mousewheel)

    def _set_scroll_target(self, frame: ctk.CTkScrollableFrame | None) -> None:
        if frame is None:
            self._current_scroll_canvas = None
            return
        try:
            self._current_scroll_canvas = frame._parent_canvas
        except Exception:
            self._current_scroll_canvas = None

    def _on_mousewheel(self, event) -> str:
        canvas = self._current_scroll_canvas
        if canvas is None:
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

    def _bubble_wraplength(self) -> int:
        try:
            width = max(self.transcript.winfo_width(), 600)
            return max(320, min(820, width - 120))
        except Exception:
            return 720

    def _scroll_transcript_bottom(self) -> None:
        try:
            self.transcript._parent_canvas.update_idletasks()
            self.transcript._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _on_transcript_resize(self, _event=None) -> None:
        if self._active_bubble is not None:
            try:
                self._active_bubble.body.configure(wraplength=self._bubble_wraplength())
            except Exception:
                pass
        self._scroll_transcript_bottom()

    # ------------------------------------------------------------------ #
    # Transcript rendering
    # ------------------------------------------------------------------ #
    def _clear_frame(self, frame: ctk.CTkFrame) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _render_transcript_history(self) -> None:
        self._clear_frame(self.transcript)
        if not self.memory.recent:
            empty = ctk.CTkFrame(
                self.transcript,
                fg_color=self._t["panel"],
                corner_radius=DS.R_MAIN,
                border_width=1,
                border_color=self._t["border"],
            )
            empty.pack(fill="x", padx=DS.XS, pady=DS.S)
            inner = ctk.CTkFrame(empty, fg_color="transparent")
            inner.pack(fill="x", padx=DS.M, pady=DS.M)
            ctk.CTkLabel(
                inner,
                text="No conversation yet.",
                font=_font(DS.BODY, True),
                text_color=self._t["text"],
            ).pack(anchor="w")
            ctk.CTkLabel(
                inner,
                text="",
                font=_font(DS.SM),
                text_color=self._t["muted"],
            ).pack(anchor="w", pady=(DS.XS, 0))
            self._scroll_transcript_bottom()
            return

        for role, message in self.memory.recent:
            if role == "user":
                self._add_user_bubble(message, show_scroll=False)
            else:
                self._add_assistant_bubble(message, title="Avinya", footer=None, show_scroll=False)
        self._scroll_transcript_bottom()

    def _add_user_bubble(self, text: str, *, show_scroll: bool = True) -> BubbleHandle:
        row = ctk.CTkFrame(self.transcript, fg_color="transparent")
        row.pack(fill="x", pady=(DS.XS, DS.XS))
        row.bind("<Enter>", lambda _event: self._set_scroll_target(self.transcript))
        row.bind("<Leave>", lambda _event: self._set_scroll_target(None))
        bubble = ctk.CTkFrame(
            row,
            fg_color=self._t["user"],
            corner_radius=DS.R_MAIN,
            border_width=1,
            border_color=self._t["border"],
        )
        bubble.pack(side="right", padx=(DS.XXL, DS.XS), fill="x", expand=True)
        title = ctk.CTkLabel(
            bubble,
            text="You",
            font=_font(DS.SM, True),
            text_color=self._t["muted"],
        )
        title.pack(anchor="w", padx=DS.M, pady=(DS.S, 0))
        body = ctk.CTkLabel(
            bubble,
            text=text.strip(),
            font=_font(DS.BODY),
            text_color=self._t["text"],
            justify="left",
            anchor="w",
            wraplength=self._bubble_wraplength(),
        )
        body.pack(fill="x", anchor="w", padx=DS.M, pady=(DS.XS, DS.M))
        for widget in (bubble, title, body):
            widget.bind("<Enter>", lambda _event: self._set_scroll_target(self.transcript))
            widget.bind("<Leave>", lambda _event: self._set_scroll_target(None))
        handle = BubbleHandle(row=row, bubble=bubble, title=title, body=body, footer=None)
        if show_scroll:
            self._scroll_transcript_bottom()
        return handle

    def _add_assistant_bubble(
        self,
        text: str,
        *,
        title: str = "Avinya",
        footer: str | None = None,
        show_scroll: bool = True,
    ) -> BubbleHandle:
        row = ctk.CTkFrame(self.transcript, fg_color="transparent")
        row.pack(fill="x", pady=(DS.XS, DS.XS))
        row.bind("<Enter>", lambda _event: self._set_scroll_target(self.transcript))
        row.bind("<Leave>", lambda _event: self._set_scroll_target(None))
        bubble = ctk.CTkFrame(
            row,
            fg_color=self._t["assistant"],
            corner_radius=DS.R_MAIN,
            border_width=1,
            border_color=self._t["border"],
        )
        bubble.pack(side="left", padx=(DS.XS, DS.XXL), fill="x", expand=True)
        title_label = ctk.CTkLabel(
            bubble,
            text=title,
            font=_font(DS.SM, True),
            text_color=self._t["muted"],
        )
        title_label.pack(anchor="w", padx=DS.M, pady=(DS.S, 0))
        body = ctk.CTkLabel(
            bubble,
            text=text.strip(),
            font=_font(DS.BODY),
            text_color=self._t["text"],
            justify="left",
            anchor="w",
            wraplength=self._bubble_wraplength(),
        )
        body.pack(fill="x", anchor="w", padx=DS.M, pady=(DS.XS, DS.XS))
        footer_label = None
        if footer is not None:
            footer_label = ctk.CTkLabel(
                bubble,
                text=footer,
                font=_font(DS.SM),
                text_color=self._t["muted_soft"],
                justify="left",
                anchor="w",
                wraplength=self._bubble_wraplength(),
            )
            footer_label.pack(fill="x", anchor="w", padx=DS.M, pady=(0, DS.M))
        for widget in (bubble, title_label, body):
            widget.bind("<Enter>", lambda _event: self._set_scroll_target(self.transcript))
            widget.bind("<Leave>", lambda _event: self._set_scroll_target(None))
        if footer_label is not None:
            footer_label.bind("<Enter>", lambda _event: self._set_scroll_target(self.transcript))
            footer_label.bind("<Leave>", lambda _event: self._set_scroll_target(None))
        handle = BubbleHandle(row=row, bubble=bubble, title=title_label, body=body, footer=footer_label)
        if show_scroll:
            self._scroll_transcript_bottom()
        return handle

    # ------------------------------------------------------------------ #
    # Inspector / sidebar
    # ------------------------------------------------------------------ #
    def _render_recent_stack(self) -> None:
        self._clear_frame(self.recent_stack)
        recent = list(self.memory.recent[-6:])
        if not recent:
            ctk.CTkLabel(
                self.recent_stack,
                text="No recent turns",
                font=_font(DS.SM),
                text_color=self._t["muted"],
            ).pack(anchor="w", pady=(DS.XS, 0))
            return

        for role, text in recent:
            row = ctk.CTkFrame(self.recent_stack, fg_color="transparent")
            row.pack(fill="x", pady=(0, DS.XS))
            badge = "You" if role == "user" else "Avinya"
            ctk.CTkLabel(
                row,
                text=badge,
                font=_font(DS.CHIP, True),
                text_color=self._t["muted"],
                fg_color=self._t["chip_bg"],
                corner_radius=999,
                padx=8,
                pady=2,
            ).pack(anchor="w", pady=(0, DS.XS))
            ctk.CTkLabel(
                row,
                text=_clip(text, 120),
                font=_font(DS.SM),
                text_color=self._t["text"],
                justify="left",
                anchor="w",
                wraplength=245,
            ).pack(anchor="w")

    def _render_inspector(self) -> None:
        self._clear_frame(self.right_scroll)

        conn = self._card(self.right_scroll, "Connection")
        self._card_line(conn, "API", "127.0.0.1:8000")
        self._card_line(conn, "Backend", self._connection_status)
        self._card_line(conn, "Ollama", self._ollama_status)
        self._card_line(conn, "Models", MODEL_DEFAULT)
        self._card_line(conn, "Reasoning", MODEL_REASONING)

        query = self._card(self.right_scroll, "Last Answer")
        self._card_line(query, "Question", _clip(self._last_query or "—", 42))
        self._card_line(query, "Model", self._last_model or "—")
        self._card_line(query, "Latency", f"{self._last_elapsed:.2f}s" if self._last_elapsed else "—")
        self._card_line(query, "Sources", str(len(self._last_result.sources)) if self._last_result else "0")

        sources = self._card(self.right_scroll, "Sources")
        if self._last_result and self._last_result.sources:
            for src in self._last_result.sources[:5]:
                source_row = ctk.CTkFrame(
                    sources,
                    fg_color=self._t["panel_alt"],
                    corner_radius=DS.R_SM,
                    border_width=1,
                    border_color=self._t["border"],
                )
                source_row.pack(fill="x", pady=(0, DS.XS))
                ctk.CTkLabel(
                    source_row,
                    text=_source_title(src),
                    font=_font(DS.SM, True),
                    text_color=self._t["text"],
                ).pack(anchor="w", padx=DS.M, pady=(DS.S, 0))
                snippet = _clip(_lines(src.chunk, limit=1).replace("\n", " "), 118)
                ctk.CTkLabel(
                    source_row,
                    text=snippet or " ",
                    font=_font(DS.SM),
                    text_color=self._t["muted"],
                    justify="left",
                    anchor="w",
                    wraplength=300,
                ).pack(anchor="w", padx=DS.M, pady=(DS.XS, DS.S))
        else:
            ctk.CTkLabel(
                sources,
                text="Waiting for a query.",
                font=_font(DS.SM),
                text_color=self._t["muted"],
            ).pack(anchor="w", pady=(DS.XS, 0))

        memory = self._card(self.right_scroll, "Memory")
        summary = self.memory.get_summary().strip() or "No rolling summary yet."
        ctk.CTkLabel(
            memory,
            text=_clip(_lines(summary, limit=6), 500),
            font=_font(DS.SM),
            text_color=self._t["text"],
            justify="left",
            anchor="w",
            wraplength=300,
        ).pack(anchor="w", pady=(DS.XS, 0))
        self._card_line(memory, "Recent turns", str(self.memory.user_turn_count()))
        self._card_line(memory, "Total user messages", str(self.memory.user_messages_total))

        activity = self._card(self.right_scroll, "Activity")
        self._card_line(activity, "Ready", "yes" if self._ready else "loading")
        self._card_line(activity, "Streaming", "yes" if self._streaming else "no")
        if self._last_error:
            ctk.CTkLabel(
                activity,
                text=_clip(self._last_error, 260),
                font=_font(DS.SM),
                text_color=self._t["warning"] if "timeout" in self._last_error.lower() else self._t["danger"],
                justify="left",
                anchor="w",
                wraplength=300,
            ).pack(anchor="w", pady=(DS.S, 0))

    def _refresh_sidebar_snapshot(self) -> None:
        self.turn_line.configure(text=str(self.memory.user_turn_count()))
        self.ollama_line.configure(text=self._ollama_status)
        self._render_recent_stack()

    # ------------------------------------------------------------------ #
    # Interaction
    # ------------------------------------------------------------------ #
    def _on_return(self, event) -> str | None:
        if event.state & 0x0001:
            return None
        self._send()
        return "break"

    def _on_ctrl_return(self, _event) -> str | None:
        self._send()
        return "break"

    def _new_chat(self) -> None:
        self.memory.clear()
        self._last_query = ""
        self._last_result = None
        self._last_elapsed = 0.0
        self._last_error = ""
        self._clear_frame(self.transcript)
        self._active_bubble = None
        self.status_line.configure(text="reset")
        self._render_transcript_history()
        self._refresh_sidebar_snapshot()
        self._render_inspector()

    def _add_system_message(self, text: str) -> None:
        bubble = self._add_assistant_bubble(text, title="Avinya", footer=None)
        self._active_bubble = bubble

    def _send(self) -> None:
        if self._streaming:
            return
        if not self._ready:
            self.status_line.configure(text="backend not ready")
            self.composer_hint.configure(text="Start Ollama first")
            self._check_ollama()
            return
        raw = self.input_box.get("1.0", "end").strip()
        if not raw:
            return

        self.input_box.delete("1.0", "end")
        self._last_query = raw
        self._last_result = None
        self._last_error = ""
        self.memory.add_user_message(raw)
        self._add_user_bubble(raw)
        self._streaming = True
        self._assistant_failed = False
        self._stream_text = ""
        self.send_btn.configure(state="disabled")
        self.status_line.configure(text="thinking")
        self.composer_hint.configure(text="")

        bubble = self._add_assistant_bubble("", title="Avinya", footer="thinking")
        self._active_bubble = bubble

        def worker() -> None:
            started = time.perf_counter()
            try:
                model = choose_model(raw)
                retrieval = retrieve_query_context(raw, rerank=True)
                prompt = build_full_prompt(raw, retrieval.answer_context, self.memory)
                self._stream_queue.put(("meta", model, retrieval))
                for token in generate_stream(prompt, model):
                    self._stream_queue.put(("tok", token))
            except OllamaError as exc:
                self._stream_queue.put(("err", str(exc)))
            except Exception as exc:
                self._stream_queue.put(("err", str(exc)))
            finally:
                self._stream_queue.put(("done", time.perf_counter() - started))

        threading.Thread(target=worker, daemon=True).start()
        self._pump_stream()

    def _pump_stream(self) -> None:
        try:
            while True:
                item = self._stream_queue.get_nowait()
                kind = item[0]
                if kind == "meta":
                    _, model, retrieval = item
                    self._last_model = model
                    self._last_result = retrieval
                    self.source_chip.configure(text=f"{len(retrieval.sources)} sources")
                    self.model_chip.configure(text=model)
                    self.connection_chip.configure(text="Working")
                    if self._active_bubble is not None:
                        footer_text = retrieval.source_labels or "no sources"
                        self._active_bubble.footer.configure(text=footer_text if self._active_bubble.footer else "")
                elif kind == "tok":
                    token = item[1]
                    self._stream_text += token
                    if self._active_bubble is not None:
                        self._active_bubble.body.configure(text=self._stream_text, wraplength=self._bubble_wraplength())
                    self._scroll_transcript_bottom()
                elif kind == "err":
                    self._assistant_failed = True
                    self._last_error = item[1]
                    self._stream_text = (self._stream_text + "\n\n" + f"Error: {item[1]}").strip()
                    if self._active_bubble is not None:
                        self._active_bubble.body.configure(text=self._stream_text, wraplength=self._bubble_wraplength())
                        if self._active_bubble.footer is not None:
                            self._active_bubble.footer.configure(text="error")
                    self.status_line.configure(text="error")
                    self._render_inspector()
                elif kind == "done":
                    self._streaming = False
                    self._last_elapsed = float(item[1]) if len(item) > 1 else 0.0
                    self.send_btn.configure(state="normal")
                    if self._active_bubble is not None and self._active_bubble.footer is not None:
                        self._active_bubble.footer.configure(
                            text=(
                                f"{self._last_result.source_labels if self._last_result else 'no sources'}"
                                + (f" · {self._last_elapsed:.2f}s" if self._last_elapsed else "")
                            )
                        )
                    if self._stream_text and not self._assistant_failed:
                        self.memory.add_assistant_message(self._stream_text)
                        threading.Thread(target=lambda: maybe_roll_summary(self.memory), daemon=True).start()
                    self._stream_text = ""
                    self._active_bubble = None
                    self.status_line.configure(text="ready" if not self._last_error else "degraded")
                    self._refresh_sidebar_snapshot()
                    self._render_inspector()
                    self._scroll_transcript_bottom()
                    self._focus_composer()
                    return
        except queue.Empty:
            self.after(35, self._pump_stream)
            return

    def _recap(self) -> None:
        block = self.memory.get_recent_context().strip()
        if not block:
            self.status_line.configure(text="nothing to recap")
            return

        self.status_line.configure(text="summarizing")

        def work() -> None:
            merged = summarize_conversation(self.memory.get_summary() + "\n\n" + block)
            if merged:
                self.memory.update_summary(merged)
                self.memory.clear_recent_only()
            self.after(0, self._after_recap)

        threading.Thread(target=work, daemon=True).start()

    def _after_recap(self) -> None:
        self.status_line.configure(text="memory updated")
        self._refresh_sidebar_snapshot()
        self._render_inspector()

    def _check_ollama(self) -> None:
        try:
            check_ollama()
            self._ollama_status = "running"
            self.status_line.configure(text="ollama ready")
        except OllamaError as exc:
            self._ollama_status = "down"
            self._last_error = str(exc)
            self.status_line.configure(text="ollama error")
        self._ready = self._connection_status == "ready" and self._ollama_status == "running"
        self.send_btn.configure(state="normal" if self._ready else "disabled")
        if not self._ready:
            self.composer_hint.configure(text="Waiting for Ollama")
        self._refresh_sidebar_snapshot()
        self._render_inspector()

    # ------------------------------------------------------------------ #
    # Voice / jarvis
    # ------------------------------------------------------------------ #
    def _toggle_jarvis(self) -> None:
        if self.voice_switch.get():
            self.jarvis.start()
            self.status_line.configure(text="hands-free on")
        else:
            self.jarvis.stop()
            self.status_line.configure(text="hands-free off")

    def _on_jarvis_state(self, state: str) -> None:
        mapping = {
            "LISTENING_WAKE_WORD": "listening",
            "RECORDING_COMMAND": "recording",
            "TRANSCRIBING": "transcribing",
            "THINKING": "thinking",
            "SPEAKING": "speaking",
        }
        msg = mapping.get(state, state.lower())
        self.after(0, lambda: self.status_line.configure(text=f"voice · {msg}"))

    def _on_jarvis_message(self, role: str, text: str) -> None:
        if role == "user":
            self.after(0, lambda: self._add_user_bubble(text))
        elif role == "assistant_partial":
            self.after(0, lambda: self._jarvis_partial(text))
        elif role == "assistant_final":
            self.after(0, lambda: self._jarvis_final(text))

    def _jarvis_partial(self, text: str) -> None:
        if self._active_bubble is None:
            self._active_bubble = self._add_assistant_bubble("", title="Avinya", footer="voice")
        existing = self._active_bubble.body.cget("text").strip()
        updated = f"{existing} {text}".strip() if existing else text.strip()
        self._active_bubble.body.configure(text=updated, wraplength=self._bubble_wraplength())
        self._scroll_transcript_bottom()

    def _jarvis_final(self, text: str) -> None:
        if self._active_bubble is None:
            self._active_bubble = self._add_assistant_bubble(text, title="Avinya", footer="voice")
        else:
            self._active_bubble.body.configure(text=text, wraplength=self._bubble_wraplength())
            if self._active_bubble.footer is not None:
                self._active_bubble.footer.configure(text="voice")
        self._active_bubble = None
        self._scroll_transcript_bottom()

    # ------------------------------------------------------------------ #
    # Closing
    # ------------------------------------------------------------------ #
    def _on_close(self) -> None:
        try:
            self.jarvis.stop()
        except Exception:
            pass
        self.destroy()


def main() -> None:
    app = AvinyaApp()
    app._render_transcript_history()
    app.mainloop()


if __name__ == "__main__":
    main()

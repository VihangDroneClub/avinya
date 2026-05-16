from __future__ import annotations

import json
import queue
import re
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

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
from voice.tts import TTS


class DS:
    XS, S, M, L, XL, XXL = 8, 12, 16, 24, 32, 48
    R_MAIN = 10
    R_SM = 6
    BODY = 14
    SM = 12
    TITLE = 26
    SUBTITLE = 14
    CHIP = 11


DARK = {
    "window": "#101010",
    "panel": "#161616",
    "panel_alt": "#1d1d1d",
    "panel_soft": "#1b1b1b",
    "border": "#2b2b2b",
    "border_strong": "#393939",
    "text": "#f6f6f6",
    "muted": "#b6b6b6",
    "muted_soft": "#8b8b8b",
    "accent": "#ff7a1a",
    "accent_hover": "#ff8c3a",
    "accent_soft": "#2b1f16",
    "accent_line": "#f36f18",
    "warning": "#f59e0b",
    "warning_soft": "#2a2111",
    "danger": "#f87171",
    "danger_soft": "#2a1414",
    "chip_bg": "#1f1f1f",
    "code_bg": "#1a1a1a",
    "blockquote_bg": "#1a1f16",
    "blockquote_border": "#3a5a2a",
}

LIGHT = {
    "window": "#f5f5f5",
    "panel": "#ffffff",
    "panel_alt": "#f0f0f0",
    "panel_soft": "#fafafa",
    "border": "#e0e0e0",
    "border_strong": "#c8c8c8",
    "text": "#1a1a1a",
    "muted": "#6b6b6b",
    "muted_soft": "#8a8a8a",
    "accent": "#e8600a",
    "accent_hover": "#d45500",
    "accent_soft": "#fff0e0",
    "accent_line": "#e8600a",
    "warning": "#d97706",
    "warning_soft": "#fef3c7",
    "danger": "#dc2626",
    "danger_soft": "#fee2e2",
    "chip_bg": "#f0f0f0",
    "code_bg": "#f0f0f0",
    "blockquote_bg": "#f0f7e8",
    "blockquote_border": "#86b95a",
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

SYNTAX_COLORS = {
    "keyword": "#c678dd",
    "string": "#98c379",
    "comment": "#5c6370",
    "number": "#d19a66",
    "function": "#61afef",
    "default_dark": "#abb2bf",
    "default_light": "#383a42",
}


@dataclass(slots=True)
class SourcePreview:
    title: str
    body: str


@dataclass
class SessionEntry:
    id: str
    title: str
    created: str
    updated: str
    turns: list[tuple[str, str]] = field(default_factory=list)
    summary: str = ""


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
    return value[: max(0, limit - 1)].rstrip() + "\u2026"


def _lines(text: str, limit: int = 4) -> str:
    parts = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return "\n".join(parts[:limit])


def _source_title(src: SourceChunk) -> str:
    file_name = Path(src.source).name
    score = f"{src.relevance_score:.2f}" if src.relevance_score is not None else "n/a"
    return f"{file_name} \u00b7 {score}"


def _apply_syntax_highlight(code: str, lang: str, theme: dict) -> list[tuple[str, str]]:
    is_dark = theme["window"] == "#101010"
    default_tag = "code_block"
    if not lang:
        return [(default_tag, code)]

    lang_lower = lang.lower()
    if lang_lower in ("python", "py"):
        patterns = [
            (r'\b(def|class|import|from|return|if|else|elif|for|while|try|except|with|as|in|not|and|or|is|None|True|False|self|lambda|yield|raise|pass|break|continue|async|await)\b', "code_keyword"),
            (r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"[^"]*"|\'[^\']*\')', "code_string"),
            (r'(#.*)', "code_comment"),
            (r'\b(\d+\.?\d*)\b', "code_number"),
            (r'\b([a-zA-Z_]\w*)\s*(?=\()', "code_function"),
        ]
    elif lang_lower in ("javascript", "js", "typescript", "ts"):
        patterns = [
            (r'\b(const|let|var|function|return|if|else|for|while|class|import|from|export|default|async|await|new|this|true|false|null|undefined|try|catch|throw)\b', "code_keyword"),
            (r'(`[^`]*`|"[^"]*"|\'[^\']*\')', "code_string"),
            (r'(//.*)', "code_comment"),
            (r'\b(\d+\.?\d*)\b', "code_number"),
            (r'\b([a-zA-Z_]\w*)\s*(?=\()', "code_function"),
        ]
    elif lang_lower in ("bash", "sh", "shell"):
        patterns = [
            (r'\b(if|then|else|fi|for|while|do|done|case|esac|function|return|exit|echo|export|source|cd|ls|mkdir|rm|cp|mv|cat|grep|sed|awk)\b', "code_keyword"),
            (r'("[^"]*"|\'[^\']*\')', "code_string"),
            (r'(#.*)', "code_comment"),
            (r'\b(\d+\.?\d*)\b', "code_number"),
        ]
    else:
        patterns = [
            (r'("[^"]*"|\'[^\']*\')', "code_string"),
            (r'(//.*|#.*)', "code_comment"),
            (r'\b(\d+\.?\d*)\b', "code_number"),
        ]

    tagged: list[tuple[str, str]] = []
    remaining = code
    while remaining:
        best_match = None
        best_pos = len(remaining)
        best_tag = None
        best_end = 0

        for regex, tag in patterns:
            m = re.search(regex, remaining)
            if m and m.start() < best_pos:
                best_pos = m.start()
                best_match = m
                best_tag = tag
                best_end = m.end()

        if best_match is None:
            tagged.append((default_tag, remaining))
            break

        if best_pos > 0:
            tagged.append((default_tag, remaining[:best_pos]))
        tagged.append((best_tag, best_match.group()))
        remaining = remaining[best_end:]

    return tagged


def _apply_markdown(text_widget, text: str) -> None:
    lines = text.split("\n")
    in_code_block = False
    code_block_lang = ""
    code_block_lines: list[str] = []
    prev_blank = False

    def flush_code_block():
        nonlocal code_block_lines, code_block_lang, in_code_block
        if code_block_lines:
            code_text = "\n".join(code_block_lines)
            theme_name = getattr(text_widget, "_app_theme", "dark")
            theme = DARK if theme_name == "dark" else LIGHT
            tagged = _apply_syntax_highlight(code_text, code_block_lang, theme)
            text_widget.insert("end", "\n")
            for tag, content in tagged:
                text_widget.insert("end", content, (tag,))
            text_widget.insert("end", "\n")
        code_block_lines = []
        code_block_lang = ""

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code_block:
                flush_code_block()
                in_code_block = False
            else:
                in_code_block = True
                code_block_lang = stripped[3:].strip()
            continue

        if in_code_block:
            code_block_lines.append(line)
            continue

        if not stripped:
            if not prev_blank:
                text_widget.insert("end", "\n")
            prev_blank = True
            continue

        prev_blank = False

        if re.match(r'^#{1,3}\s+', stripped):
            label = re.sub(r'^#{1,3}\s+', '', stripped)
            text_widget.insert("end", label + "\n", ("heading",))
            continue

        if re.match(r'^>\s+', stripped):
            quote = re.sub(r'^>\s+', '', stripped)
            text_widget.insert("end", "\u201c ")
            _insert_inline_markdown(text_widget, quote)
            text_widget.insert("end", " \u201d\n", ("blockquote",))
            continue

        if re.match(r'^(\d+)\.\s+', stripped):
            num = re.match(r'^(\d+)\.\s+', stripped).group(1)
            item = re.sub(r'^\d+\.\s+', '', stripped)
            text_widget.insert("end", f"{num}.  ", ("list_item",))
            _insert_inline_markdown(text_widget, item)
            text_widget.insert("end", "\n")
            continue

        if stripped.startswith(("- ", "* ")):
            item = stripped[2:]
            text_widget.insert("end", "\u2022  ", ("list_item",))
            _insert_inline_markdown(text_widget, item)
            text_widget.insert("end", "\n")
            continue

        if re.match(r'^---+$', stripped):
            text_widget.insert("end", "\n", ("divider",))
            continue

        _insert_inline_markdown(text_widget, line)
        text_widget.insert("end", "\n")


def _insert_inline_markdown(text_widget, text: str) -> None:
    pattern = r'(\*\*(.+?)\*\*)|(`(.+?)`)|(\*(.+?)\*)'
    parts = []
    last_end = 0

    for match in re.finditer(pattern, text):
        if match.start() > last_end:
            parts.append(("body", text[last_end:match.start()]))
        if match.group(2):
            parts.append(("bold", match.group(2)))
        elif match.group(4):
            parts.append(("code", match.group(4)))
        elif match.group(6):
            parts.append(("italic", match.group(6)))
        last_end = match.end()

    if last_end < len(text):
        parts.append(("body", text[last_end:]))

    for tag, content in parts:
        text_widget.insert("end", content, (tag,))


class SessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _ROOT / ".avinya_sessions.json"
        self.sessions: dict[str, SessionEntry] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                for sid, entry in data.items():
                    turns = [(t[0], t[1]) for t in entry.get("turns", [])]
                    self.sessions[sid] = SessionEntry(
                        id=sid,
                        title=entry.get("title", "Untitled"),
                        created=entry.get("created", ""),
                        updated=entry.get("updated", ""),
                        turns=turns,
                        summary=entry.get("summary", ""),
                    )
            except Exception:
                self.sessions = {}

    def _save(self) -> None:
        data = {}
        for sid, entry in self.sessions.items():
            data[sid] = {
                "id": entry.id,
                "title": entry.title,
                "created": entry.created,
                "updated": entry.updated,
                "turns": entry.turns,
                "summary": entry.summary,
            }
        self._path.write_text(json.dumps(data, indent=2))

    def create(self) -> SessionEntry:
        now = datetime.now().isoformat()
        entry = SessionEntry(id=str(uuid.uuid4())[:8], title="New chat", created=now, updated=now)
        self.sessions[entry.id] = entry
        self._save()
        return entry

    def update(self, entry: SessionEntry) -> None:
        entry.updated = datetime.now().isoformat()
        if entry.turns:
            first_user = next((t[1] for t in entry.turns if t[0] == "user"), "")
            entry.title = _clip(first_user, 60) or entry.title
        self.sessions[entry.id] = entry
        self._save()

    def delete(self, sid: str) -> None:
        self.sessions.pop(sid, None)
        self._save()

    def list_sorted(self) -> list[SessionEntry]:
        return sorted(self.sessions.values(), key=lambda e: e.updated, reverse=True)

    def export_markdown(self, entry: SessionEntry) -> str:
        parts = [f"# {entry.title}\n", f"Created: {entry.created}\n", f"Updated: {entry.updated}\n", "---\n"]
        for role, text in entry.turns:
            parts.append(f"\n## {'You' if role == 'user' else 'Avinya'}\n\n{text}\n")
        if entry.summary:
            parts.append(f"\n## Summary\n\n{entry.summary}\n")
        return "\n".join(parts)


class AvinyaApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Avinya")
        self.geometry("1460x900")
        self.minsize(1260, 780)

        self._theme_name = "dark"
        self._t = DARK
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=self._t["window"])

        self._ready = False
        self._streaming = False
        self._stream_queue: queue.Queue = queue.Queue()
        self._stream_text = ""
        self._assistant_failed = False
        self._last_query = ""
        self._last_model = MODEL_DEFAULT
        self._last_result: QueryResult | None = None
        self._last_elapsed = 0.0
        self._last_error = ""
        self._ollama_status = "checking"
        self._connection_status = "loading"
        self._current_body_start: str | None = None
        self._current_body_end: str | None = None
        self._copied_text = ""

        self.session_store = SessionStore()
        self._current_session: SessionEntry | None = None
        self._start_new_session()

        self.memory = SessionMemory(max_recent=SESSION_MAX_TURNS)

        self.jarvis = VoiceOrchestrator(self.memory)
        self.jarvis.on_state_change = self._on_jarvis_state
        self.jarvis.on_message = self._on_jarvis_message

        self.tts = TTS(
            str(_ROOT / "assets/models/piper/en_IN_voice.onnx"),
            str(_ROOT / "assets/models/piper/en_IN_voice.onnx.json")
        )

        self._build_layout()
        self._bind_keyboard()
        self.after(50, self._focus_composer)
        self._load_backend_async()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _start_new_session(self) -> None:
        self._current_session = self.session_store.create()
        self._refresh_session_list()

    # Layout
    def _build_layout(self) -> None:
        self.shell = ctk.CTkFrame(self, fg_color=self._t["window"], corner_radius=0)
        self.shell.pack(fill="both", expand=True)

        self.left_panel = ctk.CTkFrame(
            self.shell, width=286, corner_radius=0,
            fg_color=self._t["panel"], border_width=1, border_color=self._t["border"],
        )
        self.left_panel.pack(side="left", fill="y")
        self.left_panel.pack_propagate(False)

        self.center_panel = ctk.CTkFrame(self.shell, corner_radius=0, fg_color=self._t["window"])
        self.center_panel.pack(side="left", fill="both", expand=True)

        self.right_panel = ctk.CTkFrame(
            self.shell, width=330, corner_radius=0,
            fg_color=self._t["panel"], border_width=1, border_color=self._t["border"],
        )
        self.right_panel.pack(side="right", fill="y")
        self.right_panel.pack_propagate(False)

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()

    def _build_left_panel(self) -> None:
        brand = ctk.CTkFrame(self.left_panel, fg_color=self._t["panel"], corner_radius=0)
        brand.pack(fill="x", padx=DS.L, pady=(DS.L, DS.S))
        ctk.CTkLabel(brand, text="Avinya", font=_font(DS.TITLE, True), text_color=self._t["text"]).pack(anchor="w")
        ctk.CTkLabel(brand, text="Research workspace", font=_font(DS.SUBTITLE), text_color=self._t["muted"]).pack(anchor="w", pady=(DS.XS, 0))

        self.left_scroll = ctk.CTkScrollableFrame(self.left_panel, fg_color=self._t["panel"], corner_radius=0)
        self.left_scroll.pack(fill="both", expand=True, padx=DS.S, pady=(0, DS.S))

        self.status_card = self._card(self.left_scroll, "Connection")
        self.status_line = self._card_line(self.status_card, "Status", "loading")
        self.ollama_line = self._card_line(self.status_card, "Ollama", "checking")
        self.model_line = self._card_line(self.status_card, "Models", f"{MODEL_DEFAULT} / {MODEL_REASONING}")

        self.theme_card = self._card(self.left_scroll, "Appearance")
        theme_frame = ctk.CTkFrame(self.theme_card, fg_color="transparent")
        theme_frame.pack(fill="x")
        self.theme_btn = ctk.CTkButton(
            theme_frame, text="Switch to Light", height=32, corner_radius=DS.R_SM,
            font=_font(DS.SM), fg_color=self._t["panel_alt"], text_color=self._t["text"],
            hover_color="#242424", border_width=1, border_color=self._t["border"],
            command=self._toggle_theme,
        )
        self.theme_btn.pack(fill="x")

        self.voice_card = self._card(self.left_scroll, "Voice & Jarvis")
        self.jarvis_switch = ctk.CTkSwitch(
            self.voice_card, text="Jarvis Mode", font=_font(DS.BODY),
            command=self._toggle_jarvis, progress_color=self._t["accent"],
        )
        self.jarvis_switch.pack(anchor="w", pady=(0, DS.S))
        self.voice_switch = ctk.CTkSwitch(
            self.voice_card, text="Voice Output", font=_font(DS.BODY),
            progress_color=self._t["accent"],
        )
        self.voice_switch.pack(anchor="w")

        self.action_card = self._card(self.left_scroll, "Actions")
        self._action_button(self.action_card, "New chat", self._new_chat).pack(fill="x", pady=(0, DS.XS))
        self._action_button(self.action_card, "Export chat", self._export_chat).pack(fill="x", pady=DS.XS)
        self._action_button(self.action_card, "Check Ollama", self._check_ollama).pack(fill="x", pady=DS.XS)
        self._action_button(self.action_card, "Summarize memory", self._recap).pack(fill="x", pady=DS.XS)
        self._action_button(self.action_card, "View Graph", self._view_graph).pack(fill="x", pady=DS.XS)
        self._action_button(self.action_card, "Open Obsidian", self._open_vault).pack(fill="x", pady=DS.XS)

        self.shortcuts_card = self._card(self.left_scroll, "Shortcuts")
        shortcut_grid = ctk.CTkFrame(self.shortcuts_card, fg_color="transparent")
        shortcut_grid.pack(fill="x")
        for idx, (label, prompt) in enumerate([
            ("Summarize", "Summarize the current session and key decisions."),
            ("Budget", "What does the knowledge base say about the budget?"),
            ("Meetings", "Find recent meeting decisions and action items."),
            ("Projects", "Summarize the latest project updates and blockers."),
        ]):
            btn = ctk.CTkButton(
                shortcut_grid, text=label, height=34, corner_radius=DS.R_SM, font=_font(DS.SM),
                fg_color=self._t["panel_alt"], text_color=self._t["text"], hover_color="#242424",
                border_width=1, border_color=self._t["border"],
                command=lambda p=prompt: self._set_composer_text(p),
            )
            btn.grid(row=idx // 2, column=idx % 2, sticky="ew", padx=(0 if idx % 2 == 0 else DS.XS, 0), pady=(0, DS.XS))
            shortcut_grid.grid_columnconfigure(idx % 2, weight=1)

        self.session_list_card = self._card(self.left_scroll, "Sessions")
        self.session_list_frame = ctk.CTkFrame(self.session_list_card, fg_color="transparent")
        self.session_list_frame.pack(fill="x")
        self._refresh_session_list()

        self.recent_card = self._card(self.left_scroll, "Recent turns")
        self.recent_stack = ctk.CTkFrame(self.recent_card, fg_color="transparent")
        self.recent_stack.pack(fill="x")
        self._render_recent_stack()

    def _build_center_panel(self) -> None:
        header = ctk.CTkFrame(self.center_panel, fg_color=self._t["window"], corner_radius=0)
        header.pack(fill="x", padx=DS.L, pady=(DS.L, DS.S))

        title_block = ctk.CTkFrame(header, fg_color="transparent")
        title_block.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(title_block, text="Workspace", font=_font(DS.TITLE, True), text_color=self._t["text"]).pack(anchor="w")
        ctk.CTkLabel(title_block, text="Compact research chat for documents, notes, and follow-up work", font=_font(DS.SUBTITLE), text_color=self._t["muted"]).pack(anchor="w", pady=(DS.XS, 0))

        chip_row = ctk.CTkFrame(header, fg_color="transparent")
        chip_row.pack(side="right", anchor="e")
        self.connection_chip = self._chip(chip_row, "Loading", self._t["warning_soft"], self._t["warning"])
        self.connection_chip.pack(side="left", padx=(0, DS.XS))
        self.model_chip = self._chip(chip_row, MODEL_DEFAULT, self._t["chip_bg"], self._t["text"])
        self.model_chip.pack(side="left", padx=(0, DS.XS))
        self.source_chip = self._chip(chip_row, "0 sources", self._t["panel"], self._t["muted"])
        self.source_chip.pack(side="left")

        command_row = ctk.CTkFrame(self.center_panel, fg_color="transparent")
        command_row.pack(fill="x", padx=DS.L, pady=(0, DS.S))
        for label, prompt in (
            ("Summarize", "Summarize the current session and key decisions."),
            ("Budget", "What does the knowledge base say about the budget?"),
            ("Meetings", "Find recent meeting decisions and action items."),
            ("Projects", "Summarize the latest project updates and blockers."),
        ):
            btn = ctk.CTkButton(
                command_row, text=label, width=112, height=32, corner_radius=DS.R_SM, font=_font(DS.SM),
                fg_color=self._t["panel"], text_color=self._t["text"], hover_color="#232323",
                border_width=1, border_color=self._t["border"],
                command=lambda p=prompt: self._set_composer_text(p),
            )
            btn.pack(side="left", padx=(0, DS.XS))

        transcript_shell = ctk.CTkFrame(
            self.center_panel, fg_color=self._t["panel"], corner_radius=DS.R_MAIN,
            border_width=1, border_color=self._t["border"],
        )
        transcript_shell.pack(fill="both", expand=True, padx=DS.L, pady=(0, DS.S))

        transcript_header = ctk.CTkFrame(transcript_shell, fg_color="transparent")
        transcript_header.pack(fill="x", padx=DS.M, pady=(DS.M, DS.XS))
        ctk.CTkLabel(transcript_header, text="Transcript", font=_font(DS.BODY, True), text_color=self._t["text"]).pack(side="left")
        self.transcript_hint = ctk.CTkLabel(
            transcript_header, text="Enter to send \u00b7 Shift+Enter new line \u00b7 Ctrl+K focus \u00b7 Ctrl+N new \u00b7 Ctrl+E export",
            font=_font(DS.SM), text_color=self._t["muted_soft"],
        )
        self.transcript_hint.pack(side="right")

        transcript_frame = ctk.CTkFrame(transcript_shell, fg_color=self._t["panel"], corner_radius=0)
        transcript_frame.pack(fill="both", expand=True, padx=DS.M, pady=(0, DS.M))

        self.transcript_scroll = tk.Scrollbar(transcript_frame, orient="vertical")
        self.transcript_scroll.pack(side="right", fill="y")

        self.transcript = tk.Text(
            transcript_frame, wrap="word", bg=self._t["panel"], fg=self._t["text"],
            insertbackground=self._t["accent"], relief="flat", bd=0, highlightthickness=0,
            padx=8, pady=8, font=("Segoe UI", 13), yscrollcommand=self.transcript_scroll.set,
        )
        self.transcript._app_theme = self._theme_name
        self.transcript.pack(side="left", fill="both", expand=True)
        self.transcript_scroll.configure(command=self.transcript.yview)
        self.transcript.configure(state="disabled")
        self.transcript.bind("<MouseWheel>", self._on_transcript_mousewheel)
        self.transcript.bind("<Button-4>", self._on_transcript_mousewheel)
        self.transcript.bind("<Button-5>", self._on_transcript_mousewheel)

        self._style_transcript()

        composer_shell = ctk.CTkFrame(
            self.center_panel, fg_color=self._t["panel"], corner_radius=DS.R_MAIN,
            border_width=1, border_color=self._t["border"],
        )
        composer_shell.pack(fill="x", padx=DS.L, pady=(0, DS.L))

        composer_inner = ctk.CTkFrame(composer_shell, fg_color="transparent")
        composer_inner.pack(fill="both", expand=True, padx=DS.M, pady=DS.M)

        self.input_wrap = tk.Frame(composer_inner, bg=self._t["panel"])
        self.input_wrap.pack(side="left", fill="both", expand=True, padx=(0, DS.M))

        self.input_box = tk.Text(
            input_wrap, height=4, wrap="word", bg=self._t["panel_alt"], fg=self._t["text"],
            insertbackground=self._t["accent"], selectbackground=self._t["accent_soft"],
            selectforeground=self._t["text"], relief="flat", bd=0, highlightthickness=1,
            highlightbackground=self._t["border"], highlightcolor=self._t["accent"],
            padx=12, pady=10, font=("Segoe UI", 13), undo=True, autoseparators=True, maxundo=50,
        )
        self.input_box.pack(fill="both", expand=True)
        self.input_box.bind("<Return>", self._on_return)
        self.input_box.bind("<Shift-Return>", self._on_shift_return)
        self.input_box.bind("<Control-Return>", self._on_send_shortcut)
        self.input_box.bind("<Button-1>", lambda _event: self._focus_composer())
        self.input_box.bind("<FocusIn>", lambda _event: self._focus_composer())

        control_column = ctk.CTkFrame(composer_inner, fg_color="transparent")
        control_column.pack(side="right", fill="y")

        self.regenerate_btn = ctk.CTkButton(
            control_column, text="Regenerate", width=108, height=32, corner_radius=DS.R_SM,
            font=_font(DS.SM), fg_color=self._t["panel_alt"], text_color=self._t["muted"],
            hover_color="#242424", border_width=1, border_color=self._t["border"],
            command=self._regenerate,
        )
        self.regenerate_btn.pack(anchor="s", pady=(0, DS.XS))
        self.regenerate_btn.configure(state="disabled")

        self.send_btn = ctk.CTkButton(
            control_column, text="Send", width=108, height=44, corner_radius=DS.R_SM,
            font=_font(DS.BODY, True), fg_color=self._t["accent"], text_color="#ffffff",
            hover_color=self._t["accent_hover"], command=self._send,
        )
        self.send_btn.pack(anchor="s")
        self.send_btn.configure(state="disabled")

        self.composer_hint = ctk.CTkLabel(
            control_column, text="Waiting for Ollama", font=_font(DS.SM), text_color=self._t["muted_soft"],
        )
        self.composer_hint.pack(anchor="e", pady=(DS.S, 0))

    def _build_right_panel(self) -> None:
        title = ctk.CTkFrame(self.right_panel, fg_color=self._t["panel"], corner_radius=0)
        title.pack(fill="x", padx=DS.L, pady=(DS.L, DS.S))
        ctk.CTkLabel(title, text="Sources", font=_font(DS.TITLE, True), text_color=self._t["text"]).pack(anchor="w")
        ctk.CTkLabel(title, text="References and session memory", font=_font(DS.SUBTITLE), text_color=self._t["muted"]).pack(anchor="w", pady=(DS.XS, 0))

        self.right_scroll = ctk.CTkScrollableFrame(self.right_panel, fg_color=self._t["panel"], corner_radius=0)
        self.right_scroll.pack(fill="both", expand=True, padx=DS.S, pady=(0, DS.S))

        self._render_inspector()

    # Helpers
    def _card(self, parent: ctk.CTkFrame, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=self._t["panel_alt"], corner_radius=DS.R_MAIN, border_width=1, border_color=self._t["border"])
        card.pack(fill="x", padx=DS.XS, pady=(0, DS.S))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=DS.M, pady=DS.M)
        ctk.CTkLabel(inner, text=title, font=_font(DS.BODY, True), text_color=self._t["text"]).pack(anchor="w")
        return inner

    def _card_line(self, parent: ctk.CTkFrame, label: str, value: str) -> ctk.CTkLabel:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(DS.XS, 0))
        ctk.CTkLabel(row, text=label, font=_font(DS.SM), text_color=self._t["muted"]).pack(side="left")
        value_label = ctk.CTkLabel(row, text=value, font=_font(DS.SM, True), text_color=self._t["text"], justify="right")
        value_label.pack(side="right")
        return value_label

    def _chip(self, parent: ctk.CTkFrame, text: str, bg: str, fg: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(parent, text=text, font=_font(DS.CHIP, True), text_color=fg, fg_color=bg, corner_radius=999, padx=10, pady=4)

    def _action_button(self, parent: ctk.CTkFrame, text: str, command) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent, text=text, height=36, corner_radius=DS.R_SM, font=_font(DS.BODY),
            fg_color=self._t["panel_alt"], text_color=self._t["text"], hover_color="#242424",
            border_width=1, border_color=self._t["border"], command=command,
        )

    def _style_transcript(self) -> None:
        t = self._t
        self.transcript.tag_configure("user_title", foreground=t["accent"], font=("Segoe UI", 11, "bold"))
        self.transcript.tag_configure("assistant_title", foreground=t["text"], font=("Segoe UI", 11, "bold"))
        self.transcript.tag_configure("body", foreground=t["text"], font=("Segoe UI", 13))
        self.transcript.tag_configure("meta", foreground=t["muted_soft"], font=("Segoe UI", 10))
        self.transcript.tag_configure("divider", foreground=t["border_strong"])
        self.transcript.tag_configure("error", foreground=t["danger"])
        self.transcript.tag_configure("bold", font=("Segoe UI", 13, "bold"))
        self.transcript.tag_configure("italic", font=("Segoe UI", 13, "italic"))
        self.transcript.tag_configure("code", font=("Consolas", "Courier New", 12), background=t["code_bg"], foreground=t["accent"])
        self.transcript.tag_configure("code_block", font=("Consolas", "Courier New", 12), background=t["code_bg"], foreground=t["text"], lmargin1=12, lmargin2=12)
        self.transcript.tag_configure("code_keyword", font=("Consolas", "Courier New", 12), background=t["code_bg"], foreground=SYNTAX_COLORS["keyword"], lmargin1=12, lmargin2=12)
        self.transcript.tag_configure("code_string", font=("Consolas", "Courier New", 12), background=t["code_bg"], foreground=SYNTAX_COLORS["string"], lmargin1=12, lmargin2=12)
        self.transcript.tag_configure("code_comment", font=("Consolas", "Courier New", 12), background=t["code_bg"], foreground=SYNTAX_COLORS["comment"], lmargin1=12, lmargin2=12)
        self.transcript.tag_configure("code_number", font=("Consolas", "Courier New", 12), background=t["code_bg"], foreground=SYNTAX_COLORS["number"], lmargin1=12, lmargin2=12)
        self.transcript.tag_configure("code_function", font=("Consolas", "Courier New", 12), background=t["code_bg"], foreground=SYNTAX_COLORS["function"], lmargin1=12, lmargin2=12)
        self.transcript.tag_configure("list_item", foreground=t["text"], font=("Segoe UI", 13), lmargin1=20, lmargin2=20)
        self.transcript.tag_configure("heading", foreground=t["accent"], font=("Segoe UI", 14, "bold"))
        self.transcript.tag_configure("blockquote", foreground=t["muted"], font=("Segoe UI", 13, "italic"), lmargin1=16, lmargin2=16)

    def _insert_transcript(self, title: str, body: str, *, role: str, meta: str | None = None) -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{title}\n", (f"{role}_title",))
        body_start = self.transcript.index("end")
        if body:
            self.transcript.insert("end", body, ("body",))
        self.transcript.insert("end", "\n")
        if meta:
            self.transcript.insert("end", f"{meta}\n", ("meta",))
        self.transcript.insert("end", "\n")
        self.transcript.configure(state="disabled")
        self._scroll_transcript_bottom()
        self._current_body_start = body_start
        self._current_body_end = self.transcript.index("end-2c") if body else body_start

    def _replace_current_assistant_body(self, text: str) -> None:
        if self._current_body_start is None:
            return
        self.transcript.configure(state="normal")
        try:
            if self._current_body_end is not None:
                self.transcript.delete(self._current_body_start, self._current_body_end)
            self.transcript.insert(self._current_body_start, text, ("body",))
            self._current_body_end = self.transcript.index(f"{self._current_body_start}+{len(text)}c")
        finally:
            self.transcript.configure(state="disabled")
        self._scroll_transcript_bottom()

    def _append_assistant_footer(self, footer: str) -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{footer}\n\n", ("meta",))
        self.transcript.configure(state="disabled")
        self._scroll_transcript_bottom()

    def _format_current_body_markdown(self) -> None:
        if self._current_body_start is None or not self._stream_text:
            return
        self.transcript.configure(state="normal")
        try:
            self.transcript.delete(self._current_body_start, self._current_body_end or "end-1c")
            _apply_markdown(self.transcript, self._stream_text)
            self._current_body_end = self.transcript.index("end-1c")
        finally:
            self.transcript.configure(state="disabled")
        self._scroll_transcript_bottom()

    def _copy_last_response(self) -> None:
        text = self._copied_text or self._stream_text
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_line.configure(text="copied to clipboard")
            self.after(1500, lambda: self.status_line.configure(text="ready" if not self._last_error else "degraded"))

    def _append_copy_button(self, text_to_copy: str) -> None:
        self._copied_text = text_to_copy
        self.transcript.configure(state="normal")
        self.transcript.window_create("end-1c", window=self._make_copy_button())
        self.transcript.insert("end", "\n\n")
        self.transcript.configure(state="disabled")

    def _make_copy_button(self) -> ctk.CTkButton:
        return ctk.CTkButton(
            self.transcript, text="Copy", width=64, height=26, corner_radius=DS.R_SM, font=_font(DS.SM),
            fg_color=self._t["panel_alt"], text_color=self._t["muted"], hover_color=self._t["border"],
            border_width=1, border_color=self._t["border"], command=self._copy_last_response,
        )

    def _scroll_transcript_bottom(self) -> None:
        try:
            self.transcript.see("end")
        except Exception:
            pass

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

    def _view_graph(self) -> None:
        graph_html = _ROOT / "CKB" / "graph.html"
        if graph_html.exists():
            webbrowser.open(f"file://{graph_html.absolute()}")
        else:
            self.status_line.configure(text="graph not found")

    def _open_vault(self) -> None:
        vault_dir = _ROOT / "knowledge_vault"
        if vault_dir.exists():
            webbrowser.open(f"obsidian://open?path={vault_dir.absolute()}")
        else:
            self.status_line.configure(text="vault not found")

    # Theme
    def _toggle_theme(self) -> None:
        if self._theme_name == "dark":
            self._theme_name = "light"
            self._t = LIGHT
            ctk.set_appearance_mode("light")
            self.theme_btn.configure(text="Switch to Dark")
        else:
            self._theme_name = "dark"
            self._t = DARK
            ctk.set_appearance_mode("dark")
            self.theme_btn.configure(text="Switch to Light")
        self._apply_theme()

    def _apply_theme(self) -> None:
        t = self._t
        self.configure(fg_color=t["window"])
        self.shell.configure(fg_color=t["window"])
        self.left_panel.configure(fg_color=t["panel"], border_color=t["border"])
        self.center_panel.configure(fg_color=t["window"])
        self.right_panel.configure(fg_color=t["panel"], border_color=t["border"])
        self.transcript.configure(bg=t["panel"], fg=t["text"], insertbackground=t["accent"])
        self.input_box.configure(bg=t["panel_alt"], fg=t["text"], insertbackground=t["accent"], highlightbackground=t["border"], highlightcolor=t["accent"])
        self.input_wrap.configure(bg=t["panel"])
        self._style_transcript()
        self._render_inspector()
        self._refresh_session_list()

    # Sessions
    def _refresh_session_list(self) -> None:
        for child in self.session_list_frame.winfo_children():
            child.destroy()
        sessions = self.session_store.list_sorted()[:8]
        if not sessions:
            ctk.CTkLabel(self.session_list_frame, text="No sessions", font=_font(DS.SM), text_color=self._t["muted"]).pack(anchor="w")
            return
        t = self._t
        for s in sessions:
            is_active = self._current_session and s.id == self._current_session.id
            row = ctk.CTkFrame(self.session_list_frame, fg_color=t["panel"] if is_active else "transparent", corner_radius=DS.R_SM)
            row.pack(fill="x", pady=(0, DS.XS))
            ctk.CTkLabel(
                row, text=f"{s.title[:30]}", font=_font(DS.SM, is_active),
                text_color=t["accent"] if is_active else t["text"],
                anchor="w", justify="left", wraplength=230,
            ).pack(side="left", fill="x", expand=True, padx=DS.XS, pady=DS.XS)
            if not is_active:
                ctk.CTkButton(
                    row, text="Load", width=40, height=22, corner_radius=DS.R_SM, font=_font(DS.SM - 1),
                    fg_color=t["panel_alt"], text_color=t["muted"], hover_color=t["border"],
                    border_width=1, border_color=t["border"],
                    command=lambda sid=s.id: self._load_session(sid),
                ).pack(side="right", padx=DS.XS, pady=DS.XS)
                ctk.CTkButton(
                    row, text="\u00d7", width=22, height=22, corner_radius=DS.R_SM, font=_font(DS.SM - 1),
                    fg_color=t["danger_soft"], text_color=t["danger"], hover_color=t["danger"],
                    command=lambda sid=s.id: self._delete_session(sid),
                ).pack(side="right", padx=(0, DS.XS), pady=DS.XS)

    def _load_session(self, sid: str) -> None:
        entry = self.session_store.sessions.get(sid)
        if not entry:
            return
        self._current_session = entry
        self.memory.clear()
        for role, text in entry.turns:
            if role == "user":
                self.memory.add_user_message(text)
            else:
                self.memory.add_assistant_message(text)
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")
        self._render_transcript_history()
        self._refresh_session_list()
        self._refresh_sidebar_snapshot()
        self._render_inspector()

    def _delete_session(self, sid: str) -> None:
        if self._current_session and self._current_session.id == sid:
            return
        self.session_store.delete(sid)
        self._refresh_session_list()

    def _save_current_session(self) -> None:
        if not self._current_session:
            return
        self._current_session.turns = list(self.memory.recent)
        self._current_session.summary = self.memory.get_summary()
        self.session_store.update(self._current_session)

    def _export_chat(self) -> None:
        if not self._current_session:
            return
        md = self.session_store.export_markdown(self._current_session)
        path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All", "*.*")],
            initialfile=f"avinya_{self._current_session.id}.md",
        )
        if path:
            Path(path).write_text(md)
            self.status_line.configure(text="exported")
            self.after(1500, lambda: self.status_line.configure(text="ready"))

    # Keyboard
    def _bind_keyboard(self) -> None:
        self.bind("<Control-k>", lambda _e: self._focus_composer())
        self.bind("<Control-K>", lambda _e: self._focus_composer())
        self.bind("<Control-n>", lambda _e: self._new_chat())
        self.bind("<Control-N>", lambda _e: self._new_chat())
        self.bind("<Control-e>", lambda _e: self._export_chat())
        self.bind("<Control-E>", lambda _e: self._export_chat())
        self.bind("<Control-Shift-C>", lambda _e: self._copy_last_response())

    # Backend lifecycle
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
        self.connection_chip.configure(
            text="Ready" if self._ready else ("Degraded" if self._connection_status == "ready" else "Error"),
            fg_color=self._t["accent_soft"] if self._ready else self._t["warning_soft"],
            text_color=self._t["accent"] if self._ready else self._t["warning"],
        )
        self.status_line.configure(text=self._connection_status)
        self.ollama_line.configure(text=self._ollama_status)
        self.model_chip.configure(text=MODEL_DEFAULT)
        self.send_btn.configure(state="normal" if self._ready else "disabled")
        self.composer_hint.configure(text="Enter to send" if self._ready else "Waiting for Ollama")
        self._refresh_sidebar_snapshot()
        self._render_inspector()
        self._focus_composer()

    def _check_ollama(self) -> None:
        try:
            check_ollama()
            self._ollama_status = "running"
            self._last_error = ""
            self.status_line.configure(text="ollama ready")
        except OllamaError as exc:
            self._ollama_status = "down"
            self._last_error = str(exc)
            self.status_line.configure(text="ollama error")
        self._ready = self._connection_status == "ready" and self._ollama_status == "running"
        self.send_btn.configure(state="normal" if self._ready else "disabled")
        self.composer_hint.configure(text="Enter to send" if self._ready else "Waiting for Ollama")
        self.ollama_line.configure(text=self._ollama_status)
        self._refresh_sidebar_snapshot()
        self._render_inspector()

    # Transcript / inspector
    def _render_recent_stack(self) -> None:
        for child in self.recent_stack.winfo_children():
            child.destroy()
        recent = list(self.memory.recent[-6:])
        if not recent:
            ctk.CTkLabel(self.recent_stack, text="No recent turns", font=_font(DS.SM), text_color=self._t["muted"]).pack(anchor="w", pady=(DS.XS, 0))
            return
        for role, text in recent:
            row = ctk.CTkFrame(self.recent_stack, fg_color="transparent")
            row.pack(fill="x", pady=(0, DS.XS))
            ctk.CTkLabel(
                row, text="You" if role == "user" else "Avinya", font=_font(DS.CHIP, True),
                text_color=self._t["accent"] if role == "user" else self._t["text"],
                fg_color=self._t["chip_bg"], corner_radius=999, padx=8, pady=2,
            ).pack(anchor="w", pady=(0, DS.XS))
            ctk.CTkLabel(
                row, text=_clip(text, 110), font=_font(DS.SM), text_color=self._t["text"],
                justify="left", anchor="w", wraplength=230,
            ).pack(anchor="w")

    def _render_inspector(self) -> None:
        for child in self.right_scroll.winfo_children():
            child.destroy()
        t = self._t

        status = self._card(self.right_scroll, "Session")
        self._card_line(status, "Backend", self._connection_status)
        self._card_line(status, "Ollama", self._ollama_status)
        self._card_line(status, "Ready", "yes" if self._ready else "no")
        self._card_line(status, "Streaming", "yes" if self._streaming else "no")

        sources = self._card(self.right_scroll, "Sources")
        if self._last_result and self._last_result.sources:
            for src in self._last_result.sources[:4]:
                card = ctk.CTkFrame(sources, fg_color=t["panel"], corner_radius=DS.R_MAIN, border_width=1, border_color=t["border"])
                card.pack(fill="x", pady=(0, DS.XS))
                ctk.CTkLabel(card, text=_source_title(src), font=_font(DS.SM, True), text_color=t["text"]).pack(anchor="w", padx=DS.M, pady=(DS.S, 0))
                ctk.CTkLabel(card, text=_clip(_lines(src.chunk, limit=2).replace("\n", " "), 150), font=_font(DS.SM), text_color=t["muted"], justify="left", anchor="w", wraplength=250).pack(anchor="w", padx=DS.M, pady=(DS.XS, DS.S))
                file_path = Path(src.source)
                if file_path.exists():
                    ctk.CTkButton(
                        card, text="Open", width=48, height=20, corner_radius=DS.R_SM, font=_font(DS.SM - 1),
                        fg_color=t["panel_alt"], text_color=t["muted"], hover_color=t["border"],
                        border_width=1, border_color=t["border"],
                        command=lambda p=str(file_path): self._open_source_file(p),
                    ).pack(anchor="e", padx=DS.M, pady=(0, DS.S))
        else:
            ctk.CTkLabel(sources, text="Waiting for a question.", font=_font(DS.SM), text_color=t["muted"]).pack(anchor="w", pady=(DS.XS, 0))

        notes = self._card(self.right_scroll, "Notes")
        summary = self.memory.get_summary().strip() or "No rolling summary yet."
        ctk.CTkLabel(notes, text=_clip(_lines(summary, limit=6), 520), font=_font(DS.SM), text_color=t["text"], justify="left", anchor="w", wraplength=250).pack(anchor="w", pady=(DS.XS, 0))
        self._card_line(notes, "Recent turns", str(self.memory.user_turn_count()))

        activity = self._card(self.right_scroll, "Activity")
        self._card_line(activity, "Model", self._last_model or MODEL_DEFAULT)
        self._card_line(activity, "Latency", f"{self._last_elapsed:.2f}s" if self._last_elapsed else "\u2014")
        if self._last_error:
            ctk.CTkLabel(activity, text=_clip(self._last_error, 220), font=_font(DS.SM), text_color=t["danger"], justify="left", anchor="w", wraplength=250).pack(anchor="w", pady=(DS.S, 0))

    def _open_source_file(self, path: str) -> None:
        import subprocess
        try:
            subprocess.Popen(["start", path], shell=True)
        except Exception:
            webbrowser.open(f"file://{path}")

    def _refresh_sidebar_snapshot(self) -> None:
        self.status_line.configure(text=self._connection_status)
        self.ollama_line.configure(text=self._ollama_status)
        self._render_recent_stack()

    # Interaction
    def _on_return(self, event) -> str | None:
        if event.state & 0x0001:
            return None
        self._send()
        return "break"

    def _on_shift_return(self, _event) -> str | None:
        return None

    def _on_send_shortcut(self, _event) -> str | None:
        self._send()
        return "break"

    def _new_chat(self) -> None:
        self._save_current_session()
        self.memory.clear()
        self._last_query = ""
        self._last_result = None
        self._last_elapsed = 0.0
        self._last_error = ""
        self._current_body_start = None
        self._current_body_end = None
        self._stream_text = ""
        self._copied_text = ""
        self.regenerate_btn.configure(state="disabled")
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")
        self._start_new_session()
        self._render_transcript_history()
        self._refresh_sidebar_snapshot()
        self._render_inspector()

    def _render_transcript_history(self) -> None:
        if not self.memory.recent:
            self._insert_transcript("Avinya", "Ready when you are.", role="assistant", meta="Local RAG chat")
            return
        for role, message in self.memory.recent:
            if role == "user":
                self._insert_transcript("You", message, role="user")
            else:
                self._insert_transcript("Avinya", message, role="assistant")

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

    def _regenerate(self) -> None:
        if self._streaming or not self._last_query:
            return
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")
        self.memory.clear()
        self._stream_text = ""
        self._assistant_failed = False
        self._last_result = None
        self._last_elapsed = 0.0
        self._last_error = ""
        self._current_body_start = None
        self._current_body_end = None
        self._copied_text = ""
        self._send_force(self._last_query)

    def _send(self) -> None:
        if self._streaming:
            return
        if not self._ready:
            self.status_line.configure(text="backend not ready")
            self.composer_hint.configure(text="Waiting for Ollama")
            self._check_ollama()
            return
        raw = self.input_box.get("1.0", "end").strip()
        if not raw:
            return
        self._send_force(raw)

    def _send_force(self, raw: str) -> None:
        self.input_box.delete("1.0", "end")
        self._last_query = raw
        self._last_result = None
        self._last_error = ""
        self.memory.add_user_message(raw)
        self._insert_transcript("You", raw, role="user")
        self._streaming = True
        self._assistant_failed = False
        self._stream_text = ""
        self._copied_text = ""
        self.send_btn.configure(state="disabled")
        self.regenerate_btn.configure(state="disabled")
        self.status_line.configure(text="thinking")

        self._insert_transcript("Avinya", "", role="assistant", meta="thinking")
        self._current_body_end = self._current_body_start

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
                elif kind == "tok":
                    token = item[1]
                    self._stream_text += token
                    self._replace_current_assistant_body(self._stream_text)
                elif kind == "err":
                    self._assistant_failed = True
                    self._last_error = item[1]
                    self._stream_text = (self._stream_text + "\n\n" + f"Error: {item[1]}").strip()
                    self._replace_current_assistant_body(self._stream_text)
                    self._append_assistant_footer("error")
                    self.status_line.configure(text="error")
                elif kind == "done":
                    self._streaming = False
                    self._last_elapsed = float(item[1]) if len(item) > 1 else 0.0
                    self.send_btn.configure(state="normal")
                    self.regenerate_btn.configure(state="normal" if self._last_query else "disabled")

                    if self._stream_text and not self._assistant_failed:
                        self._format_current_body_markdown()

                    footer = self._last_result.source_labels if self._last_result else "no sources"
                    if self._last_elapsed:
                        footer = f"{footer} \u00b7 {self._last_elapsed:.2f}s"
                    self._append_assistant_footer(footer)
                    self._append_copy_button(self._stream_text)

                    if self.voice_switch.get() and self._stream_text and not self._assistant_failed:
                        self.tts.speak_async(self._stream_text)

                    if self._stream_text and not self._assistant_failed:
                        self.memory.add_assistant_message(self._stream_text)
                        threading.Thread(target=lambda: maybe_roll_summary(self.memory), daemon=True).start()

                    self._save_current_session()
                    self._stream_text = ""
                    self._current_body_start = None
                    self._current_body_end = None
                    self.status_line.configure(text="ready" if not self._last_error else "degraded")
                    self._refresh_sidebar_snapshot()
                    self._render_inspector()
                    self._scroll_transcript_bottom()
                    return
        except queue.Empty:
            self.after(35, self._pump_stream)

    def _on_transcript_mousewheel(self, event) -> str:
        delta = 0
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        elif getattr(event, "delta", 0):
            delta = -1 if event.delta > 0 else 1
        try:
            self.transcript.yview_scroll(delta, "units")
        except Exception:
            pass
        return "break"

    def _on_close(self) -> None:
        self._save_current_session()
        try:
            self.jarvis.stop()
        except Exception:
            pass
        self.destroy()

    # Jarvis & Voice
    def _toggle_jarvis(self) -> None:
        if self.jarvis_switch.get():
            self.jarvis.start()
            self.status_line.configure(text="Jarvis Mode active")
        else:
            self.jarvis.stop()
            self.status_line.configure(text="ready")

    def _on_jarvis_state(self, state: str) -> None:
        icons = {
            "LISTENING_WAKE_WORD": "Jarvis: Listening (Hey Jarvis)\u2026",
            "RECORDING_COMMAND": "Jarvis: Listening to you\u2026",
            "TRANSCRIBING": "Jarvis: Understanding\u2026",
            "THINKING": "Jarvis: Thinking\u2026",
            "SPEAKING": "Jarvis: Speaking\u2026",
        }
        msg = icons.get(state, state)
        self.after(0, lambda: self.status_line.configure(text=msg))

    def _on_jarvis_message(self, role: str, text: str) -> None:
        if role == "user":
            self.after(0, lambda: self._handle_jarvis_user(text))
        elif role == "assistant_partial":
            self.after(0, lambda: self._handle_jarvis_partial(text))
        elif role == "assistant_final":
            self.after(0, lambda: self._handle_jarvis_final(text))

    def _handle_jarvis_user(self, text: str) -> None:
        self._insert_transcript("You", text, role="user")
        self._stream_text = ""
        self._insert_transcript("Avinya", "", role="assistant", meta="thinking")
        self._current_body_end = self._current_body_start

    def _handle_jarvis_partial(self, text: str) -> None:
        self._stream_text += text + " "
        self._replace_current_assistant_body(self._stream_text.strip())

    def _handle_jarvis_final(self, text: str) -> None:
        self._replace_current_assistant_body(text)
        self._format_current_body_markdown()
        self._append_assistant_footer("jarvis voice mode")
        self._append_copy_button(text)
        self._stream_text = text
        self._current_body_start = None
        self._current_body_end = None
        self._save_current_session()
        self._refresh_sidebar_snapshot()
        self._scroll_transcript_bottom()


def main() -> None:
    app = AvinyaApp()
    app._render_transcript_history()
    app.mainloop()


if __name__ == "__main__":
    main()

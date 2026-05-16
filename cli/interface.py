from __future__ import annotations

import time

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table

from core.config import SESSION_MAX_TURNS
from core.prompt_builder import build_full_prompt
from core.session_ops import maybe_roll_summary
from llm.ollama_adapter import OllamaError, check_ollama, generate_stream
from llm.router import choose_model
from memory.session_memory import SessionMemory
from memory.summarizer import summarize_conversation
from retrieval import retrieve_context

console = Console()
_MEMORY = SessionMemory(max_recent=SESSION_MAX_TURNS)


def _thinking() -> None:
    spinner = Spinner("dots", text="Retrieving & reasoning…", style="dim")
    with Live(spinner, console=console, refresh_per_second=12):
        time.sleep(0.35)


def _print_help() -> None:
    table = Table(title="Avinya commands", show_header=False, border_style="dim")
    table.add_column("Cmd", style="cyan")
    table.add_column("Description")
    table.add_row("exit, quit", "Leave Avinya")
    table.add_row("help, ?", "This help")
    table.add_row("clear", "Reset session memory (summary + recent chat)")
    table.add_row("summary", "Show rolling summary text")
    table.add_row("recap", "Summarize recent dialogue into long-term memory now")
    table.add_row("check", "Ping Ollama")
    console.print(Panel(table, border_style="yellow"))


def start_cli() -> None:
    console.print(
        "\n[bold cyan]AVINYA[/bold cyan]  "
        "[dim]local RAG · session memory · type [bold]help[/bold] for commands[/dim]\n"
    )

    try:
        check_ollama()
    except OllamaError as e:
        console.print(f"[red]Warning:[/red] {e}\n")

    while True:
        user_input = console.input("[bold green]› [/bold green]").strip()
        if not user_input:
            continue

        low = user_input.lower()
        if low in ("exit", "quit", ":q"):
            console.print("\n[dim]Goodbye.[/dim]\n")
            break

        if low in ("help", "?", "/help", ":help"):
            _print_help()
            continue

        if low == "clear":
            _MEMORY.clear()
            console.print("[dim]Session memory cleared.[/dim]\n")
            continue

        if low == "summary":
            s = _MEMORY.get_summary().strip()
            console.print(Panel(s or "[dim](empty)[/dim]", title="Rolling summary", border_style="cyan"))
            continue

        if low == "recap":
            block = _MEMORY.get_recent_context().strip()
            if not block:
                console.print("[dim]Nothing recent to recap.[/dim]\n")
                continue
            with console.status("[dim]Summarizing…[/dim]", spinner="dots"):
                merged = summarize_conversation(_MEMORY.get_summary() + "\n\n" + block)
            if merged:
                _MEMORY.update_summary(merged)
                _MEMORY.clear_recent_only()
                console.print("[dim]Updated long-term memory from recap.[/dim]\n")
            continue

        if low == "check":
            try:
                check_ollama()
                console.print("[green]Ollama is reachable.[/green]\n")
            except OllamaError as e:
                console.print(f"[red]{e}[/red]\n")
            continue

        _MEMORY.add_user_message(user_input)
        _thinking()

        model = choose_model(user_input)
        kb_text, source = retrieve_context(user_input)
        prompt = build_full_prompt(user_input, kb_text, _MEMORY)

        meta = Table.grid(expand=True)
        meta.add_column(justify="left", ratio=1)
        meta.add_column(justify="right", ratio=1)
        meta.add_row(
            f"[dim]sources[/dim] [yellow]{source or '—'}[/yellow]",
            f"[dim]model[/dim] [magenta]{model}[/magenta]",
        )
        console.print(meta)
        console.print()

        console.print("[bold cyan]Avinya[/bold cyan] ", end="")
        response = ""
        try:
            for token in generate_stream(prompt, model):
                print(token, end="", flush=True)
                response += token
            print("\n")
        except OllamaError as e:
            console.print(f"\n[red]Ollama error:[/red] {e}\n")
            response = ""

        if response:
            _MEMORY.add_assistant_message(response)
            with console.status("[dim]Compressing long-term memory…[/dim]", spinner="dots"):
                maybe_roll_summary(_MEMORY)

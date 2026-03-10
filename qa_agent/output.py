"""qa_agent/output.py

Central terminal rendering for all qa-agent commands.

Public API (new rich-based):
    console                 — shared rich Console instance
    print_header()          — branded panel header for every command
    print_footer()          — status footer with rule lines
    print_summary_table()   — key-value summary table (regression / analyse)
    print_welcome()         — full ASCII logo + quick-start (hello command)
    arrow_select()          — shared interactive arrow-key selector (TTY only)
    confirm()               — Y/n prompt
    render_tool_result_card() — agentic tool result preview card with
                               Accept/Reject interaction (Run→Show→Accept/Reject)
    Spinner                 — deprecated; use console.status() instead

Legacy API (kept for backward compat — imports still work):
    bold, cyan, red, green, yellow, dim, magenta, rule
    print_banner, print_doctor_banner, print_regression_banner
    print_success, print_error, render_line
"""

from __future__ import annotations

import importlib.metadata
import importlib.metadata
import os
import select
import signal
import subprocess
import sys
import termios
import tty
from typing import Any

# ── rich imports ──────────────────────────────────────────────────────────────
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

# ─────────────────────────────────────────────────────────────────────────────
# Shared Console instance (auto-detects TTY; disables markup when piped)
# ─────────────────────────────────────────────────────────────────────────────
console = Console(highlight=False)

# ─────────────────────────────────────────────────────────────────────────────
# TTY detection  (used by legacy helpers + arrow_select)
# ─────────────────────────────────────────────────────────────────────────────
USE_COLOR: bool = sys.stdout.isatty()

# ─────────────────────────────────────────────────────────────────────────────
# Colour palette — dark blue / navy brand theme
#
#   Brand / headings : bold bright_cyan    (#00CFFF — arctic blue)
#   Success          : bold green          (#00E676)
#   Warning          : bold yellow         (#FFD740)
#   Error            : bold red            (#FF5252)
#   Accent           : bold magenta        (#E040FB — neon purple)
#   Secondary        : dim                 (muted grey)
# ─────────────────────────────────────────────────────────────────────────────

STYLE_BRAND   = "bold bright_cyan"
STYLE_SUCCESS = "bold green"
STYLE_WARN    = "bold yellow"
STYLE_ERROR   = "bold red"
STYLE_ACCENT  = "bold magenta"
STYLE_DIM     = "dim"
STYLE_PANEL   = "bright_cyan"          # panel border colour

# ─────────────────────────────────────────────────────────────────────────────
# Legacy ANSI colour helpers  (kept for backward compatibility)
# ─────────────────────────────────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
    """Wrap *text* in an ANSI escape sequence (no-op when not a TTY)."""
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def bold(t: str) -> str:    return _c("1", t)
def cyan(t: str) -> str:    return _c("1;36", t)
def green(t: str) -> str:   return _c("1;32", t)
def yellow(t: str) -> str:  return _c("1;33", t)
def red(t: str) -> str:     return _c("1;31", t)
def dim(t: str) -> str:     return _c("2", t)
def magenta(t: str) -> str: return _c("1;35", t)


def rule(char: str = "─", width: int = 60) -> str:
    return dim(char * width)


# ─────────────────────────────────────────────────────────────────────────────
# Version helper
# ─────────────────────────────────────────────────────────────────────────────

def _get_version() -> str:
    """Read version from package metadata, fallback to 'dev'."""
    try:
        return importlib.metadata.version("qa-agent")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


# ─────────────────────────────────────────────────────────────────────────────
# ASCII logo  (6 rows × ~48 cols — fits cleanly inside a 60-wide panel)
# ─────────────────────────────────────────────────────────────────────────────

QA_AGENT_LOGO = r"""\
    ██████╗  █████╗        █████╗  ██████╗ ███████╗███╗   ██╗████████╗
   ██╔═══██╗██╔══██╗      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
   ██║   ██║███████║█████╗███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║
   ██║▄▄ ██║██╔══██║╚════╝██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║
   ╚██████╔╝██║  ██║      ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║
    ╚══▀▀═╝ ╚═╝  ╚═╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝"""


# ─────────────────────────────────────────────────────────────────────────────
# NEW: Branded header panel  (used by every command)
# ─────────────────────────────────────────────────────────────────────────────

def print_header(command: str, subtitle: str = "", *, full: bool = False) -> None:
    """Print the branded command header panel.

    Args:
        command:  Sub-command name, e.g. ``"doctor"``.
        subtitle: One-liner shown next to the command name.
        full:     If True, render the full ASCII logo (hello only).
    """
    version = _get_version()
    if full:
        # Write logo lines directly to stdout with raw ANSI codes.
        # rich's console.print() miscounts Unicode block-char cell widths and
        # clips the right edge — raw write is the only safe approach.
        CYAN_BOLD = "\033[1;96m" if USE_COLOR else ""
        RESET     = "\033[0m"   if USE_COLOR else ""
        sys.stdout.write("\n")
        for line in QA_AGENT_LOGO.splitlines():
            sys.stdout.write(f"{CYAN_BOLD}  {line}{RESET}\n")
        sys.stdout.flush()
        # Info block below logo — safe to use rich Panel (no wide chars)
        info = Text()
        info.append("  Automate DV regression runs & post-regression triage.", style="bold white")
        info.append("\n  regression · analyse · summarise (AI) · doctor", style="dim")
        info.append(f"\n  v{version}", style="dim")
        console.print()
        console.print(Panel(info, border_style=STYLE_PANEL, expand=False, padding=(0, 2)))
    else:
        header = Text()
        header.append(f"qa-agent {command}", style=STYLE_BRAND)
        if subtitle:
            header.append(f"  ·  {subtitle}", style=STYLE_DIM)
        header.append(f"\n  v{version}", style=STYLE_DIM)
        console.print()
        console.print(Panel(header, border_style=STYLE_PANEL, expand=False, padding=(0, 1)))


# ─────────────────────────────────────────────────────────────────────────────
# NEW: Shared footer
# ─────────────────────────────────────────────────────────────────────────────

def print_footer(message: str, *, success: bool = True) -> None:
    """Print a status footer with rule separators."""
    icon_style = STYLE_SUCCESS if success else STYLE_ERROR
    icon = "✓" if success else "✗"
    t = Text()
    t.append(f"  {icon}  ", style=icon_style)
    t.append(message, style="bold")
    console.print()
    console.rule(style="dim bright_cyan")
    console.print(t)
    console.rule(style="dim bright_cyan")
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# NEW: Summary table  (used by regression + analyse)
# ─────────────────────────────────────────────────────────────────────────────

def print_summary_table(rows: list[tuple[str, str]]) -> None:
    """Print a key-value summary table."""
    table = Table(
        show_header=False,
        box=box.ROUNDED,
        border_style="bright_cyan",
        padding=(0, 2),
    )
    table.add_column("Key", style="bold white", min_width=12)
    table.add_column("Value", style="dim")
    for key, value in rows:
        table.add_row(key, value)
    console.print(table)


# ─────────────────────────────────────────────────────────────────────────────
# doctor section table helper
# ─────────────────────────────────────────────────────────────────────────────

def render_doctor_table(title: str, results: list[Any]) -> None:
    """Render one doctor section as a rich table.

    results: list of CheckResult objects (duck-typed to avoid circular import).
    """
    icon_map = {
        "ok":    Text("✓", style=STYLE_SUCCESS),
        "warn":  Text("⚠", style=STYLE_WARN),
        "error": Text("✗", style=STYLE_ERROR),
    }
    table = Table(
        show_header=False,
        box=box.ROUNDED,
        border_style="bright_cyan",
        title=f"  {title}",
        title_style="bold white",
        title_justify="left",
        padding=(0, 1),
    )
    table.add_column("Icon", width=3)
    table.add_column("Label", style="bold", min_width=26)
    table.add_column("Detail", style="dim")

    for r in results:
        icon = icon_map.get(r.status.value, Text("?"))
        table.add_row(icon, r.label, r.detail)
        if r.fix:
            for fix_line in r.fix.splitlines():
                arrow = Text("  → ", style="bold bright_cyan")
                table.add_row("", arrow, Text(fix_line, style="dim"))

    console.print(table)


# ─────────────────────────────────────────────────────────────────────────────
# Welcome screen  (hello command)
# ─────────────────────────────────────────────────────────────────────────────

def print_welcome() -> None:
    """Print the full welcome screen with ASCII logo and quick-start table."""
    print_header("", full=True)

    # Quick-start table
    table = Table(
        show_header=False,
        box=box.ROUNDED,
        border_style="bright_cyan",
        title="  Quick start",
        title_style="bold white",
        title_justify="left",
        padding=(0, 2),
    )
    table.add_column("Command", style="bold bright_cyan", min_width=26)
    table.add_column("Description", style="dim")

    cmds = [
        ("qa-agent doctor",      "Verify SDKs, credentials & environment"),
        ("qa-agent regression",  "Run a regression (basic or slurm mode)"),
        ("qa-agent analyse",     "Triage failures: re-run debug, generate QA report"),
        ("qa-agent summarise .", "AI code summary — Claude / OpenAI / Gemini"),
        ("qa-agent guide",       "Short user guide for any command"),
    ]
    for cmd, desc in cmds:
        table.add_row(cmd, desc)

    console.print(table)
    console.print()
    console.print(
        "  Run  [bold bright_cyan]qa-agent <command> --help[/]  for flag details.\n"
        "  Run  [bold bright_cyan]qa-agent guide <command>[/]   for a user guide.",
        markup=True,
    )
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# Interactive arrow-key selector  (shared; replaces duplicate in analyse + regression)
# ─────────────────────────────────────────────────────────────────────────────

def arrow_select(prompt: str, options: list[tuple[str, str]]) -> int:
    """Shared interactive arrow-key selector (TTY only).

    Args:
        prompt:  Header text shown above the options.
        options: List of (label, tag) tuples.  Tag is shown in brackets.

    Returns:
        Index of the chosen option.  Falls back to 0 if not a TTY.

    Appearance::

        🔧 Select source file:
          ❯  sourcefile_2025_3.csh              [qa-agent]
             env_setup.csh                      [cwd]
    """
    if not sys.stdin.isatty() or not options:
        if options:
            label, tag = options[0]
            print(f"  {green('✓')}  Auto-selected: {label}  {dim(f'[{tag}]')}")
        return 0

    selected = 0
    n = len(options)
    print(f"\n  {prompt}\n")

    def _render(sel: int) -> None:
        sys.stdout.write(f"\033[{n}A")
        for i, (label, tag) in enumerate(options):
            prefix = f"  {cyan('❯')}  " if i == sel else "     "
            tag_str = dim(f"[{tag}]")
            sys.stdout.write(
                f"\r{prefix}{bold(label) if i == sel else label}  {tag_str}\n"
            )
        sys.stdout.flush()

    # Initial render
    for i, (label, tag) in enumerate(options):
        prefix = f"  {cyan('❯')}  " if i == 0 else "     "
        tag_str = dim(f"[{tag}]")
        print(f"{prefix}{bold(label) if i == 0 else label}  {tag_str}")

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                break
            elif ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":
                    selected = (selected - 1) % n
                elif seq == "[B":
                    selected = (selected + 1) % n
                _render(selected)
            elif ch == "\x03":
                raise KeyboardInterrupt
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    print()
    return selected


def confirm(prompt: str, default: bool = True) -> bool:
    """Y/n confirmation prompt using arrow_select. Falls back to default when not a TTY."""
    if not sys.stdin.isatty():
        return default
    if default:
        ans = arrow_select(prompt, [("Yes", "default"), ("No", "")])
        return ans == 0
    else:
        ans = arrow_select(prompt, [("No", "default"), ("Yes", "")])
        return ans == 1


# ─────────────────────────────────────────────────────────────────────────────
# Markdown renderer  (summarise output)
# ─────────────────────────────────────────────────────────────────────────────

def render_markdown(text: str) -> None:
    """Render AI-generated markdown output with rich."""
    console.print(Markdown(text))


# ─────────────────────────────────────────────────────────────────────────────
# Markdown-aware line renderer  (legacy; kept for summarise streaming)
# ─────────────────────────────────────────────────────────────────────────────

def render_line(line: str) -> None:
    """Apply ANSI colour to markdown headings; pass the rest through."""
    if line.startswith("## "):
        print(f"\n{cyan(bold(line))}")
    elif line.startswith("### "):
        print(f"\n{bold(line)}")
    elif line.startswith("#### "):
        print(f"{yellow(line)}")
    else:
        print(line)


# ─────────────────────────────────────────────────────────────────────────────
# Rich progress bar helper  (analyse command)
# ─────────────────────────────────────────────────────────────────────────────

def make_progress() -> Progress:
    """Return a rich Progress bar pre-configured for debug-run batches."""
    return Progress(
        SpinnerColumn(spinner_name="dots", style=STYLE_BRAND),
        TextColumn("[progress.description]{task.description}", style="bold white"),
        BarColumn(bar_width=None, style="bright_cyan", complete_style="bold bright_cyan"),
        TextColumn("[bold white]{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Error display  (rich panel)
# ─────────────────────────────────────────────────────────────────────────────

def print_rich_error(message: str) -> None:
    """Display an error inside a red rich panel."""
    t = Text()
    t.append("✗  ", style=STYLE_ERROR)
    t.append(message.strip(), style="bold white")
    console.print()
    console.print(Panel(t, border_style="red", expand=False, padding=(0, 1)))
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# DEPRECATED legacy banner functions  (still called by some modules)
# ─────────────────────────────────────────────────────────────────────────────

def print_banner(target_label: str, provider_name: str) -> None:
    """DEPRECATED — use print_header().  Kept for backward compat."""
    print_header("summarise", f"{provider_name}  ·  {target_label}")


def print_doctor_banner() -> None:
    """DEPRECATED — use print_header().  Kept for backward compat."""
    print_header("doctor", "environment health check")


def print_regression_banner(mode: str) -> None:
    """DEPRECATED — use print_header().  Kept for backward compat."""
    print_header("regression", f"Mode: {mode}")


def print_success(msg: str = "Summary complete.") -> None:
    """Print a green success footer (legacy)."""
    print_footer(msg, success=True)


def print_error(msg: str) -> None:
    """Print a red error display (legacy — delegates to rich panel)."""
    print_rich_error(msg)


# ─────────────────────────────────────────────────────────────────────────────
# DEPRECATED Spinner class  (use console.status() instead)
# ─────────────────────────────────────────────────────────────────────────────

class Spinner:
    """DEPRECATED context manager spinner.

    Use ``with console.status("...", spinner="dots"):`` instead.

    Kept for backward compatibility — wraps ``console.status`` internally.
    """

    def __init__(self, label: str, *, stream=sys.stderr) -> None:
        self._label = label
        self._status = console.status(f"{label}...", spinner="dots")

    def __enter__(self) -> "Spinner":
        self._status.__enter__()
        return self

    def __exit__(self, *args) -> None:
        self._status.__exit__(*args)
# ─────────────────────────────────────────────────────────────────────────────
# Subprocess ESC monitor  (regression/analyse)
# ─────────────────────────────────────────────────────────────────────────────

def stream_with_esc_monitor(proc: subprocess.Popen, log_fh, print_output: bool = True) -> str:
    """Streams stdout/stderr to terminal and log, killing proc group on double ESC.
    
    Expects proc to have been created with stdout=subprocess.PIPE, start_new_session=True.
    Returns the accumulated decoded output string.
    """
    is_tty = sys.stdin.isatty()
    out_fd = proc.stdout.fileno()
    os.set_blocking(out_fd, False)
    
    if is_tty:
        in_fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(in_fd)
        tty.setcbreak(in_fd)
        os.set_blocking(in_fd, False)

    esc_count = 0
    captured_text = ""
    
    try:
        while proc.poll() is None:
            rlist = [out_fd, in_fd] if is_tty else [out_fd]
            r, _, _ = select.select(rlist, [], [], 0.05)
            
            if is_tty and in_fd in r:
                try:
                    while True:
                        chunk = os.read(in_fd, 1)
                        if not chunk:
                            break
                        if chunk == b'\x1b':
                            esc_count += 1
                            if esc_count >= 2:
                                print("\n\n  \033[1;31m✗\033[0m  Aborted: ESC pressed twice. Terminating processes...", flush=True)
                                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                                sys.exit(1)
                        else:
                            esc_count = 0
                except (BlockingIOError, OSError):
                    pass
                    
            if out_fd in r:
                try:
                    while True:
                        chunk = os.read(out_fd, 4096)
                        if not chunk:
                            break
                        text = chunk.decode("utf-8", errors="replace")
                        if print_output:
                            sys.stdout.write(text)
                            sys.stdout.flush()
                        log_fh.write(text)
                        captured_text += text
                except (BlockingIOError, OSError):
                    pass
    finally:
        if is_tty:
            os.set_blocking(in_fd, True)
            termios.tcsetattr(in_fd, termios.TCSADRAIN, old_settings)
            
    # Drain remaining
    try:
        while True:
            chunk = os.read(out_fd, 4096)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            if print_output:
                sys.stdout.write(text)
                sys.stdout.flush()
            log_fh.write(text)
            captured_text += text
    except (BlockingIOError, OSError):
        pass
        
    return captured_text


# ─────────────────────────────────────────────────────────────────────────────
# Agentic tool result preview card
#
# Flow: AI calls tool → tool executes → result shown to user → Accept/Reject
#
# Normal mode: shows only data preview (no tool name/args).
# Verbose mode: adds a tool-details header above the data preview.
# gvim mode:    writes full result to a temp file, opens in gvim,
#               then shows a minimal Accept/Reject selector.
# Auto-accept:  card is skipped entirely; prints a one-line status.
#
# Tab+Shift toggles auto_accept ON/OFF for the remainder of the session.
# ─────────────────────────────────────────────────────────────────────────────

def render_tool_result_card(
    tool_name: str,
    args: dict,
    result_content: str,
    *,
    truncated: bool = False,
    error: bool = False,
    verbose: bool = False,
    use_gvim: bool = False,
    auto_accept_state: list[bool] | None = None,
) -> tuple[bool, str | None]:
    """Show a tool result to the user and get Accept / Reject decision.

    The tool has ALREADY executed before this is called.  This function
    only handles the display and user interaction.

    Flow:
        Tool executed → collect result → call this function → user decides
        ↓
        Accept → result fed to AI in full (not just preview)
        Reject → user types a message → message sent to AI instead

    Args:
        tool_name:         Internal tool name (shown only in verbose mode).
        args:              Tool arguments dict (shown only in verbose mode).
        result_content:    Full tool result text (fed to AI on Accept).
        truncated:         True if the result was cut by the output cap.
        error:             True if the tool returned an error.
        verbose:           If True, show tool name + args above preview.
        use_gvim:          If True, open full result in gvim, then prompt.
        auto_accept_state: Mutable list[bool] wrapper for auto-accept flag.
                           Index 0 is the current state; Tab+Shift flips it.
                           Pass None to disable auto-accept toggling.

    Returns:
        (accepted, user_message):
          If accepted=True  → feed result_content to AI.
          If accepted=False → feed user_message (str) to AI, discard result.
          user_message is None when accepted=True.
    """
    _is_tty = sys.stdin.isatty() and sys.stdout.isatty()

    # ── Auto-accept fast path ─────────────────────────────────────────────────
    if auto_accept_state is not None and auto_accept_state[0]:
        lines = result_content.count("\n") + 1
        size_kb = len(result_content.encode()) / 1024
        badge = (
            f"[bold red][[ERROR]][/bold red] " if error
            else f"[bold yellow][[TRUNC]][/bold yellow] " if truncated
            else "[bold green][[OK]][/bold green] "
        )
        console.print(
            f"  [dim]→[/dim] {badge}[dim]{lines} lines · {size_kb:.1f} KB "
            f"· auto-accepted[/dim]",
        )
        return True, None

    # ── gvim mode ─────────────────────────────────────────────────────────────
    if use_gvim and _is_tty:
        import tempfile
        import subprocess
        from pathlib import Path

        tmp = Path(tempfile.gettempdir()) / f"qa_agent_result_{tool_name}.txt"
        header_lines = [
            f"# qa-agent | AI Tool Result Preview",
            f"# Tool: {tool_name}",
            f"# Args: {', '.join(f'{k}={repr(v)[:40]}' for k, v in args.items())}",
            f"# Size: {len(result_content.splitlines())} lines · "
            f"{len(result_content.encode())/1024:.1f} KB",
            f"# Status: {'ERROR' if error else 'TRUNCATED' if truncated else 'OK'}",
            f"# ─────────────────────────────────────────────────────",
            "",
        ]
        tmp.write_text("\n".join(header_lines) + result_content, encoding="utf-8")

        console.print(
            f"  [bright_cyan]⊞[/bright_cyan]  Opening data in gvim for review…"
        )
        try:
            subprocess.run(
                ["gvim", "-f", "--nofork", str(tmp)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            # Fall back to vim in terminal
            try:
                subprocess.run(["vim", str(tmp)])
            except Exception:
                console.print(
                    "  [yellow]Warning:[/yellow] gvim/vim not found; "
                    "showing preview in terminal instead."
                )
                use_gvim = False

        if use_gvim:
            # Minimal accept/reject after gvim closes
            console.print()
            try:
                choice = arrow_select(
                    "Feed this data to AI?",
                    [("Accept", "send result to AI"), ("Reject", "send a message instead")],
                )
                if choice == 0:
                    return True, None
                else:
                    try:
                        import readline  # noqa: F401 — readline improves editing
                    except ImportError:
                        pass
                    user_msg = input("  Your message to AI: ").strip()
                    return False, user_msg or "(User rejected this data, please try a different approach.)"
            except KeyboardInterrupt:
                console.print("\n  [dim]Cancelled — accepting.[/dim]")
                return True, None

    # ── Build preview text (first 15 lines) ──────────────────────────────────
    result_lines = result_content.splitlines()
    total_lines = len(result_lines)
    size_bytes = len(result_content.encode())
    size_kb = size_bytes / 1024

    _PREVIEW_LINES = 15
    preview_lines = result_lines[:_PREVIEW_LINES]
    more_count = total_lines - _PREVIEW_LINES if total_lines > _PREVIEW_LINES else 0

    # ── Status badge ──────────────────────────────────────────────────────────
    if error:
        badge_text = Text("  ✗ ERROR ", style="bold white on red")
        border_style = "red"
    elif truncated:
        badge_text = Text("  ⚠ TRUNCATED ", style="bold black on yellow")
        border_style = "yellow"
    else:
        badge_text = Text("  ✓ OK ", style="bold black on green")
        border_style = "bright_cyan"

    # ── Compose panel content ─────────────────────────────────────────────────
    panel_content = Text()

    # Verbose mode: tool details header
    if verbose:
        panel_content.append(f"Tool: ", style="dim")
        panel_content.append(f"{tool_name}", style="bold bright_cyan")
        if args:
            pairs = "  ".join(f"{k}={repr(v)[:30]}" for k, v in list(args.items())[:4])
            panel_content.append(f"\n{pairs}", style="dim")
        panel_content.append("\n" + ("─" * 54) + "\n", style="dim")

    # Preview lines
    for i, line in enumerate(preview_lines):
        # Highlight lines that look like errors/failures
        is_error_line = bool(
            __import__("re").search(
                r"(?i)(error|fatal|fail|assert|mismatch|timeout|\*\*)",
                line,
            )
        )
        style = "bold red" if is_error_line and not error else "white"
        # Truncate very long lines for display (full data still sent to AI)
        display_line = line[:110] + ("…" if len(line) > 110 else "")
        panel_content.append(f"{display_line}\n", style=style)

    # "More lines" notice
    if more_count > 0:
        panel_content.append(
            f"\n… {more_count} more line(s) — full data fed to AI on Accept\n",
            style="dim italic",
        )

    # Separator
    panel_content.append("─" * 54 + "\n", style="dim")

    # Stats row
    panel_content.append(badge_text)
    panel_content.append(
        f"  {total_lines} lines · {size_kb:.1f} KB",
        style="dim",
    )

    # ── Print card ────────────────────────────────────────────────────────────
    console.print()
    console.print(
        Panel(
            panel_content,
            title="[bold bright_cyan]Data Preview[/bold bright_cyan]",
            title_align="left",
            border_style=border_style,
            padding=(0, 1),
            expand=False,
        )
    )

    # ── Auto-accept hint ──────────────────────────────────────────────────────
    auto_on = auto_accept_state is not None and auto_accept_state[0]
    auto_label = (
        "[bold green]ON[/bold green]" if auto_on
        else "[dim]OFF[/dim]"
    )
    console.print(
        f"  [dim]Tab+Shift: Auto-Accept [{auto_label}[dim]][/dim]",
    )

    # ── Non-TTY fast-accept ───────────────────────────────────────────────────
    if not _is_tty:
        return True, None

    # ── Arrow-key selector ────────────────────────────────────────────────────
    _TAB_SHIFT_SEQ = b"\x1b[Z"  # standard "\033[Z" for Shift+Tab

    # Patch arrow_select to detect Tab+Shift; fall back gracefully if not TTY
    try:
        choice = arrow_select(
            "Feed this data to AI?",
            [
                ("Accept", "send result to AI"),
                ("Reject", "send a message instead"),
            ],
            tab_shift_callback=(
                lambda: auto_accept_state.__setitem__(0, not auto_accept_state[0])
                if auto_accept_state is not None
                else None
            ),
        )
    except TypeError:
        # arrow_select may not accept tab_shift_callback; call without it
        choice = arrow_select(
            "Feed this data to AI?",
            [
                ("Accept", "send result to AI"),
                ("Reject", "send a message instead"),
            ],
        )
    except KeyboardInterrupt:
        console.print("\n  [dim]Cancelled — accepting.[/dim]")
        return True, None

    if choice == 0:
        return True, None

    # Reject — collect user message
    console.print()
    try:
        import readline  # noqa: F401
    except ImportError:
        pass
    try:
        user_msg = input("  [>] Your message to AI: ").strip()
    except (EOFError, KeyboardInterrupt):
        user_msg = ""

    return False, user_msg or "(User rejected this data. Please try a different approach or different tool arguments.)"


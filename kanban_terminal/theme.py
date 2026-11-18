"""Light or dark, like the editor around the board.

In order: the terminal's real background colour (asked with OSC 11 before
the app starts — VS Code's terminal answers it), then VS Code's settings
(its colour theme, or the OS appearance when « window.autoDetectColorScheme »
is on), then the OS appearance (macOS)."""
from __future__ import annotations

import json
import os
import re
import select
import subprocess
import sys
import time

LIGHT, DARK = "light", "dark"


def parse_osc11(reply: str) -> str | None:
    """« ESC]11;rgb:ffff/ffff/ffff BEL » → light / dark (by luminance)."""
    m = re.search(r"rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)", reply)
    if not m:
        return None
    r, g, b = (int(x, 16) / (16 ** len(x) - 1) for x in m.groups())
    return LIGHT if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5 else DARK


def terminal_background(timeout: float = 0.3) -> str | None:
    """Ask the terminal its background colour; None if it doesn't answer."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    try:
        import termios
        import tty
    except ImportError:
        return None
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    reply = ""
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\033]11;?\033\\")
        sys.stdout.flush()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            r, _, _ = select.select([fd], [], [], max(0.0, end - time.monotonic()))
            if not r:
                break
            reply += os.read(fd, 64).decode("latin-1", "replace")
            if reply.endswith(("\007", "\033\\")):
                break
    except OSError:
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return parse_osc11(reply)


def os_appearance() -> str | None:
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                 capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            return None
        return DARK if "Dark" in out.stdout else LIGHT
    return None


def vscode_settings_path() -> str:
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", "")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "Code", "User", "settings.json")


def _jsonc(text: str) -> dict:
    """settings.json allows // comments and trailing commas."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True; out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(c)
        i += 1
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)) or "{}")


def theme_kind(name: str) -> str:
    """« Light Modern », « Solarized Light », « Default High Contrast Light » → light."""
    return LIGHT if re.search(r"light|day|latte|dawn", name, re.I) else DARK


def vscode_theme(settings: dict, os_mode: str | None) -> str:
    if settings.get("window.autoDetectColorScheme") and os_mode:
        key = "workbench.preferredLightColorTheme" if os_mode == LIGHT else "workbench.preferredDarkColorTheme"
        return theme_kind(settings.get(key, "Light" if os_mode == LIGHT else "Dark"))
    return theme_kind(settings.get("workbench.colorTheme", "Default Dark Modern"))


def vscode_settings() -> dict | None:
    if os.environ.get("TERM_PROGRAM") != "vscode":
        return None
    try:
        with open(vscode_settings_path(), encoding="utf-8") as f:
            return _jsonc(f.read())
    except (OSError, ValueError):
        return None


def transparent_terminal(settings: dict) -> bool:
    """« terminal.background »: "#00000000" (alpha 00) in colorCustomizations,
    globally or for the current theme: the terminal shows the editor behind it,
    but answers OSC 11 with the colour without its alpha — black."""
    custom = settings.get("workbench.colorCustomizations") or {}
    scoped = custom.get(f"[{settings.get('workbench.colorTheme', '')}]") or {}
    bg = str(scoped.get("terminal.background") or custom.get("terminal.background") or "")
    return bool(re.fullmatch(r"#(?:[0-9a-fA-F]{3}0|[0-9a-fA-F]{6}00)", bg))


def detect() -> str:
    """Light or dark at start: the terminal's background, unless VS Code's
    terminal is transparent (then its theme), then the settings, then dark."""
    settings = vscode_settings()
    if not (settings and transparent_terminal(settings)):
        bg = terminal_background()
        if bg:
            return bg
    return from_settings() or DARK


def from_settings() -> str | None:
    """VS Code's theme when running in its terminal, else the OS appearance."""
    os_mode = os_appearance()
    if os.environ.get("TERM_PROGRAM") == "vscode":
        try:
            with open(vscode_settings_path(), encoding="utf-8") as f:
                return vscode_theme(_jsonc(f.read()), os_mode)
        except (OSError, ValueError):
            pass
    return os_mode

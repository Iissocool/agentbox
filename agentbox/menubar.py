"""macOS Notch App launcher — build, configure, and open AgentboxMenuBar.app."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

console = Console()

MENUBAR_DIR = Path(__file__).resolve().parent.parent / "ui" / "macbar"
APP_NAME = "AgentboxMenuBar"
APP_BUNDLE = MENUBAR_DIR / "dist" / f"{APP_NAME}.app"
CONFIG_PATH = Path.home() / ".agentbox" / "menubar.json"
DEFAULT_PORT = 18733


def _write_launcher_config(port: int = DEFAULT_PORT) -> Path:
    """Persist python path so the notch app can spawn the gateway."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "python": sys.executable,
        "port": port,
        "module": "agentbox.ui_gateway",
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return CONFIG_PATH


def build_app() -> Path:
    """Build AgentboxMenuBar.app via ui/macbar/build.sh."""
    script = MENUBAR_DIR / "build.sh"
    if not script.exists():
        raise FileNotFoundError(f"Build script not found: {script}")

    console.print("[dim]Building macOS notch app...[/dim]")
    result = subprocess.run(
        ["bash", str(script)],
        cwd=str(MENUBAR_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(result.stdout)
        console.print(result.stderr)
        raise RuntimeError("Notch app build failed")

    if result.stdout.strip():
        console.print(result.stdout.strip())

    if not APP_BUNDLE.exists():
        raise FileNotFoundError(f"App bundle not found after build: {APP_BUNDLE}")

    return APP_BUNDLE


def launch_menubar(*, rebuild: bool = False, port: int = DEFAULT_PORT) -> None:
    """Build (if needed) and open the macOS notch application."""
    if sys.platform != "darwin":
        console.print("[red]Notch app is only available on macOS.[/red]")
        raise SystemExit(1)

    if shutil.which("swiftc") is None:
        console.print(
            "[red]swiftc not found.[/red] Install Xcode Command Line Tools:\n"
            "  xcode-select --install"
        )
        raise SystemExit(1)

    _write_launcher_config(port)

    app_path = APP_BUNDLE
    if rebuild or not app_path.exists():
        app_path = build_app()

    console.print(
        Panel(
            f"[green]Launching {APP_NAME}[/green]\n\n"
            f"App: [cyan]{app_path}[/cyan]\n"
            f"Config: [cyan]{CONFIG_PATH}[/cyan]\n\n"
            "The notch overlay appears at the top center of your screen.\n"
            "The gateway starts automatically — no need to run [bold]ag gateway[/bold].",
            title="🍎 Agentbox Notch",
            border_style="blue",
        )
    )

    subprocess.Popen(["open", "-a", str(app_path)])

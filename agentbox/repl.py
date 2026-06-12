"""Agentbox REPL — Sovereign Terminal Theme.

Inspired by JPMorgan Chase & Bloomberg Terminal design language:
Deep navy, burnished gold, silver accents, authoritative typography.
"""

from __future__ import annotations

import os
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import Condition
from prompt_toolkit.styles import Style as PtStyle
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.box import ROUNDED
from rich.text import Text
from rich.align import Align

from . import __version__

console = Console()

# ═══════════════════════════════════════════════════════════════
#  SOVEREIGN PALETTE — Deep Navy · Burnished Gold · Silver
# ═══════════════════════════════════════════════════════════════
NAVY       = "#0A1628"   # Abyssal navy (primary bg)
NAVY_MID   = "#122035"   # Mid navy (panels, menus)
NAVY_LIGHT = "#1B3A5C"   # Light navy (borders, lines)
ROYAL      = "#2E5B8A"   # Royal blue (active borders)
ELECTRIC   = "#4A90D9"   # Electric blue (links, hover)
GOLD       = "#C5A572"   # Burnished gold (primary accent)
GOLD_LIGHT = "#E8D5B5"   # Light gold (secondary accent)
GOLD_DIM   = "#8B7355"   # Dim gold (subtle accents)
SILVER     = "#A8B2C1"   # Silver (dim text)
PEARL      = "#D0D5DD"   # Pearl (normal text)
WHITE      = "#E8ECF1"   # Off-white (bright text)
VOID       = "#060D18"   # Void black (deepest bg)
ALERT_R    = "#E25C5C"   # Alert red
ALERT_A    = "#E8A838"   # Alert amber

# ── Slash commands ──
_CMDS = [
    ("/claude",   "启动 Claude Code 沙盒",        "Agent",  ""),
    ("/codex",    "启动 OpenAI Codex 沙盒",       "Agent",  ""),
    ("/aider",    "启动 Aider 沙盒",              "Agent",  ""),
    ("/goose",    "启动 Goose 沙盒",              "Agent",  ""),
    ("/opencode", "启动 OpenCode 沙盒",           "Agent",  ""),
    ("/run",      "运行任意 Agent",                "Agent",  "<agent>"),
    ("/compose",  "多 Agent 角色组合协作",         "Multi",  "a:role b:role"),
    ("/team",     "运行预定义团队",                "Multi",  "<team_id>"),
    ("/compare",  "多个 Agent 并排对比",          "Multi",  "claude codex"),
    ("/ask",      "快捷提问，一键启动 Agent",      "Chat",   "\"问题\""),
    ("/status",   "查看会话和沙盒状态",            "Manage", ""),
    ("/attach",   "重连到 tmux 会话",             "Manage", ""),
    ("/kill",     "停止会话和沙盒",                "Manage", ""),
    ("/logs",     "查看沙盒日志",                  "Manage", ""),
    ("/diff",     "查看 Git 改动摘要",            "Flow",   ""),
    ("/merge",    "暂存并提交所有改动",           "Flow",   "-m \"msg\""),
    ("/review",   "审查改动+测试+合并/丢弃",      "Flow",   ""),
    ("/test",     "运行项目测试",                  "Flow",   ""),
    ("/pipeline", "多步流水线编排",                "Pipe",   "dev \"任务\""),
    ("/list",     "列出可用 Agent 和团队",        "Config", ""),
    ("/config",   "查看/编辑配置",                 "Config", "show|edit"),
    ("/shell",    "打开容器 Shell",               "Shell",  "<agent>"),
    ("/help",     "显示帮助信息",                  "",       ""),
    ("/exit",     "退出 Agentbox",                "",       ""),
]


class _Completer(Completer):
    def get_completions(self, document, _event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for cmd, desc, cat, usage in _CMDS:
            if cmd.lower().startswith(text.lower()):
                display = f"{cmd} {usage}".strip() if usage else cmd
                meta = f"{cat}  ·  {desc}" if cat else desc
                yield Completion(cmd, start_position=-len(text),
                                 display=display, display_meta=meta)


def _key_bindings() -> KeyBindings:
    kb = KeyBindings()

    @kb.add("enter", filter=Condition(lambda: bool(
        _get_app().current_buffer.complete_state)))
    def _accept(event):
        cs = event.current_buffer.complete_state
        if cs and cs.current_completion:
            event.current_buffer.apply_completion(cs.current_completion)

    return kb


def _get_app():
    from prompt_toolkit.application import get_app
    return get_app()


# ═══════════════════════════════════════════════════════════════
#  SPLASH — Command Center Entry
# ═══════════════════════════════════════════════════════════════
_BANNER = r"""
       _                 _           _
      / \   __ _ ___ ___| |__   __ _(_)_ __
     / _ \ / _` / __/ __| '_ \ / _` | | '_ \
    / ___ \ (_| \__ \__ \ |_) | (_| | | | | |
   /_/   \_\__,_|___/___/_.__/ \__,_|_|_| |_|
"""


def _splash() -> None:
    console.print()
    console.print(f"  [bold {GOLD}]{_BANNER}[/]")
    console.print(f"  [{GOLD}]◈[/]  [bold {GOLD_LIGHT}]AGENTBOX[/] [{SILVER}]v{__version__}[/]  [{GOLD_DIM}]──[/]  [{PEARL}]AI Agent Orchestration Sandbox[/]")
    console.print()


# ═══════════════════════════════════════════════════════════════
#  HELP — Sovereign Command Reference
# ═══════════════════════════════════════════════════════════════
def _help() -> None:
    console.print()

    # ── Title panel in gold ──
    title = Panel(
        Align(Text("◈  C O M M A N D S", style=f"bold {GOLD}"), align="center"),
        border_style=GOLD_DIM,
        padding=(0, 4),
    )
    console.print(title)

    # ── Command table ──
    table = Table(
        show_header=True,
        header_style=f"bold {GOLD}",
        box=ROUNDED,
        border_style=NAVY_LIGHT,
        padding=(0, 2),
        show_lines=False,
    )
    table.add_column("Command", style=f"bold {GOLD_LIGHT}", min_width=24, no_wrap=True)
    table.add_column("Description", style=PEARL, min_width=28, no_wrap=True)
    table.add_column("Category", style=f"{SILVER}", min_width=8, no_wrap=True)

    for cmd, desc, cat, usage in _CMDS:
        c = f"{cmd} {usage}".strip() if usage else cmd
        table.add_row(c, desc, cat or "—")

    console.print(table)
    console.print()


# ═══════════════════════════════════════════════════════════════
#  COMMAND DISPATCH
# ═══════════════════════════════════════════════════════════════
def _exec(ctx: Any, raw: str) -> bool:
    parts = raw.strip().split()
    if not parts:
        return True
    cmd, args = parts[0].lower(), parts[1:]
    name = cmd.lstrip("/")

    from .cli import _interactive_agent_select, _parse_agent_role
    from .agents import AgentRunner

    config = ctx.obj["config"]
    project = ctx.obj["project_path"]
    runner = AgentRunner(config)
    simple = {"claude", "codex", "aider", "goose", "opencode"}

    try:
        if name in simple and not args:
            runner.run_agent(name, project)
        elif name == "run":
            aid = args[0] if args else _interactive_agent_select(config)
            if aid:
                runner.run_agent(aid, project, prompt=" ".join(args[1:]) or None)
        elif name in simple and args:
            runner.run_agent(name, project, prompt=" ".join(args))
        elif name == "ask":
            q = " ".join(args) or input("  > ").strip()
            from .workflow import WorkflowEngine
            WorkflowEngine(config).ask(prompt=q, agent_id="claude", project_path=project)
        elif name == "compose":
            if not args:
                args = input("  > ").strip().split()
            runner.run_compose([_parse_agent_role(s) for s in args], project)
        elif name == "team":
            runner.run_team(args[0] if args else "dev-team", project)
        elif name == "compare":
            runner.run_compare(args or ["claude", "codex"], project)
        elif name == "shell":
            runner.run_shell(args[0] if args else "claude", project)
        elif name == "pipeline":
            from .orchestrator import Orchestrator
            from .orchestrator.pipeline import dev_pipeline, research_pipeline, compare_pipeline
            pt = args[0] if args else "dev"
            task = " ".join(args[1:]) or input("  > ").strip()
            orch = Orchestrator(config)
            pipe = {"dev": dev_pipeline, "research": research_pipeline,
                    "compare": compare_pipeline}.get(pt, dev_pipeline)
            orch.execute(pipe(task), project)
        elif name in ("status", "attach", "kill", "logs", "history",
                       "diff", "merge", "review", "test", "list", "config", "init"):
            from . import cli
            fn = {"status": cli.status, "attach": cli.attach, "kill": cli.kill,
                  "logs": cli.logs, "history": cli.history, "diff": cli.diff_cmd,
                  "merge": cli.merge, "review": cli.review, "test": cli.test_cmd,
                  "list": cli.list, "config": cli.config_show, "init": cli.init}[name]
            if name == "merge":
                ctx.invoke(fn, message=" ".join(args) or "Update project")
            else:
                ctx.invoke(fn)
        elif name == "help":
            _help()
        elif name in ("exit", "quit", "q"):
            console.print(f"\n  [{GOLD_DIM}]◈ Session closed.[/]\n")
            return False
        else:
            console.print(f"\n  [{ALERT_R}]✘[/]  Unknown command: [bold]{cmd}[/]  [{SILVER}]Type / for commands[/]\n")
    except Exception as e:
        console.print(f"\n  [{ALERT_A}]⚠[/] {e}")
        console.print(f"  [{SILVER}]Type /help for commands[/]\n")

    return True


# ═══════════════════════════════════════════════════════════════
#  PROMPT_TOOLKIT STYLE — Sovereign Terminal
# ═══════════════════════════════════════════════════════════════
_style = PtStyle.from_dict({
    # Completion menu — warm gold sovereign theme
    "completion-menu":                          f"bg:#14100a {GOLD_LIGHT}",
    "completion-menu.completion":               f"bg:#14100a {GOLD_LIGHT}",
    "completion-menu.completion.current":       f"bg:#2a1f10 {WHITE} bold",
    "completion-menu.meta":                     f"bg:#14100a {GOLD_DIM}",
    "completion-menu.completion.current meta":  f"bg:#2a1f10 {GOLD}",
    # Scrollbar
    "scrollbar":                                f"bg:#0d1520",
    "scrollbar.button":                         f"bg:{GOLD}",
    # Auto-suggestion
    "auto-suggestion":                          f"{GOLD_DIM}",
    # Bottom toolbar — premium gold on transparent
    "bottom-toolbar":                           f"bold {GOLD}",
})


# ═══════════════════════════════════════════════════════════════
#  MAIN REPL LOOP
# ═══════════════════════════════════════════════════════════════
def run_repl(ctx: Any) -> None:
    _splash()

    session = PromptSession(
        history=InMemoryHistory(),
        completer=_Completer(),
        auto_suggest=AutoSuggestFromHistory(),
        complete_while_typing=True,
        key_bindings=_key_bindings(),
    )

    project = os.path.basename(ctx.obj["project_path"])

    def _prompt():
        return FormattedText([
            (f"bold {GOLD}", "◈ "),
            (f"{GOLD_LIGHT}", project),
            (f"bold {GOLD}", " › "),
        ])

    def _toolbar():
        # Single gold — clear section breaks with wide spacing
        G = f"bold {GOLD}"
        return FormattedText([
            (G, "  ◈  /命令  ↑↓选择  ↵执行  /help        claude启动  提问即执行        ⌃C取消  /exit退出  "),
        ])

    while True:
        try:
            user_input = session.prompt(_prompt, bottom_toolbar=_toolbar, style=_style)
            if not user_input or not user_input.strip():
                continue
            user_input = user_input.strip()

            if user_input.startswith("/"):
                if not _exec(ctx, user_input):
                    break
            else:
                from .agents import AgentRunner
                config = ctx.obj["config"]
                runner = AgentRunner(config)
                first = user_input.split()[0].lower()
                if first in config.get("agents", {}):
                    rest = user_input[len(first):].strip()
                    runner.run_agent(first, ctx.obj["project_path"], prompt=rest or None)
                else:
                    from .workflow import WorkflowEngine
                    WorkflowEngine(config).ask(
                        prompt=user_input, agent_id="claude",
                        project_path=ctx.obj["project_path"])

        except KeyboardInterrupt:
            console.print()
        except EOFError:
            console.print(f"\n  [{GOLD_DIM}]◈ Session closed.[/]\n")
            break
        except Exception as e:
            console.print(f"\n  [{ALERT_A}]⚠[/] {e}")
            console.print(f"  [{SILVER}]REPL recovered.[/]\n")
            try:
                import subprocess
                subprocess.run(["stty", "sane"], check=False)
            except Exception:
                pass
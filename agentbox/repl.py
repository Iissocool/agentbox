"""Agentbox REPL — Minimal & Premium."""

from __future__ import annotations

import os
import time
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
from rich.text import Text

from . import __version__

console = Console()

# ── Minimal palette ──
MUTED = "#6B7280"    # Gray
ACCENT = "#D4AF37"   # Subtle gold
DIM = "#4B5563"      # Dark gray

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
    ("/ask",      "快捷提问",                     "Chat",   "\"问题\""),
    ("/status",   "查看会话和沙盒状态",            "Manage", ""),
    ("/attach",   "重连到 tmux 会话",             "Manage", ""),
    ("/kill",     "停止会话和沙盒",                "Manage", ""),
    ("/logs",     "查看沙盒日志",                  "Manage", ""),
    ("/diff",     "查看 Git 改动",                "Flow",   ""),
    ("/merge",    "暂存并提交改动",               "Flow",   "-m \"msg\""),
    ("/review",   "审查+测试+合并/丢弃",          "Flow",   ""),
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
                display = f"{cmd} {usage}".strip()
                meta = f"{cat}  {desc}" if cat else desc
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


# ── Splash ──
def _splash() -> None:
    console.print()
    console.print(f"  [bold]agentbox[/bold] [dim]{__version__}[/dim]")
    console.print(f"  [dim]AI Agent Orchestration Sandbox[/dim]")
    console.print()
    console.print(f"  [dim]Type [bold]/[/bold] for commands · [bold]/exit[/bold] to quit[/dim]")
    console.print()


# ── Help ──
def _help() -> None:
    console.print()
    console.print(f"  [bold]Commands[/bold]")
    console.print(f"  [dim]{'─' * 42}[/dim]")

    cats: dict[str, list] = {}
    for cmd, desc, cat, usage in _CMDS:
        cats.setdefault(cat or "Other", []).append((cmd, desc, usage))

    for cat, cmds in cats.items():
        console.print(f"  [dim]{cat}[/dim]")
        for cmd, desc, usage in cmds:
            c = f"[bold]{cmd}[/bold]" + (f" [dim]{usage}[/dim]" if usage else "")
            console.print(f"    {c:<24} [dim]{desc}[/dim]")
    console.print()


# ── Command dispatch ──
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
            console.print(f"  [dim]Bye.[/dim]")
            return False
        else:
            console.print(f"  [dim]Unknown: {cmd} · Type [bold]/[/bold] for commands[/dim]")
    except Exception as e:
        console.print(f"  [dim]Error: {e}[/dim]")

    return True


# ── prompt_toolkit style ──
_style = PtStyle.from_dict({
    "completion-menu": "bg:#1a1a2e #e0e0e0",
    "completion-menu.completion": "bg:#1a1a2e #e0e0e0",
    "completion-menu.completion.current": "bg:#2a2a4a #ffffff bold",
    "completion-menu.meta": "bg:#1a1a2e #888888",
    "completion-menu.completion.current meta": "bg:#2a2a4a #aaaaaa",
})


# ── Main REPL ──
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
            (f"{ACCENT} bold", "›"),
            ("", " "),
        ])

    while True:
        try:
            user_input = session.prompt(_prompt, style=_style)
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
            console.print(f"  [dim]Bye.[/dim]")
            break
        except Exception as e:
            console.print(f"  [dim]Error: {e}[/dim]")
            try:
                import subprocess
                subprocess.run(["stty", "sane"], check=False)
            except Exception:
                pass
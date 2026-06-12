"""Agentbox REPL — Art Deco Morgan-style with rotating Rubik's cube."""

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
from rich.panel import Panel

from . import __version__

console = Console()

# ── Art Deco palette ──
G = "#D4AF37"      # Gold
DG = "#B8860B"     # Dark gold
PG = "#F5E6CC"     # Pale gold
NV = "#0D1B2A"     # Navy
DN = "#1B2838"     # Dark navy
CR = "#FAF0E6"     # Cream
DR = "#8B0000"     # Deep red

# ── Rotating Rubik's cube — 6 emoji frames ──
_CUBE = ["🔵🟥🟢", "🟥🟡🔵", "🟡⚪🟥", "⚪🟠🟡", "🟠🟢⚪", "🟢🔵🟠"]


def _cube() -> str:
    """Current rotating cube frame."""
    return _CUBE[int(time.time() * 2.5) % 6]


# ── Slash commands ──
_CMDS = [
    ("/claude",   "启动 Claude Code 沙盒",        "🤖 Agent",  ""),
    ("/codex",    "启动 OpenAI Codex 沙盒",       "🤖 Agent",  ""),
    ("/aider",    "启动 Aider 沙盒",              "🤖 Agent",  ""),
    ("/goose",    "启动 Goose 沙盒",              "🤖 Agent",  ""),
    ("/opencode", "启动 OpenCode 沙盒",           "🤖 Agent",  ""),
    ("/run",      "运行任意 Agent",                "🤖 Agent",  "<agent>"),
    ("/compose",  "多 Agent 角色组合协作",         "👥 多Agent", "a:role b:role"),
    ("/team",     "运行预定义团队",                "👥 多Agent", "<team_id>"),
    ("/compare",  "多个 Agent 并排对比",          "👥 多Agent", "claude codex"),
    ("/ask",      "快捷提问，一键启动 Agent",      "💬 对话",   "\"问题\""),
    ("/status",   "查看会话和沙盒状态",            "📊 管理",   ""),
    ("/attach",   "重连到 tmux 会话",             "📊 管理",   ""),
    ("/kill",     "停止会话和沙盒",                "📊 管理",   ""),
    ("/logs",     "查看沙盒日志",                  "📊 管理",   ""),
    ("/diff",     "查看 Git 改动摘要",            "🔧 工作流", ""),
    ("/merge",    "暂存并提交所有改动",           "🔧 工作流", "-m \"msg\""),
    ("/review",   "审查改动+测试+合并/丢弃",      "🔧 工作流", ""),
    ("/test",     "运行项目测试",                  "🔧 工作流", ""),
    ("/pipeline", "多步流水线编排",                "🧠 流水线", "dev \"任务\""),
    ("/list",     "列出可用 Agent 和团队",        "⚙️ 配置",   ""),
    ("/config",   "查看/编辑配置",                 "⚙️ 配置",   "show|edit"),
    ("/shell",    "打开容器 Shell",               "🐚 Shell",  "<agent>"),
    ("/help",     "显示帮助信息",                  "❓ 其他",   ""),
    ("/exit",     "退出 Agentbox",                "❓ 其他",   ""),
]


class _Completer(Completer):
    def get_completions(self, document, _event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for cmd, desc, cat, usage in _CMDS:
            if cmd.startswith(text.lower()) or cmd.lower().startswith(text.lower()):
                display = f"{cmd} {usage}".strip()
                yield Completion(cmd, start_position=-len(text),
                                 display=display, display_meta=f"{cat}  {desc}")


# ── Key bindings ──
def _key_bindings() -> KeyBindings:
    kb = KeyBindings()

    @kb.add("enter", filter=Condition(lambda: bool(
        __get_app().current_buffer.complete_state)))
    def _accept(event):
        cs = event.current_buffer.complete_state
        if cs and cs.current_completion:
            event.current_buffer.apply_completion(cs.current_completion)

    return kb


def __get_app():
    from prompt_toolkit.application import get_app
    return get_app()


# ── Splash ──
def _splash() -> None:
    console.print()
    console.print(f"  [{G}]     ╔═══════════════════════════════════╗[/]")
    console.print(f"  [{G}]   ╔═╩═══════════════════════════════╩═╗[/]")
    console.print(f"  [{G}]   ║[/]   [{DG}]◈[/]  [bold {G}]A G E N T B O X[/]  [{DG}]◈[/]   [{G}]║[/]")
    console.print(f"  [{G}]   ║[/]   [{DG}]━━━━━━━━━━━━━━━━━━━━━[/]   [{G}]║[/]")
    console.print(f"  [{G}]   ║[/]   [{CR} italic]AI Agent Orchestration Sandbox[/]   [{G}]║[/]")
    console.print(f"  [{G}]   ║[/]   [{PG} dim]v{__version__}[/]                      [{G}]║[/]")
    console.print(f"  [{G}]   ╚═════════════════════════════════╝[/]")
    console.print(f"  [{G}]     ╚═══════════════════════════════╝[/]")
    console.print()
    console.print(f"  [{CR}]◈[/]  [bold {G}]/[/] 命令  [{DG}]·[/]  [bold {G}]↑↓[/] 选择  [{DG}]·[/]  [bold {G}]↵[/] 执行  [{DG}]·[/]  [bold {G}]/exit[/] 退出")
    console.print()


# ── Help ──
def _help() -> None:
    console.print()
    console.print(Panel(
        f"[bold {G}]◈  Agentbox 命令列表  ◈[/]\n"
        f"[{CR} dim]输入 / 触发补全 · ↑↓ 选择 · ↵ 执行[/]",
        border_style=DG, padding=(0, 2)))

    cats: dict[str, list] = {}
    for cmd, desc, cat, usage in _CMDS:
        cats.setdefault(cat, []).append((cmd, desc, usage))

    for cat, cmds in cats.items():
        console.print(f"\n  [bold {G}]{cat}[/]")
        console.print(f"  [{DG}]{'─' * 40}[/]")
        for cmd, desc, usage in cmds:
            c = f"[{G}]{cmd}[/]" + (f" [{CR} dim]{usage}[/]" if usage else "")
            console.print(f"  {c:<28} [{PG}]{desc}[/]")
    console.print()


# ── Command dispatch ──
def _exec(ctx: Any, raw: str) -> bool:
    """Execute a slash command. Returns False if should quit."""
    parts = raw.strip().split()
    if not parts:
        return True
    cmd, args = parts[0].lower(), parts[1:]
    name = cmd.lstrip("/")

    from .cli import _interactive_agent_select, _parse_agent_role
    from .config import list_teams
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
            q = " ".join(args) or input("  问题: ").strip()
            from .workflow import WorkflowEngine
            WorkflowEngine(config).ask(prompt=q, agent_id="claude", project_path=project)
        elif name == "compose":
            if not args:
                args = input("  组合 (如 claude:coder codex:reviewer): ").strip().split()
            runner.run_compose([_parse_agent_role(s) for s in args], project)
        elif name == "team":
            tid = args[0] if args else "dev-team"
            runner.run_team(tid, project)
        elif name == "compare":
            runner.run_compare(args or ["claude", "codex"], project)
        elif name == "shell":
            runner.run_shell(args[0] if args else "claude", project)
        elif name == "pipeline":
            from .orchestrator import Orchestrator
            from .orchestrator.pipeline import dev_pipeline, research_pipeline, compare_pipeline
            pt = args[0] if args else "dev"
            task = " ".join(args[1:]) or input("  任务: ").strip()
            orch = Orchestrator(config)
            pipe = {"dev": dev_pipeline, "research": research_pipeline, "compare": compare_pipeline}.get(pt, dev_pipeline)
            orch.execute(pipe(task), project)
        elif name in ("status", "attach", "kill", "logs", "history", "diff", "merge", "review", "test", "list", "config", "init"):
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
            console.print(f"\n  [{CR} dim]👋 再见！[/]")
            return False
        else:
            console.print(f"\n  [{DR}]✘ 未知命令:[/] {cmd}  [{CR} dim]输入 / 查看命令[/]\n")
    except Exception as e:
        console.print(f"\n  [{DR}]⚠[/] {e}")
        console.print(f"  [{CR} dim]输入 /help 查看命令[/]\n")

    return True


# ── prompt_toolkit style ──
_style = PtStyle.from_dict({
    "bottom-toolbar": f"bg:{NV} {CR}",
    "completion-menu": f"bg:{DN} {CR}",
    "completion-menu.completion": f"bg:{DN} {CR}",
    "completion-menu.completion.current": f"bg:{G} #000000 bold",
    "completion-menu.meta": f"bg:{NV} #888888",
    "completion-menu.completion.current meta": f"bg:{G} #1a1a1a",
})


# ── Main REPL ──
def run_repl(ctx: Any) -> None:
    """Run the interactive Agentbox REPL."""
    _splash()

    session = PromptSession(
        history=InMemoryHistory(),
        completer=_Completer(),
        auto_suggest=AutoSuggestFromHistory(),
        complete_while_typing=True,
        key_bindings=_key_bindings(),
        refresh_interval=0.4,
    )

    project = os.path.basename(ctx.obj["project_path"])

    def _prompt():
        return FormattedText([
            (f"bold {G}", "◈ "),
            ("", _cube() + " "),
            (f"{DG}", f"{project}"),
            (f"bold {G}", " › "),
        ])

    def _toolbar():
        return FormattedText([
            (f"bg:{NV} {PG}", f"  ◈ {_cube()}  "),
            (f"bg:{NV} {CR}", "输入 "),
            (f"bg:{NV} bold {G}", "/"),
            (f"bg:{NV} {CR}", " 命令  ·  "),
            (f"bg:{NV} bold {G}", "↵"),
            (f"bg:{NV} {CR}", " 执行  ·  "),
            (f"bg:{NV} bold {G}", "/exit"),
            (f"bg:{NV} {CR}", " 退出  "),
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
            console.print(f"\n  [{CR} dim]Ctrl+D 或 /exit 退出[/]")
        except EOFError:
            console.print(f"\n  [{CR} dim]👋 再见！[/]\n")
            break
        except Exception as e:
            console.print(f"\n  [{DR}]⚠[/] {e}")
            console.print(f"  [{CR} dim]REPL 已恢复[/]\n")
            try:
                import subprocess
                subprocess.run(["stty", "sane"], check=False)
            except Exception:
                pass
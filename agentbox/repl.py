"""Agentbox REPL — Frosted glass tech style with box input."""

from __future__ import annotations

import os
import shutil
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

from . import __version__

console = Console()

# ── Frosted glass palette ──
AC = "#5EEAD4"      # Soft teal accent
AB = "#7DD3FC"      # Sky blue
AD = "#94A3B8"      # Slate gray (dim text)
AM = "#64748B"      # Muted slate
ABG = "#0d1117"     # Near-black (toolbar bg)
AW = "#CBD5E1"      # Light text
AH = "#38BDF8"      # Highlight blue

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
_BANNER = r"""
       _                 _           _
      / \   __ _ ___ ___| |__   __ _(_)_ __
     / _ \ / _` / __/ __| '_ \ / _` | | '_ \
    / ___ \ (_| \__ \__ \ |_) | (_| | | | | |
   /_/   \_\__,_|___/___/_.__/ \__,_|_|_| |_|
"""


def _splash() -> None:
    console.print()
    console.print(f"  [bold {AC}]{_BANNER}[/]")
    console.print(f"  [{AC}]◇[/]  [bold {AC}]Agentbox[/] [{AM}]v{__version__}[/]")
    console.print(f"  [{AM}]│[/]  [{AD}]AI Agent Orchestration Sandbox[/]")
    console.print()
    console.print(f"  [{AM}]├─[/]  [{AD}]输入 [bold {AC}]/[/] 查看命令  [{AM}]·[/]  [bold {AC}]↑↓[/] 选择  [{AM}]·[/]  [bold {AC}]↵[/] 补全/执行[/]")
    console.print(f"  [{AM}]├─[/]  [{AD}]输入 [bold {AC}]claude[/] 启动 Agent  [{AM}]·[/]  直接提问自动执行[/]")
    console.print(f"  [{AM}]╰─[/]  [{AD}][bold {AC}]Ctrl+C[/] 取消  [{AM}]·[/]  [bold {AC}]Ctrl+D[/] 或 [bold {AC}]/exit[/] 退出[/]")
    console.print()


# ── Help ──
def _help() -> None:
    console.print()
    table = Table(
        show_header=False,
        box=ROUNDED,
        border_style=AM,
        padding=(0, 1),
    )
    table.add_column("cmd", style=f"bold {AC}", min_width=24, no_wrap=True)
    table.add_column("desc", style=AW, min_width=24, no_wrap=True)
    table.add_column("cat", style=AM, min_width=8, no_wrap=True)

    for cmd, desc, cat, usage in _CMDS:
        c = f"{cmd} {usage}".strip() if usage else cmd
        table.add_row(c, desc, cat or "Other")

    console.print(Panel(
        f"[bold {AC}]Commands[/]",
        border_style=AM, padding=(0, 2)))
    console.print(table)
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
            console.print(f"\n  [{AM}]Bye.[/]")
            return False
        else:
            console.print(f"\n  [{AH}]✘[/] 未知命令: {cmd}  [{AD}]输入 / 查看命令[/]\n")
    except Exception as e:
        console.print(f"\n  [{AH}]⚠[/] {e}")
        console.print(f"  [{AD}]输入 /help 查看命令[/]\n")

    return True


# ── prompt_toolkit style — rounded table look ──
_style = PtStyle.from_dict({
    "bottom-toolbar": f"bg:{ABG} {AD}",
    "completion-menu": f"bg:#0d1117 {AW}",
    "completion-menu.completion": f"bg:#0d1117 {AW}",
    "completion-menu.completion.current": f"bg:#1a3a4a #ffffff bold",
    "completion-menu.meta": f"bg:#0d1117 {AM}",
    "completion-menu.completion.current meta": f"bg:#1a3a4a {AC}",
    "scrollbar": f"bg:#1a2744",
    "scrollbar.button": f"bg:{AC}",
    "auto-suggestion": f"{AM}",
})


# ── Box prompt helpers ──
def _make_top_border(project: str) -> str:
    """Full-width top border: ╭─ ◈ project ────╮"""
    w = shutil.get_terminal_size().columns
    header = f"╭─ ◈ {project} "
    # visual_len: count actual display columns
    # ╭ = 1, ─ = 1 each, ◈ = 2 (wide char), spaces = 1 each
    vis_len = 1 + 1 + 1 + 1 + 2 + 1 + len(project) + 1  # ╭─ ◈ project_
    fill = max(1, w - vis_len - 1)  # -1 for ╮
    return header + "─" * fill + "╮"


def _make_bottom_border() -> str:
    """Full-width bottom border: ╰──────────────╯"""
    w = shutil.get_terminal_size().columns
    return "╰" + "─" * max(1, w - 2) + "╯"


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
        top = _make_top_border(project)
        return FormattedText([
            (f"{AM}", f"{top}\n"),
            (f"{AM}", "│ "),
        ])

    def _rprompt():
        return FormattedText([
            (f"{AM}", " │"),
        ])

    def _toolbar():
        return FormattedText([
            (f"bg:{ABG} {AM}", "  "),
            (f"bg:{ABG} bold {AC}", "/"),
            (f"bg:{ABG} {AD}", " 命令  "),
            (f"bg:{ABG} {AM}", "·  "),
            (f"bg:{ABG} bold {AC}", "↵"),
            (f"bg:{ABG} {AD}", " 执行  "),
            (f"bg:{ABG} {AM}", "·  "),
            (f"bg:{ABG} bold {AC}", "/help"),
            (f"bg:{ABG} {AD}", " 帮助  "),
            (f"bg:{ABG} {AM}", "·  "),
            (f"bg:{ABG} bold {AC}", "/exit"),
            (f"bg:{ABG} {AD}", " 退出  "),
        ])

    while True:
        try:
            user_input = session.prompt(
                _prompt, rprompt=_rprompt,
                bottom_toolbar=_toolbar, style=_style)
            # Print bottom border after input
            console.print(f"  [{AM}]{_make_bottom_border()}[/]")
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
            console.print(f"  [{AM}]{_make_bottom_border()}[/]")
        except EOFError:
            console.print(f"  [{AM}]{_make_bottom_border()}[/]")
            console.print(f"\n  [{AM}]Bye.[/]\n")
            break
        except Exception as e:
            console.print(f"  [{AM}]{_make_bottom_border()}[/]")
            console.print(f"\n  [{AH}]⚠[/] {e}")
            console.print(f"  [{AD}]REPL 已恢复[/]\n")
            try:
                import subprocess
                subprocess.run(["stty", "sane"], check=False)
            except Exception:
                pass
"""Agentbox REPL — Art Deco Morgan-style with rotating Rubik's cube."""

from __future__ import annotations

import os
import sys
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
from rich.text import Text
from rich.columns import Columns
from rich.align import Align

from . import __version__

console = Console()

# ═══════════════════════════════════════════════════════════════════
# Art Deco / Morgan-style color palette
# ═══════════════════════════════════════════════════════════════════

_GOLD = "#D4AF37"
_DARK_GOLD = "#B8860B"
_PALE_GOLD = "#F5E6CC"
_NAVY = "#0D1B2A"
_DARK_NAVY = "#1B2838"
_CREAM = "#FAF0E6"
_DEEP_RED = "#8B0000"
_EMERALD = "#006B3C"

# ═══════════════════════════════════════════════════════════════════
# Rotating Rubik's Cube — 6 frames, isometric 3D
# ═══════════════════════════════════════════════════════════════════

# Rubik's cube face colors (bg:style)
_FC = {
    "B": ("bg:#0051ff fg:#ffffff bold", "██"),  # Blue
    "G": ("bg:#00cc44 fg:#ffffff bold", "██"),  # Green
    "Y": ("bg:#ffcc00 fg:#1a1a1a bold", "██"),  # Yellow
    "R": ("bg:#ff2200 fg:#ffffff bold", "██"),  # Red
    "O": ("bg:#ff6600 fg:#ffffff bold", "██"),  # Orange
    "W": ("bg:#f0f0f0 fg:#1a1a1a bold", "██"),  # White
}

# Cube rotation sequence: (top, left, right) face colors
_CUBE_ROTATION = [
    ("B", "R", "G"),  # Blue top, Red left, Green right
    ("R", "Y", "B"),  # Red top, Yellow left, Blue right
    ("Y", "W", "R"),  # Yellow top, White left, Red right
    ("W", "O", "Y"),  # White top, Orange left, Yellow right
    ("O", "G", "W"),  # Orange top, Green left, White right
    ("G", "B", "O"),  # Green top, Blue left, Orange right
]

# Frame border style
_CB = f"bold {_GOLD}"  # cube border


def _build_cube_frame(top: str, left: str, right: str) -> list[tuple[str, str]]:
    """Build FormattedText tuples for one isometric cube frame.

    Layout:
       ╱TT╲       T = top face (2 blocks)
      ╱LLTT╲      L = left face (2 blocks)
      ╲LLRR╱      R = right face (2 blocks)
       ╲RR╱
    """
    t = _FC[top]
    l = _FC[left]
    r = _FC[right]
    return [
        ("", "  "), (_CB, "╱"), t, t, (_CB, "╲"), ("", "  "), ("", "\n"),
        ("", " "), (_CB, "╱"), l, l, t, t, (_CB, "╲"), ("", "\n"),
        ("", " "), (_CB, "╲"), l, l, r, r, (_CB, "╱"), ("", "  "), ("", "\n"),
        ("", "  "), (_CB, "╲"), r, r, (_CB, "╱"), ("", "  "),
    ]


def _get_cube_prompt(project_name: str) -> FormattedText:
    """Get the full prompt text with current rotating cube frame."""
    frame_idx = int(time.time() * 2.5) % len(_CUBE_ROTATION)
    top, left, right = _CUBE_ROTATION[frame_idx]
    cube = _build_cube_frame(top, left, right)

    parts = list(cube)
    # Separator + prompt line
    parts.extend([
        ("", "\n"),
        (f"bold {_GOLD}", "╭─"),
        ("", " "),
        (f"bold {_DARK_GOLD}", "◈"),
        ("", " "),
        (f"bold {_PALE_GOLD}", project_name),
        ("", " "),
        (f"{_DARK_GOLD}", "━━"),
        ("", " "),
        (f"bold {_GOLD}", "╯"),
        ("", "\n"),
        (f"bold {_GOLD}", "╰"),
        ("", " "),
        (f"bold {_GOLD}", "›"),
        ("", " "),
    ])
    return FormattedText(parts)


# ═══════════════════════════════════════════════════════════════════
# Slash commands with Chinese descriptions
# ═══════════════════════════════════════════════════════════════════

SLASH_COMMANDS = [
    # (command, description_zh, category, usage_hint)
    ("/claude",    "启动 Claude Code 沙盒",           "🤖 Agent",   ""),
    ("/codex",     "启动 OpenAI Codex 沙盒",          "🤖 Agent",   ""),
    ("/aider",     "启动 Aider 沙盒",                 "🤖 Agent",   ""),
    ("/goose",     "启动 Goose 沙盒",                 "🤖 Agent",   ""),
    ("/opencode",  "启动 OpenCode 沙盒",              "🤖 Agent",   ""),
    ("/run",       "运行任意 Agent",                   "🤖 Agent",   "<agent>"),
    ("/compose",   "多 Agent 角色组合协作",            "👥 多Agent", "claude:coder codex:reviewer"),
    ("/team",      "运行预定义团队",                   "👥 多Agent", "<team_id>"),
    ("/compare",   "多个 Agent 并排对比",             "👥 多Agent", "claude codex"),
    ("/ask",       "快捷提问，一键启动 Agent",         "💬 对话",    "\"你的问题\""),
    ("/status",    "查看所有会话和沙盒状态",           "📊 管理",    ""),
    ("/attach",    "重连到 tmux 会话",                "📊 管理",    "[session]"),
    ("/kill",      "停止会话和沙盒",                   "📊 管理",    "[session]"),
    ("/logs",      "查看沙盒日志",                     "📊 管理",    "[sandbox]"),
    ("/history",   "查看会话历史",                     "📊 管理",    ""),
    ("/diff",      "查看 Git 改动摘要",               "🔧 工作流",  ""),
    ("/merge",     "暂存并提交所有改动",              "🔧 工作流",  "-m \"msg\""),
    ("/review",    "审查改动+测试+合并/丢弃",         "🔧 工作流",  ""),
    ("/test",      "运行项目测试",                     "🔧 工作流",  ""),
    ("/pipeline",  "多步流水线编排",                   "🧠 流水线",  "dev \"任务\""),
    ("/list",      "列出可用 Agent 和团队",           "⚙️ 配置",    ""),
    ("/config",    "查看/编辑配置",                    "⚙️ 配置",    "show|edit|reset"),
    ("/init",      "初始化项目 AGENTS.md",            "⚙️ 配置",    ""),
    ("/shell",     "打开容器 Shell（同环境修改代码）",   "🐚 Shell",  "<agent>"),
    ("/help",      "显示帮助信息",                     "❓ 其他",    ""),
    ("/exit",      "退出 Agentbox",                   "❓ 其他",    ""),
]


class SlashCommandCompleter(Completer):
    """Completer that shows slash commands with Chinese descriptions."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        word = text.lower()
        for cmd, desc, cat, usage in SLASH_COMMANDS:
            if cmd.lower().startswith(word):
                display_text = f"{cmd}"
                if usage:
                    display_text += f" {usage}"
                meta = f"{cat}  {desc}"
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display=display_text,
                    display_meta=meta,
                )


def _build_key_bindings() -> KeyBindings:
    """Custom key bindings: Enter during completion only accepts, doesn't submit."""
    kb = KeyBindings()

    @kb.add("enter", filter=Condition(lambda: bool(
        _get_app().current_buffer.complete_state
    )))
    def _accept_completion(event):
        """When completion menu is visible, Enter only accepts the completion."""
        event.current_buffer.complete_state.current_completion \
            and event.current_buffer.apply_completion(
                event.current_buffer.complete_state.current_completion
            )

    return kb


def _get_app():
    """Helper to get the current prompt_toolkit app."""
    from prompt_toolkit.application import get_app
    return get_app()


# ═══════════════════════════════════════════════════════════════════
# Art Deco Splash Screen — Morgan Style
# ═══════════════════════════════════════════════════════════════════

def _print_splash() -> None:
    """Print the Agentbox splash screen in Art Deco Morgan style."""
    g, dg = _GOLD, _DARK_GOLD

    console.print()
    # Top stepped border — Art Deco ziggurat frame
    console.print(f"  [{g}]         ╔═══════════════════════════════════════════╗[/]")
    console.print(f"  [{g}]       ╔═╩═════════════════════════════════════════╩═╗[/]")
    console.print(f"  [{g}]     ╔═╩═════════════════════════════════════════════╩═╗[/]")
    console.print(f"  [{g}]     ║[/]                                           [{g}]║[/]")

    # Title with diamond ornaments
    console.print(f"  [{g}]     ║[/]    [{dg}]◈[/]   [bold {g}]A G E N T B O X[/]   [{dg}]◈[/]                [{g}]║[/]")

    # Decorative separator
    console.print(f"  [{g}]     ║[/]    [{dg}]━━━━━━━━━━━━━━━━━━━━━━━━━[/]                [{g}]║[/]")

    # Subtitle
    console.print(f"  [{g}]     ║[/]    [{_CREAM} italic]AI Agent Orchestration Sandbox[/]             [{g}]║[/]")
    console.print(f"  [{g}]     ║[/]    [{_PALE_GOLD} dim]v{__version__}[/]                                [{g}]║[/]")

    console.print(f"  [{g}]     ║[/]                                           [{g}]║[/]")

    # Bottom stepped border
    console.print(f"  [{g}]     ╚═════════════════════════════════════════════╝[/]")
    console.print(f"  [{g}]       ╚═══════════════════════════════════════════╝[/]")
    console.print(f"  [{g}]         ╚═══════════════════════════════════════════╝[/]")

    console.print()

    # Help hints
    console.print(f"  [{_CREAM}]◈[/]  输入 [bold {g}]/[/] 查看所有命令  [{dg}]·[/]  [bold {g}]↑↓[/] 选择  [{dg}]·[/]  [bold {g}]↵[/] 补全  [{dg}]·[/]  再 [bold {g}]↵[/] 执行")
    console.print(f"  [{_CREAM}]◈[/]  直接输入 [bold {g}]claude[/] 启动 Agent  [{dg}]·[/]  输入问题自动提问")
    console.print(f"  [{_CREAM}]◈[/]  [bold {g}]Ctrl+C[/] 取消  [{dg}]·[/]  [bold {g}]Ctrl+D[/] 或 [bold {g}]/exit[/] 退出")
    console.print()


def _print_help() -> None:
    """Print Art Deco styled help."""
    console.print()
    console.print(Panel(
        f"[bold {_GOLD}]◈  Agentbox 命令列表  ◈[/]\n\n"
        f"[{_CREAM} dim]输入 / 前缀触发补全 · ↑↓ 选择 · 回车补全 · 再回车执行[/]",
        border_style=_DARK_GOLD,
        padding=(0, 2),
    ))

    categories: dict[str, list[tuple[str, str, str]]] = {}
    for cmd, desc, cat, usage in SLASH_COMMANDS:
        categories.setdefault(cat, []).append((cmd, desc, usage))

    for cat, cmds in categories.items():
        console.print(f"\n  [bold {_GOLD}]{cat}[/]")
        console.print(f"  [{_DARK_GOLD}]{'─' * 44}[/]")
        for cmd, desc, usage in cmds:
            cmd_display = f"[{_GOLD}]{cmd}[/]"
            if usage:
                cmd_display += f" [{_CREAM} dim]{usage}[/]"
            console.print(f"  {cmd_display:<30} [{_PALE_GOLD}]{desc}[/]")

    console.print()


# ═══════════════════════════════════════════════════════════════════
# Command execution
# ═══════════════════════════════════════════════════════════════════

def _execute_slash_command(ctx: Any, raw_input: str) -> bool:
    """Parse and execute a slash command. Returns False if should quit."""
    parts = raw_input.strip().split()
    if not parts:
        return True

    cmd = parts[0].lower()
    args = parts[1:]

    from .cli import _interactive_agent_select, _parse_agent_role
    from .config import list_teams
    from .agents import AgentRunner

    config = ctx.obj["config"]
    project_path = ctx.obj["project_path"]
    runner = AgentRunner(config)

    simple_agents = {"claude", "codex", "aider", "goose", "opencode"}
    cmd_name = cmd.lstrip("/")

    if cmd_name in simple_agents and not args:
        runner.run_agent(cmd_name, project_path)
    elif cmd_name == "run":
        agent_id = args[0] if args else None
        if not agent_id:
            agent_id = _interactive_agent_select(config)
        if agent_id:
            prompt = " ".join(args[1:]) if len(args) > 1 else None
            runner.run_agent(agent_id, project_path, prompt=prompt)
    elif cmd_name in simple_agents and args:
        prompt = " ".join(args)
        runner.run_agent(cmd_name, project_path, prompt=prompt)
    elif cmd_name == "ask":
        question = " ".join(args) if args else None
        if not question:
            question = click_prompt("输入你的问题")
        from .workflow import WorkflowEngine
        engine = WorkflowEngine(config)
        engine.ask(prompt=question, agent_id="claude", project_path=project_path)
    elif cmd_name == "compose":
        if not args:
            specs_str = click_prompt("输入组合 (如 claude:coder codex:reviewer)")
            args = specs_str.strip().split()
        composition = [_parse_agent_role(s) for s in args]
        runner.run_compose(composition, project_path)
    elif cmd_name == "team":
        team_id = args[0] if args else None
        if not team_id:
            teams = list_teams(config)
            for i, t in enumerate(teams, 1):
                console.print(f"  {i}. [{_GOLD}]{t['id']}[/] — {t.get('description', '')}")
            team_id = click_prompt("选择团队", default="dev-team")
        runner.run_team(team_id, project_path)
    elif cmd_name == "compare":
        agents_list = args if args else ["claude", "codex"]
        runner.run_compare(agents_list, project_path)
    elif cmd_name == "status":
        from .cli import status
        ctx.invoke(status)
    elif cmd_name == "attach":
        from .cli import attach
        ctx.invoke(attach)
    elif cmd_name == "kill":
        from .cli import kill
        ctx.invoke(kill)
    elif cmd_name == "logs":
        from .cli import logs
        ctx.invoke(logs)
    elif cmd_name == "history":
        from .cli import history
        ctx.invoke(history)
    elif cmd_name == "diff":
        from .cli import diff_cmd
        ctx.invoke(diff_cmd)
    elif cmd_name == "merge":
        msg = " ".join(args) if args else "Update project"
        from .cli import merge
        ctx.invoke(merge, message=msg)
    elif cmd_name == "review":
        from .cli import review
        ctx.invoke(review)
    elif cmd_name == "test":
        from .cli import test_cmd
        ctx.invoke(test_cmd)
    elif cmd_name == "pipeline":
        from .orchestrator import Orchestrator
        from .orchestrator.pipeline import dev_pipeline, research_pipeline, compare_pipeline
        ptype = args[0] if args else "dev"
        task = " ".join(args[1:]) if len(args) > 1 else click_prompt("输入任务描述")
        orch = Orchestrator(config)
        if ptype == "dev":
            orch.execute(dev_pipeline(task), project_path)
        elif ptype == "research":
            orch.execute(research_pipeline(task), project_path)
        elif ptype == "compare":
            orch.execute(compare_pipeline(task), project_path)
    elif cmd_name == "list":
        from .cli import list as list_cmd
        ctx.invoke(list_cmd)
    elif cmd_name == "config":
        from .cli import config_show
        ctx.invoke(config_show)
    elif cmd_name == "init":
        from .cli import init
        ctx.invoke(init)
    elif cmd_name == "shell":
        target_agent = args[0] if args else "claude"
        runner.run_shell(target_agent, project_path)
    elif cmd_name == "help":
        _print_help()
    elif cmd_name in ("exit", "quit", "q"):
        console.print(f"\n  [{_CREAM} dim]👋 再见！[/]")
        return False
    else:
        console.print(f"\n  [{_DEEP_RED}]✘ 未知命令:[/] {cmd}  [{_CREAM} dim]输入 / 查看所有命令[/]\n")

    return True


def click_prompt(msg: str, default: str = "") -> str:
    """Simple prompt fallback."""
    try:
        val = input(f"  {msg}: ").strip()
        return val or default
    except (EOFError, KeyboardInterrupt):
        return default


# ═══════════════════════════════════════════════════════════════════
# prompt_toolkit style — Art Deco theme
# ═══════════════════════════════════════════════════════════════════

_repl_style = PtStyle.from_dict({
    "bottom-toolbar": f"bg:{_NAVY} {_CREAM}",
    "bottom-toolbar.text": f"bg:{_NAVY} {_PALE_GOLD}",
    "completion-menu": f"bg:{_DARK_NAVY} {_CREAM}",
    "completion-menu.completion": f"bg:{_DARK_NAVY} {_CREAM}",
    "completion-menu.completion.current": f"bg:{_GOLD} #000000 bold",
    "completion-menu.meta": f"bg:{_NAVY} #888888",
    "completion-menu.completion.current meta": f"bg:{_GOLD} #1a1a1a",
})


# ═══════════════════════════════════════════════════════════════════
# Main REPL loop
# ═══════════════════════════════════════════════════════════════════

def run_repl(ctx: Any) -> None:
    """Run the interactive Agentbox REPL with Art Deco styling and rotating cube."""
    _print_splash()

    kb = _build_key_bindings()

    session: PromptSession = PromptSession(
        history=InMemoryHistory(),
        completer=SlashCommandCompleter(),
        auto_suggest=AutoSuggestFromHistory(),
        complete_while_typing=True,
        multiline=False,
        key_bindings=kb,
        refresh_interval=0.4,  # Refresh for cube animation
    )

    project_name = os.path.basename(ctx.obj["project_path"])

    def _bottom_toolbar():
        """Bottom toolbar with Art Deco styling and contextual hints."""
        frame_idx = int(time.time() * 2.5) % len(_CUBE_ROTATION)
        face_names = {"B": "🔵", "G": "🟢", "Y": "🟡", "R": "🔴", "O": "🟠", "W": "⚪"}
        top, left, right = _CUBE_ROTATION[frame_idx]
        cube_icon = f"{face_names[top]}{face_names[left]}{face_names[right]}"

        return FormattedText([
            (f"bg:{_NAVY} {_PALE_GOLD}", f"  ◈ {cube_icon} "),
            (f"bg:{_NAVY} {_CREAM}", "输入 "),
            (f"bg:{_NAVY} bold {_GOLD}", "/"),
            (f"bg:{_NAVY} {_CREAM}", " 查看命令  ·  "),
            (f"bg:{_NAVY} bold {_GOLD}", "↑↓"),
            (f"bg:{_NAVY} {_CREAM}", " 选择  ·  "),
            (f"bg:{_NAVY} bold {_GOLD}", "↵"),
            (f"bg:{_NAVY} {_CREAM}", " 补全  ·  再 "),
            (f"bg:{_NAVY} bold {_GOLD}", "↵"),
            (f"bg:{_NAVY} {_CREAM}", " 执行  ·  "),
            (f"bg:{_NAVY} bold {_GOLD}", "/exit"),
            (f"bg:{_NAVY} {_CREAM}", " 退出  "),
        ])

    while True:
        try:
            user_input = session.prompt(
                lambda: _get_cube_prompt(project_name),
                bottom_toolbar=_bottom_toolbar,
                style=_repl_style,
            )

            if not user_input or not user_input.strip():
                continue

            user_input = user_input.strip()

            # If starts with /, it's a slash command
            if user_input.startswith("/"):
                if not _execute_slash_command(ctx, user_input):
                    break
            else:
                # Non-slash input
                from .agents import AgentRunner

                config = ctx.obj["config"]
                runner = AgentRunner(config)

                first_word = user_input.split()[0].lower()
                if first_word in config.get("agents", {}):
                    rest = user_input[len(first_word):].strip()
                    runner.run_agent(first_word, ctx.obj["project_path"], prompt=rest or None)
                else:
                    from .workflow import WorkflowEngine
                    engine = WorkflowEngine(config)
                    engine.ask(prompt=user_input, agent_id="claude", project_path=ctx.obj["project_path"])

        except KeyboardInterrupt:
            console.print(f"\n  [{_CREAM} dim]按 Ctrl+D 或输入 /exit 退出[/]")
            continue
        except EOFError:
            console.print(f"\n  [{_CREAM} dim]👋 再见！[/]\n")
            break
        except Exception as e:
            # Catch ALL exceptions — REPL never crashes out
            console.print(f"\n  [{_DEEP_RED}]⚠ 错误:[/] {e}")
            console.print(f"  [{_CREAM} dim]REPL 已恢复，输入 /exit 退出[/]\n")
            # Ensure terminal is in a sane state
            try:
                import subprocess
                subprocess.run(["stty", "sane"], check=False)
            except Exception:
                pass
            continue
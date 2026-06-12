"""Agentbox REPL — Cyber hacker style with rotating binary cube."""

from __future__ import annotations

import math
import os
import random
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

# ── Cyber palette ──
CY = "#00FF41"      # Matrix green
CG = "#00CC33"      # Darker green
CD = "#009926"      # Dim green
CB = "#001a0d"      # Dark bg
CN = "#0a0a0a"      # Near black
CW = "#c0c0c0"      # Light gray
CR2 = "#FAF0E6"     # Cream (dim text)

# ── 3D Binary Cube Engine ──
# 8 vertices of a unit cube
_VERTS = [
    (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
    (-1, -1,  1), (1, -1,  1), (1, 1,  1), (-1, 1,  1),
]
# 12 edges (vertex index pairs)
_EDGES = [
    (0,1),(1,2),(2,3),(3,0),  # back face
    (4,5),(5,6),(6,7),(7,4),  # front face
    (0,4),(1,5),(2,6),(3,7),  # connecting edges
]

# Canvas size for cube rendering
_CW, _CH = 10, 7


def _rotate_y(v: tuple, angle: float) -> tuple:
    x, y, z = v
    c, s = math.cos(angle), math.sin(angle)
    return (x * c + z * s, y, -x * s + z * c)


def _rotate_x(v: tuple, angle: float) -> tuple:
    x, y, z = v
    c, s = math.cos(angle), math.sin(angle)
    return (x, y * c - z * s, y * s + z * c)


def _render_cube(angle_y: float, angle_x: float = 0.3) -> list[str]:
    """Render a rotating wireframe cube using 0s and 1s.

    Returns list of strings (lines of the cube).
    """
    # Rotate all vertices
    rotated = []
    for v in _VERTS:
        r = _rotate_y(v, angle_y)
        r = _rotate_x(r, angle_x)
        rotated.append(r)

    # Project to 2D (orthographic, scaled)
    scale = 2.0
    projected = []
    for x, y, z in rotated:
        px = int((x * scale) + _CW // 2)
        py = int((-y * scale) + _CH // 2)
        projected.append((px, py))

    # Create canvas
    canvas = [[" "] * _CW for _ in range(_CH)]

    # Draw edges with binary digits
    for i, j in _EDGES:
        x0, y0 = projected[i]
        x1, y1 = projected[j]
        # Bresenham-like line drawing
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for s in range(steps + 1):
            t = s / steps
            x = int(x0 + (x1 - x0) * t)
            y = int(y0 + (y1 - y0) * t)
            if 0 <= x < _CW and 0 <= y < _CH:
                canvas[y][x] = random.choice("01")

    # Draw vertices brighter
    for px, py in projected:
        if 0 <= px < _CW and 0 <= py < _CH:
            canvas[py][px] = random.choice("01")

    return ["".join(row) for row in canvas]


def _cube_frame() -> list[str]:
    """Get current rotating cube frame."""
    angle = time.time() * 1.2  # Rotation speed
    return _render_cube(angle)


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
                display = f"{cmd} {usage}".strip()
                meta = f"{cat}  {desc}" if cat else desc
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
    # Render a static cube for splash
    cube = _render_cube(0.8)
    cube_lines = "\n".join(f"    {line}" for line in cube)
    console.print(f"  [{CG}]{cube_lines}[/]")
    console.print()
    console.print(f"  [bold {CY}]{_BANNER}[/]")
    console.print(f"  [bold {CY}]Agentbox[/] [{CD}]v{__version__}[/]  [{CD}]·[/]  [{CD}]AI Agent 编排沙盒[/]")
    console.print()
    console.print(f"  [{CD}]{'─' * 43}[/]")
    console.print()
    console.print(f"  [{CD}]◈[/]  输入 [bold {CY}]/[/] 查看所有命令  [{CD}]·[/]  [bold {CY}]↑↓[/] 选择  [{CD}]·[/]  [bold {CY}]↵[/] 补全/执行")
    console.print(f"  [{CD}]◈[/]  直接输入 [bold {CY}]claude[/] 启动 Agent  [{CD}]·[/]  输入问题自动提问")
    console.print(f"  [{CD}]◈[/]  [bold {CY}]Ctrl+C[/] 取消  [{CD}]·[/]  [bold {CY}]Ctrl+D[/] 或 [bold {CY}]/exit[/] 退出")
    console.print()


# ── Help ──
def _help() -> None:
    console.print()
    console.print(Panel(
        f"[bold {CY}]◈  Agentbox 命令列表  ◈[/]\n"
        f"[{CW} dim]输入 / 触发补全 · ↑↓ 选择 · ↵ 执行[/]",
        border_style=CD, padding=(0, 2)))

    cats: dict[str, list] = {}
    for cmd, desc, cat, usage in _CMDS:
        cats.setdefault(cat or "Other", []).append((cmd, desc, usage))

    for cat, cmds in cats.items():
        console.print(f"\n  [bold {CY}]{cat}[/]")
        console.print(f"  [{CD}]{'─' * 40}[/]")
        for cmd, desc, usage in cmds:
            c = f"[{CY}]{cmd}[/]" + (f" [{CW} dim]{usage}[/]" if usage else "")
            console.print(f"  {c:<28} [{CG}]{desc}[/]")
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
            console.print(f"\n  [{CD}]Bye.[/]")
            return False
        else:
            console.print(f"\n  [{CY}]✘[/] 未知命令: {cmd}  [{CD}]输入 / 查看命令[/]\n")
    except Exception as e:
        console.print(f"\n  [{CY}]⚠[/] {e}")
        console.print(f"  [{CD}]输入 /help 查看命令[/]\n")

    return True


# ── prompt_toolkit style ──
_style = PtStyle.from_dict({
    "bottom-toolbar": f"bg:{CB} {CY}",
    "completion-menu": f"bg:#0d1a0d {CW}",
    "completion-menu.completion": f"bg:#0d1a0d {CW}",
    "completion-menu.completion.current": f"bg:{CY} #000000 bold",
    "completion-menu.meta": f"bg:{CB} #888888",
    "completion-menu.completion.current meta": f"bg:{CY} #1a1a1a",
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
        refresh_interval=0.4,
    )

    project = os.path.basename(ctx.obj["project_path"])

    def _prompt():
        # Rotating binary cube as prompt header
        cube = _cube_frame()
        parts = []
        for line in cube:
            parts.append((f"{CD}", f"  {line}\n"))
        parts.extend([
            (f"bold {CY}", "╭─"),
            ("", " "),
            (f"{CG}", f"⬡ {project}"),
            ("", " "),
            (f"bold {CY}", "──╯"),
            ("", "\n"),
            (f"bold {CY}", "╰ "),
            (f"bold {CY}", "› "),
        ])
        return FormattedText(parts)

    def _toolbar():
        cube = _cube_frame()
        # Show a single-line mini cube in toolbar
        mini = cube[len(cube) // 2]  # Middle line of cube
        return FormattedText([
            (f"bg:{CB} {CD}", f"  {mini}  "),
            (f"bg:{CB} {CW}", "输入 "),
            (f"bg:{CB} bold {CY}", "/"),
            (f"bg:{CB} {CW}", " 命令  ·  "),
            (f"bg:{CB} bold {CY}", "↵"),
            (f"bg:{CB} {CW}", " 执行  ·  "),
            (f"bg:{CB} bold {CY}", "/exit"),
            (f"bg:{CB} {CW}", " 退出  "),
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
            console.print(f"\n  [{CD}]Bye.[/]\n")
            break
        except Exception as e:
            console.print(f"\n  [{CY}]⚠[/] {e}")
            console.print(f"  [{CD}]REPL 已恢复[/]\n")
            try:
                import subprocess
                subprocess.run(["stty", "sane"], check=False)
            except Exception:
                pass
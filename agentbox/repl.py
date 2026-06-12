"""Agentbox REPL — interactive command shell with slash-command autocomplete."""

from __future__ import annotations

import os
import sys
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from . import __version__

console = Console()

# ── Slash commands with Chinese descriptions ──

SLASH_COMMANDS = [
    # (command, description_zh, category)
    ("/claude",    "启动 Claude Code 沙盒",           "Agent"),
    ("/codex",     "启动 OpenAI Codex 沙盒",          "Agent"),
    ("/aider",     "启动 Aider 沙盒",                 "Agent"),
    ("/goose",     "启动 Goose 沙盒",                 "Agent"),
    ("/opencode",  "启动 OpenCode 沙盒",              "Agent"),
    ("/run",       "运行任意 Agent (需加名字)",        "Agent"),
    ("/compose",   "多 Agent 角色组合协作",            "多Agent"),
    ("/team",      "运行预定义团队",                   "多Agent"),
    ("/compare",   "多个 Agent 并排对比",             "多Agent"),
    ("/ask",       "快捷提问，一键启动 Agent",         "对话"),
    ("/status",    "查看所有会话和沙盒状态",           "管理"),
    ("/attach",    "重连到 tmux 会话",                "管理"),
    ("/kill",      "停止会话和沙盒（保留数据）",       "管理"),
    ("/logs",      "查看沙盒日志",                     "管理"),
    ("/history",   "查看会话历史",                     "管理"),
    ("/diff",      "查看 Git 改动摘要",               "工作流"),
    ("/merge",     "暂存并提交所有改动",              "工作流"),
    ("/review",    "审查改动+测试+合并/丢弃",         "工作流"),
    ("/test",      "运行项目测试",                     "工作流"),
    ("/pipeline",  "多步流水线编排",                   "流水线"),
    ("/list",      "列出可用 Agent 和团队",           "配置"),
    ("/config",    "查看/编辑配置",                    "配置"),
    ("/init",      "初始化项目 AGENTS.md",            "配置"),
    ("/help",      "显示帮助信息",                     "其他"),
    ("/quit",      "退出 Agentbox",                   "其他"),
]


class SlashCommandCompleter(Completer):
    """Completer that shows slash commands with Chinese descriptions."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        # Only complete when input starts with /
        if not text.startswith("/"):
            return

        word = text.lower()

        for cmd, desc, cat in SLASH_COMMANDS:
            if cmd.lower().startswith(word):
                # Show command as completion, description in meta
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display=f"{cmd}",
                    display_meta=f"[{cat}] {desc}",
                )


def _print_splash() -> None:
    """Print the Agentbox splash screen."""
    splash = r"""
     _                 _           _
    / \   __ _ ___ ___| |__   __ _(_)_ __
   / _ \ / _` / __/ __| '_ \ / _` | | '_ \
  / ___ \ (_| \__ \__ \ |_) | (_| | | | | |
 /_/   \_\__,_|___/___/_.__/ \__,_|_|_| |_|

    """
    text = Text(splash, style="bold cyan")
    console.print(text)
    console.print(f"  [bold]v{__version__}[/bold]  [dim]— AI Agent 编排沙盒[/dim]")
    console.print()
    console.print("  [dim]输入命令开始使用 | 输入[/dim] [cyan]/[/cyan] [dim]查看所有命令 |[/dim] [cyan]/quit[/cyan] [dim]退出[/dim]")
    console.print()


def _print_help() -> None:
    """Print quick help."""
    console.print("\n[bold cyan]🧊 Agentbox 命令列表[/bold cyan]")
    console.print("[dim]输入 / 前缀可触发自动补全，方向键选择，回车补全，再回车执行[/dim]\n")

    # Group by category
    categories: dict[str, list[tuple[str, str]]] = {}
    for cmd, desc, cat in SLASH_COMMANDS:
        categories.setdefault(cat, []).append((cmd, desc))

    for cat, cmds in categories.items():
        console.print(f"  [bold]{cat}[/bold]")
        for cmd, desc in cmds:
            console.print(f"    [cyan]{cmd:<14}[/cyan] {desc}")
        console.print()


def _execute_slash_command(ctx: Any, raw_input: str) -> bool:
    """Parse and execute a slash command. Returns False if should quit."""
    parts = raw_input.strip().split()
    if not parts:
        return True

    cmd = parts[0].lower()
    args = parts[1:]

    # Import here to avoid circular imports
    from .cli import _execute_palette_choice, _interactive_agent_select
    from .config import list_teams
    from .agents import AgentRunner

    config = ctx.obj["config"]
    project_path = ctx.obj["project_path"]
    runner = AgentRunner(config)

    # Map slash commands to palette choices
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
        # e.g. /claude -p "fix bug"
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
        from .cli import _parse_agent_role
        composition = [_parse_agent_role(s) for s in args]
        runner.run_compose(composition, project_path)
    elif cmd_name == "team":
        team_id = args[0] if args else None
        if not team_id:
            teams = list_teams(config)
            for i, t in enumerate(teams, 1):
                console.print(f"  {i}. [cyan]{t['id']}[/cyan] — {t.get('description', '')}")
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
    elif cmd_name == "help":
        _print_help()
    elif cmd_name in ("quit", "exit", "q"):
        console.print("[dim]👋 再见！[/dim]")
        return False
    else:
        console.print(f"[red]未知命令: {cmd}[/red]  [dim]输入 / 查看所有命令[/dim]")

    return True


def click_prompt(msg: str, default: str = "") -> str:
    """Simple prompt fallback."""
    try:
        val = input(f"{msg}: ").strip()
        return val or default
    except (EOFError, KeyboardInterrupt):
        return default


def run_repl(ctx: Any) -> None:
    """Run the interactive Agentbox REPL."""
    _print_splash()

    session: PromptSession = PromptSession(
        history=InMemoryHistory(),
        completer=SlashCommandCompleter(),
        auto_suggest=AutoSuggestFromHistory(),
        complete_while_typing=True,
        multiline=False,
        prompt_continuation="... ",
    )

    project_name = os.path.basename(ctx.obj["project_path"])

    while True:
        try:
            # Build the prompt: 🧊 project >
            prompt_text = FormattedText([
                ("bold cyan", "🧊 "),
                ("bold green", f"{project_name}"),
                ("", " > "),
            ])

            user_input = session.prompt(prompt_text)

            if not user_input or not user_input.strip():
                continue

            user_input = user_input.strip()

            # If starts with /, it's a slash command
            if user_input.startswith("/"):
                if not _execute_slash_command(ctx, user_input):
                    break
            else:
                # Non-slash input: treat as a quick agent launch or ask
                # e.g. "claude" → run claude, "fix the bug" → ask claude
                from .agents import AgentRunner
                from .config import get_agent_config

                config = ctx.obj["config"]
                runner = AgentRunner(config)

                first_word = user_input.split()[0].lower()
                if first_word in config.get("agents", {}):
                    # Direct agent name
                    rest = user_input[len(first_word):].strip()
                    runner.run_agent(first_word, ctx.obj["project_path"], prompt=rest or None)
                else:
                    # Treat as a question to default agent
                    from .workflow import WorkflowEngine
                    engine = WorkflowEngine(config)
                    engine.ask(prompt=user_input, agent_id="claude", project_path=ctx.obj["project_path"])

        except KeyboardInterrupt:
            # Ctrl+C — show hint, don't exit
            console.print("\n[dim]按 Ctrl+D 或输入 /quit 退出[/dim]")
            continue
        except EOFError:
            # Ctrl+D — exit
            console.print("\n[dim]👋 再见！[/dim]")
            break
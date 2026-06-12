"""Agentbox CLI - simplified single-entry command interface.

All common operations are top-level commands under `ag`:
  ag                Pick an agent interactively
  ag claude         Run Claude in sandbox
  ag status         Dashboard
  ag attach         Reconnect to session
  ag kill           Kill session + sandbox
  ag logs           View sandbox logs
  ag history        Session history
"""

import os
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .agents import AgentRunner
from .compose import DockerComposeManager
from .config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_FILE,
    detect_local_agents,
    list_agents,
    list_teams,
    load_config,
    save_config,
)
from .sandbox import SandboxManager
from .orchestrator import Orchestrator, Pipeline, PipelineStep
from .orchestrator.pipeline import StepType, dev_pipeline, research_pipeline, compare_pipeline
from .state import cleanup_stale_sessions, get_session_info, list_all_sessions, recover_orphaned_sessions, unregister_session
from .tmux_mgr import TmuxManager
from .workflow import WorkflowEngine

console = Console()


def _parse_agent_role(spec: str) -> dict[str, str]:
    """Parse an 'agent:role' specification."""
    if ":" in spec:
        parts = spec.split(":", 1)
        return {"agent": parts[0], "role": parts[1]}
    return {"agent": spec, "role": spec}


# ── Interactive command palette ──

COMMAND_PALETTE = [
    # (key, command, description_zh, category)
    ("claude",    "ag claude",              "启动 Claude Code 沙盒",           "🤖 启动 Agent"),
    ("codex",     "ag codex",               "启动 OpenAI Codex 沙盒",          "🤖 启动 Agent"),
    ("aider",     "ag aider",               "启动 Aider 沙盒",                 "🤖 启动 Agent"),
    ("goose",     "ag goose",               "启动 Goose 沙盒",                 "🤖 启动 Agent"),
    ("opencode",  "ag opencode",            "启动 OpenCode 沙盒",              "🤖 启动 Agent"),
    ("run",       "ag run <agent>",         "运行任意已配置的 Agent",           "🤖 启动 Agent"),
    ("compose",   "ag compose a:r b:r",     "多 Agent 角色组合协作",           "👥 多 Agent"),
    ("team",      "ag team <id>",           "运行预定义团队",                  "👥 多 Agent"),
    ("compare",   "ag compare a b",         "多个 Agent 并排对比",            "👥 多 Agent"),
    ("ask",       'ag ask "问题"',          "快捷提问，一键启动 Agent",        "💬 对话"),
    ("status",    "ag status",              "查看所有会话和沙盒状态",          "📊 管理"),
    ("attach",    "ag attach",              "重连到 tmux 会话",               "📊 管理"),
    ("kill",      "ag kill",                "停止会话和沙盒（保留数据）",      "📊 管理"),
    ("logs",      "ag logs",                "查看沙盒日志",                    "📊 管理"),
    ("history",   "ag history",             "查看会话历史",                    "📊 管理"),
    ("diff",      "ag diff",                "查看 Git 改动摘要",              "🔧 工作流"),
    ("merge",     'ag merge -m "msg"',      "暂存并提交所有改动",             "🔧 工作流"),
    ("review",    "ag review",              "审查改动+测试+合并/丢弃",        "🔧 工作流"),
    ("test",      "ag test",                "运行项目测试",                    "🔧 工作流"),
    ("pipeline",  "ag pipeline dev",        "多步流水线编排",                  "🧠 流水线"),
    ("list",      "ag list",                "列出可用 Agent 和团队",          "⚙️ 配置"),
    ("config",    "ag config show",         "查看/编辑配置",                   "⚙️ 配置"),
    ("init",      "ag init",                "初始化项目 AGENTS.md",           "⚙️ 配置"),
]


def _interactive_command_palette(config: dict) -> str | None:
    """Show interactive command palette with Chinese descriptions."""
    console.print("\n[bold cyan]🧊 Agentbox 命令面板[/bold cyan]")
    console.print("[dim]输入 / 可随时唤出此面板 | 输入编号或命令名选择[/dim]\n")

    # Group by category
    categories: dict[str, list[tuple[str, str, str]]] = {}
    for key, cmd, desc_zh, cat in COMMAND_PALETTE:
        categories.setdefault(cat, []).append((key, cmd, desc_zh))

    items = []  # (key, cmd, desc_zh)
    idx = 1
    for cat, cmds in categories.items():
        console.print(f"  [bold]{cat}[/bold]")
        for key, cmd, desc_zh in cmds:
            items.append((key, cmd, desc_zh))
            console.print(f"    [green]{idx:>2}[/green]. [cyan]{cmd:<30}[/cyan] {desc_zh}")
            idx += 1
        console.print()

    console.print("[dim]0. 退出[/dim]\n")

    while True:
        choice = click.prompt("选择命令", type=str, default="1")

        if choice.strip() == "0":
            return None

        # Try as number
        try:
            num = int(choice.strip())
            if 1 <= num <= len(items):
                return items[num - 1][0]
            console.print(f"[red]无效编号，请输入 1-{len(items)}[/red]")
            continue
        except ValueError:
            pass

        # Try as command key / partial match
        choice_lower = choice.strip().lower()
        matches = [item for item in items if item[0] == choice_lower or choice_lower in item[0]]
        if len(matches) == 1:
            return matches[0][0]
        elif len(matches) > 1:
            console.print(f"[yellow]多个匹配: {', '.join(m[0] for m in matches)}，请更精确[/yellow]")
            continue
        else:
            console.print(f"[red]未找到命令: {choice}[/red]")
            continue


def _interactive_agent_select(config: dict) -> str | None:
    """Show interactive agent selector when no agent is specified."""
    local_agents = detect_local_agents()
    all_agents = config.get("agents", {})

    if not local_agents and not all_agents:
        console.print("[red]No agents available.[/red]")
        console.print("[dim]Install an agent CLI first (claude, codex, aider, etc.)[/dim]")
        return None

    console.print("\n[bold]🧊 Select an agent to run in sandbox:[/bold]\n")

    items = []
    for a in local_agents:
        agent_config = all_agents.get(a["id"], {})
        name = agent_config.get("name", a["id"])
        items.append(a["id"])
        console.print(f"  [green]{len(items)}[/green]. 📦 {name} ([cyan]{a['id']}[/cyan]) — installed at {a['path']}")

    for agent_id, agent_config in all_agents.items():
        if agent_id not in {a["id"] for a in local_agents}:
            items.append(agent_id)
            name = agent_config.get("name", agent_id)
            console.print(f"  [green]{len(items)}[/green]. ☁️  {name} ([cyan]{agent_id}[/cyan]) — [dim]will install in sandbox[/dim]")

    if not items:
        console.print("[red]No agents available.[/red]")
        return None

    console.print()
    choice = click.prompt("Select agent", type=int, default=1)

    if 1 <= choice <= len(items):
        return items[choice - 1]
    else:
        console.print("[red]Invalid selection[/red]")
        return None


def _execute_palette_choice(ctx: click.Context, choice: str) -> None:
    """Execute a command selected from the palette."""
    config = ctx.obj["config"]
    project_path = ctx.obj["project_path"]
    runner = AgentRunner(config)

    # Agent shortcuts — launch directly
    if choice in ("claude", "codex", "aider", "goose", "opencode"):
        runner.run_agent(choice, project_path)
    elif choice == "run":
        agent_id = _interactive_agent_select(config)
        if agent_id:
            runner.run_agent(agent_id, project_path)
    elif choice == "compose":
        specs = click.prompt("输入组合 (如 claude:coder codex:reviewer)", type=str)
        composition = [_parse_agent_role(s) for s in specs.strip().split()]
        runner.run_compose(composition, project_path)
    elif choice == "team":
        teams = list_teams(config)
        if not teams:
            console.print("[red]没有配置团队[/red]")
            return
        console.print("\n[bold]可用团队:[/bold]")
        for i, t in enumerate(teams, 1):
            console.print(f"  {i}. [cyan]{t['id']}[/cyan] — {t.get('description', '')}")
        idx = click.prompt("选择团队编号", type=int, default=1)
        if 1 <= idx <= len(teams):
            runner.run_team(teams[idx - 1]["id"], project_path)
    elif choice == "compare":
        agents_str = click.prompt("输入对比的 Agent (如 claude codex)", type=str)
        agents_list = agents_str.strip().split()
        runner.run_compare(agents_list, project_path)
    elif choice == "ask":
        question = click.prompt("输入你的问题", type=str)
        engine = WorkflowEngine(config)
        engine.ask(prompt=question, agent_id="claude", project_path=project_path)
    elif choice == "status":
        # Invoke the status command
        ctx.invoke(status)
    elif choice == "attach":
        ctx.invoke(attach)
    elif choice == "kill":
        ctx.invoke(kill)
    elif choice == "logs":
        ctx.invoke(logs)
    elif choice == "history":
        ctx.invoke(history)
    elif choice == "diff":
        ctx.invoke(diff_cmd)
    elif choice == "merge":
        msg = click.prompt("提交信息", type=str, default="Update project")
        ctx.invoke(merge, message=msg)
    elif choice == "review":
        ctx.invoke(review)
    elif choice == "test":
        ctx.invoke(test_cmd)
    elif choice == "pipeline":
        console.print("\n[bold]可用流水线:[/bold]")
        console.print("  1. dev      — 规划→编码→审查")
        console.print("  2. research — 研究→总结→评审")
        console.print("  3. compare  — 多Agent对比→综合")
        ptype = click.prompt("选择流水线", type=str, default="dev")
        task = click.prompt("输入任务描述", type=str)
        orch = Orchestrator(config)
        if ptype == "dev":
            orch.execute(dev_pipeline(task), project_path)
        elif ptype == "research":
            orch.execute(research_pipeline(task), project_path)
        elif ptype == "compare":
            orch.execute(compare_pipeline(task), project_path)
    elif choice == "list":
        ctx.invoke(list)
    elif choice == "config":
        ctx.invoke(config_show)
    elif choice == "init":
        ctx.invoke(init)
    else:
        console.print(f"[yellow]未知命令: {choice}[/yellow]")


# ═══════════════════════════════════════════════════════════════════
# Main group
# ═══════════════════════════════════════════════════════════════════

@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="ag")
@click.option("-p", "--project", "project_path", default=None, help="Project directory path")
@click.pass_context
def main(ctx: click.Context, project_path: str | None) -> None:
    """🧊 Agentbox — AI Agent sandbox CLI

    \b
    Quick start:
      ag              Pick an agent interactively
      ag claude       Run Claude Code in sandbox
      ag codex        Run OpenAI Codex in sandbox
      ag status       Dashboard: view all sessions & sandboxes
      ag attach       Reconnect to a session
      ag kill         Kill a session and its sandbox
    """
    ctx.ensure_object(dict)
    ctx.obj["project_path"] = project_path or os.getcwd()
    ctx.obj["config"] = load_config()

    if ctx.invoked_subcommand is None:
        config = ctx.obj["config"]
        choice = _interactive_command_palette(config)
        if choice:
            _execute_palette_choice(ctx, choice)


# ═══════════════════════════════════════════════════════════════════
# Agent shortcuts — ag claude / ag codex / ag aider / ...
# ═══════════════════════════════════════════════════════════════════

def _make_agent_command(agent_id: str):
    """Factory to create agent shortcut commands."""
    @click.option("-p", "--prompt", default=None, help="Prompt to send")
    @click.option("-r", "--role", default=None, help="Role label (e.g., 'planner', 'coder')")
    @click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
    @click.pass_context
    def agent_cmd(ctx: click.Context, prompt: str | None, role: str | None, no_attach: bool) -> None:
        runner = AgentRunner(ctx.obj["config"])
        runner.run_agent(agent_id, ctx.obj["project_path"], prompt, attach=not no_attach, role=role)
    return agent_cmd

# Register agent shortcut commands
for _aid in ["claude", "codex", "aider", "goose", "opencode"]:
    _cmd = _make_agent_command(_aid)
    _cmd.__doc__ = f"🤖 Run {_aid.capitalize()} in Docker sandbox."
    main.add_command(click.command(name=_aid)(_cmd))


# ── / shortcut: ag / → command palette ──
# Click doesn't allow "/" as command name, so we use a unicode lookalike
# and also register "slash" as an alias

@main.command(name="/")
@click.pass_context
def slash_cmd(ctx: click.Context) -> None:
    """📋 快速唤出命令面板."""
    config = ctx.obj["config"]
    choice = _interactive_command_palette(config)
    if choice:
        _execute_palette_choice(ctx, choice)


@main.command()
@click.argument("agent_id")
@click.option("-p", "--prompt", default=None, help="Prompt to send")
@click.option("-r", "--role", default=None, help="Role label")
@click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
@click.pass_context
def run(ctx: click.Context, agent_id: str, prompt: str | None, role: str | None, no_attach: bool) -> None:
    """🚀 Run any configured agent by ID."""
    runner = AgentRunner(ctx.obj["config"])
    runner.run_agent(agent_id, ctx.obj["project_path"], prompt, attach=not no_attach, role=role)


# ═══════════════════════════════════════════════════════════════════
# Status dashboard — ag status
# ═══════════════════════════════════════════════════════════════════

@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """📊 Dashboard: all sessions, sandboxes and agents."""
    config = ctx.obj["config"]
    tmux_mgr = TmuxManager(config)
    sandbox_mgr = SandboxManager(config)

    # Recover orphaned sessions first, then cleanup stale ones
    recovered = recover_orphaned_sessions()
    active_sessions = tmux_mgr.list_sessions()
    active_names = [s["name"] for s in active_sessions]
    cleaned = cleanup_stale_sessions(active_names)
    if cleaned > 0:
        console.print(f"[dim]Cleaned up {cleaned} stale session(s)[/dim]")

    all_state = list_all_sessions()
    sandboxes = sandbox_mgr.list_sandboxes()

    # ── Summary panel ──
    n_sessions = len(active_sessions)
    n_sandboxes = len([sb for sb in sandboxes if "Up" in sb["status"]])
    n_agents = sum(len(s.get("windows", {})) for s in all_state.values())

    summary = (
        f"Sessions:  [cyan]{n_sessions}[/cyan]   "
        f"Sandboxes: [green]{n_sandboxes}[/green]   "
        f"Agents:    [yellow]{n_agents}[/yellow]"
    )
    console.print(Panel(summary, title="🧊 Agentbox Dashboard", border_style="cyan"))

    if not active_sessions and not sandboxes:
        console.print("\n[dim]No active sessions or sandboxes.[/dim]")
        console.print("[dim]Run [cyan]ag[/cyan] to pick an agent, or [cyan]ag claude[/cyan] to start.[/dim]")
        return

    # ── Sessions & Agents table ──
    if active_sessions:
        table = Table(title="🖥️  Sessions & Agents")
        table.add_column("Session", style="cyan", width=18)
        table.add_column("Project", style="green", width=15)
        table.add_column("Agent", style="yellow", width=10)
        table.add_column("Role", style="magenta", width=12)
        table.add_column("Container", style="blue", width=25)
        table.add_column("Status", style="bold", width=8)
        table.add_column("Prompt", style="dim", max_width=30)

        for s in active_sessions:
            name = s["name"]
            state = all_state.get(name, {})
            project = state.get("project_name", "")
            windows_state = state.get("windows", {})

            if not windows_state:
                table.add_row(name, project, "-", "-", "-", s["attached"], "")
                continue

            first = True
            for wname, winfo in windows_state.items():
                agent = winfo.get("agent", "-")
                role = winfo.get("role", agent)
                prompt_text = winfo.get("prompt", "")[:30]

                container = "-"
                for sb in sandboxes:
                    if agent in sb["name"] and "Up" in sb["status"]:
                        container = sb["name"]
                        break

                status_str = "🟢" if s["attached"] == "Yes" else "⚪"

                if first:
                    table.add_row(name, project, agent, role, container, status_str, prompt_text)
                    first = False
                else:
                    table.add_row("", "", agent, role, container, status_str, prompt_text)

        console.print(table)

    # ── Docker Sandboxes table ──
    if sandboxes:
        sb_table = Table(title="🐳 Sandboxes")
        sb_table.add_column("ID", style="dim", width=12)
        sb_table.add_column("Name", style="cyan", width=30)
        sb_table.add_column("Agent", style="yellow", width=10)
        sb_table.add_column("Image", style="green", width=25)
        sb_table.add_column("Status", style="bold")

        for sb in sandboxes:
            status_style = "green" if "Up" in sb["status"] else "red"
            sb_table.add_row(
                sb["container_id"], sb["name"], sb["agent"], sb["image"],
                f"[{status_style}]{sb['status']}[/{status_style}]",
            )

        console.print(sb_table)

    # ── Quick tips ──
    console.print("\n[dim]💡 [cyan]ag attach[/cyan]  [cyan]ag kill[/cyan]  [cyan]ag logs[/cyan]  [cyan]ag history[/cyan][/dim]")


# ═══════════════════════════════════════════════════════════════════
# Attach — ag attach [session_name]
# ═══════════════════════════════════════════════════════════════════

@main.command()
@click.argument("session_name", required=False)
@click.pass_context
def attach(ctx: click.Context, session_name: str | None) -> None:
    """🔄 Attach to a tmux session."""
    tmux_mgr = TmuxManager(ctx.obj["config"])

    if session_name:
        tmux_mgr.attach_session(session_name)
        return

    # No session name given — show picker
    active_sessions = tmux_mgr.list_sessions()

    if not active_sessions:
        console.print("[dim]No active sessions. Run [cyan]ag[/cyan] to start one.[/dim]")
        return

    if len(active_sessions) == 1:
        sname = active_sessions[0]["name"]
        console.print(f"[dim]Only one active session: {sname}[/dim]")
        tmux_mgr.attach_session(sname)
        return

    console.print("\n[bold]🔄 Active sessions — select one:[/bold]\n")
    for i, s in enumerate(active_sessions, 1):
        state = get_session_info(s["name"]) or {}
        project = state.get("project_name", "")
        windows = state.get("windows", {})
        agents = ", ".join(winfo.get("agent", "?") for winfo in windows.values()) if windows else "-"
        console.print(f"  [green]{i}[/green]. {s['name']}  project={project}  agents=[cyan]{agents}[/cyan]")

    console.print()
    choice = click.prompt("Select session", type=int, default=1)

    if 1 <= choice <= len(active_sessions):
        tmux_mgr.attach_session(active_sessions[choice - 1]["name"])
    else:
        console.print("[red]Invalid selection[/red]")


# ═══════════════════════════════════════════════════════════════════
# Kill — ag kill [session_name]   (kills session + sandbox)
# ═══════════════════════════════════════════════════════════════════

@main.command()
@click.argument("session_name", required=False)
@click.option("--all", "kill_all", is_flag=True, help="Kill all sessions and sandboxes")
@click.option("--rm", "remove", is_flag=True, help="Permanently delete sandbox containers (data lost!)")
@click.pass_context
def kill(ctx: click.Context, session_name: str | None, kill_all: bool, remove: bool) -> None:
    """🔥 Stop a session and its sandbox (preserves data by default).

    By default, only stops containers without deleting them.
    Use --rm to permanently delete sandbox data.
    """
    tmux_mgr = TmuxManager(ctx.obj["config"])
    sandbox_mgr = SandboxManager(ctx.obj["config"])

    if kill_all:
        if remove:
            sb_count = sandbox_mgr.kill_all_sandboxes()
        else:
            # Just stop, don't remove
            sandboxes = sandbox_mgr.list_sandboxes()
            sb_count = 0
            for sb in sandboxes:
                name = sb["name"].replace("agentbox-", "", 1)
                if sandbox_mgr.stop_sandbox(name):
                    sb_count += 1
        # Kill all agentbox tmux sessions
        active = tmux_mgr.list_sessions()
        for s in active:
            tmux_mgr.kill_session(s["name"])
            unregister_session(s["name"])
        action = "removed" if remove else "stopped"
        console.print(f"[green]✓ Killed {len(active)} session(s), {sb_count} sandbox(es) {action}[/green]")
        return

    if not session_name:
        # Show picker
        active = tmux_mgr.list_sessions()
        if not active:
            console.print("[dim]No active sessions to kill.[/dim]")
            return

        console.print("\n[bold]🔥 Stop which session?[/bold]\n")
        for i, s in enumerate(active, 1):
            state = get_session_info(s["name"]) or {}
            project = state.get("project_name", "")
            console.print(f"  [red]{i}[/red]. {s['name']}  project={project}")

        console.print()
        choice = click.prompt("Select session to stop", type=int, default=0)
        if 1 <= choice <= len(active):
            session_name = active[choice - 1]["name"]
        else:
            return

    # Stop the sandbox container(s) matching this session
    state = get_session_info(session_name) or {}
    windows = state.get("windows", {})
    for wname, winfo in windows.items():
        agent = winfo.get("agent", "")
        project_name = state.get("project_name", "")
        if agent and project_name:
            sandbox_name = f"{agent}-{project_name}"
            if remove:
                sandbox_mgr.kill_sandbox(sandbox_name)
            else:
                sandbox_mgr.stop_sandbox(sandbox_name)

    # Kill the tmux session
    tmux_mgr.kill_session(session_name)
    unregister_session(session_name)
    action = "removed" if remove else "stopped (sandbox preserved)"
    console.print(f"[green]✓ Session {session_name} {action}[/green]")


# ═══════════════════════════════════════════════════════════════════
# Logs — ag logs [sandbox_name]
# ═══════════════════════════════════════════════════════════════════

@main.command()
@click.argument("name", required=False)
@click.option("--tail", default=50, help="Number of lines to show")
@click.pass_context
def logs(ctx: click.Context, name: str | None, tail: int) -> None:
    """📜 View sandbox logs."""
    sandbox_mgr = SandboxManager(ctx.obj["config"])

    if not name:
        # Show available sandboxes
        sandboxes = sandbox_mgr.list_sandboxes()
        if not sandboxes:
            console.print("[dim]No sandboxes running.[/dim]")
            return
        console.print("[bold]📜 Which sandbox?[/bold]\n")
        for i, sb in enumerate(sandboxes, 1):
            console.print(f"  [green]{i}[/green]. {sb['name']}  agent={sb['agent']}  status={sb['status']}")
        console.print()
        choice = click.prompt("Select sandbox", type=int, default=1)
        if 1 <= choice <= len(sandboxes):
            name = sandboxes[choice - 1]["name"].replace("agentbox-", "", 1)
        else:
            return

    output = sandbox_mgr.get_sandbox_logs(name, tail)
    console.print(output)


# ═══════════════════════════════════════════════════════════════════
# History — ag history
# ═══════════════════════════════════════════════════════════════════

@main.command()
@click.option("--limit", "-n", default=20, help="Number of sessions to show")
@click.pass_context
def history(ctx: click.Context, limit: int) -> None:
    """📜 View session history and reconnect."""
    # Recover orphaned sessions before showing history
    recover_orphaned_sessions()

    from .state import load_state

    state = load_state()
    sessions = state.get("sessions", {})

    if not sessions:
        console.print("[dim]No session history yet. Run [cyan]ag[/cyan] to start your first session.[/dim]")
        return

    tmux_mgr = TmuxManager(ctx.obj["config"])
    active_sessions = tmux_mgr.list_sessions()
    active_names = {s["name"] for s in active_sessions}

    table = Table(title="📜 Session History")
    table.add_column("#", style="dim", width=4)
    table.add_column("Session", style="cyan")
    table.add_column("Project", style="green")
    table.add_column("Agents", style="yellow", max_width=40)
    table.add_column("Started", style="magenta", width=19)
    table.add_column("Status", style="bold")

    sorted_sessions = sorted(
        sessions.items(),
        key=lambda x: x[1].get("created_at", ""),
        reverse=True,
    )

    for i, (sname, sstate) in enumerate(sorted_sessions[:limit], 1):
        project = sstate.get("project_name", "")
        created = sstate.get("created_at", "")[:19]

        windows = sstate.get("windows", {})
        if windows:
            agent_parts = []
            for wname, winfo in windows.items():
                agent = winfo.get("agent", "?")
                role = winfo.get("role", agent)
                if role != agent:
                    agent_parts.append(f"{agent}→{role}")
                else:
                    agent_parts.append(agent)
            agents_str = ", ".join(agent_parts)
        else:
            agents_str = "-"

        if sname in active_names:
            status_str = "[green]🟢 active[/green]"
        else:
            status_str = "[dim]⚪ dead[/dim]"

        table.add_row(str(i), sname, project, agents_str, created, status_str)

    console.print(table)

    console.print("\n[dim]💡 [cyan]ag attach[/cyan] to reconnect · [cyan]ag kill[/cyan] to remove[/dim]")


# ═══════════════════════════════════════════════════════════════════
# Compose — ag compose agent:role agent:role
# ═══════════════════════════════════════════════════════════════════

@main.command()
@click.argument("specs", nargs=-1, required=True)
@click.option("-p", "--prompt", default=None, help="Shared prompt for all agents")
@click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
@click.pass_context
def compose(ctx: click.Context, specs: tuple[str, ...], prompt: str | None, no_attach: bool) -> None:
    """✨ Compose agents with roles.

    \b
    Examples:
      ag compose claude:coder codex:reviewer
      ag compose claude:architect aider:test-writer -p "Build auth"
    """
    composition = [_parse_agent_role(spec) for spec in specs]

    console.print("[dim]Composition:[/dim]")
    for comp in composition:
        console.print(f"  [cyan]{comp['agent']}[/cyan] as [yellow]{comp['role']}[/yellow]")

    runner = AgentRunner(ctx.obj["config"])
    runner.run_compose(composition, ctx.obj["project_path"], prompt, attach=not no_attach)


# ═══════════════════════════════════════════════════════════════════
# Team — ag team <team_id>
# ═══════════════════════════════════════════════════════════════════

@main.command()
@click.argument("team_id")
@click.option("-p", "--prompt", default=None, help="Prompt for all agents")
@click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
@click.pass_context
def team(ctx: click.Context, team_id: str, prompt: str | None, no_attach: bool) -> None:
    """👥 Run a team of agents."""
    runner = AgentRunner(ctx.obj["config"])
    runner.run_team(team_id, ctx.obj["project_path"], prompt, attach=not no_attach)


# ═══════════════════════════════════════════════════════════════════
# Compare — ag compare <agents...>
# ═══════════════════════════════════════════════════════════════════

@main.command()
@click.argument("agents", nargs=-1, required=True)
@click.option("-p", "--prompt", default=None, help="Prompt for all agents")
@click.pass_context
def compare(ctx: click.Context, agents: tuple[str, ...], prompt: str | None) -> None:
    """⚡ Compare agents side by side."""
    runner = AgentRunner(ctx.obj["config"])
    runner.run_compare(list(agents), ctx.obj["project_path"], prompt)


# ═══════════════════════════════════════════════════════════════════
# Ask — ag ask <question>
# ═══════════════════════════════════════════════════════════════════

@main.command()
@click.argument("question", nargs=-1, required=True)
@click.option("-a", "--agent", "agent_id", default="claude", help="Agent to use (default: claude)")
@click.option("-r", "--role", default=None, help="Role label")
@click.option("--test", "ask_tests", is_flag=True, help="Ask agent to run tests")
@click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
@click.pass_context
def ask(
    ctx: click.Context,
    question: tuple[str, ...],
    agent_id: str,
    role: str | None,
    ask_tests: bool,
    no_attach: bool,
) -> None:
    """💬 Ask an agent a question about your project."""
    prompt = " ".join(question)
    engine = WorkflowEngine(ctx.obj["config"])
    if ask_tests:
        test_cmd = engine.detect_test_command(ctx.obj["project_path"])
        if test_cmd:
            prompt = f"{prompt}\n\nAfter making changes, run `{test_cmd}` and report the result."
        else:
            prompt = f"{prompt}\n\nAfter making changes, identify and run the appropriate project tests."
    engine.ask(
        prompt=prompt,
        agent_id=agent_id,
        project_path=ctx.obj["project_path"],
        role=role,
        attach=not no_attach,
    )


# ═══════════════════════════════════════════════════════════════════
# Workflow shortcuts — ag diff / ag merge / ag review
# ═══════════════════════════════════════════════════════════════════

@main.command(name="diff")
@click.option("--patch", is_flag=True, help="Show the full diff after the summary")
@click.pass_context
def diff_cmd(ctx: click.Context, patch: bool) -> None:
    """📊 Git diff summary for the project."""
    engine = WorkflowEngine(ctx.obj["config"])
    if engine.print_diff_summary(ctx.obj["project_path"]) and patch:
        diff_text = engine.get_git_diff(ctx.obj["project_path"])
        console.print(diff_text or "[dim]No diff.[/dim]")


@main.command(name="merge")
@click.option("-m", "--message", default="Update project", help="Commit message")
@click.pass_context
def merge(ctx: click.Context, message: str) -> None:
    """✅ Stage all changes and commit."""
    engine = WorkflowEngine(ctx.obj["config"])
    engine.merge_changes(ctx.obj["project_path"], message)


@main.command(name="review")
@click.option("--no-test", is_flag=True, help="Skip running tests")
@click.option("--test-cmd", default=None, help="Test command to run")
@click.pass_context
def review(ctx: click.Context, no_test: bool, test_cmd: str | None) -> None:
    """🔍 Review git changes, run tests, then merge or discard."""
    engine = WorkflowEngine(ctx.obj["config"])
    engine.review(ctx.obj["project_path"], auto_test=not no_test, test_cmd=test_cmd)


@main.command(name="test")
@click.option("-c", "--command", "test_command", default=None, help="Test command to run")
@click.pass_context
def test_cmd(ctx: click.Context, test_command: str | None) -> None:
    """🧪 Run project tests."""
    engine = WorkflowEngine(ctx.obj["config"])
    results = engine.run_tests(ctx.obj["project_path"], test_command)
    engine.print_test_results(results)


# ═══════════════════════════════════════════════════════════════════
# List — ag list
# ═══════════════════════════════════════════════════════════════════

@main.command()
@click.option("--all", "show_all", is_flag=True, help="Show all details")
@click.pass_context
def list(ctx: click.Context, show_all: bool) -> None:
    """📋 List available agents and teams."""
    config = ctx.obj["config"]
    runner = AgentRunner(config)
    runner.list_available_agents()

    teams = list_teams(config)
    if teams:
        table = Table(title="Agent Teams")
        table.add_column("ID", style="cyan")
        table.add_column("Description", style="green")
        table.add_column("Agents", style="magenta")

        for t in teams:
            agent_list = ", ".join(
                f"{a.get('agent', '?')}→{a.get('role', a.get('agent', '?'))}"
                for a in t.get("agents", [])
            )
            table.add_row(t["id"], t.get("description", ""), agent_list)

        console.print()
        console.print(table)

    local = detect_local_agents()
    if local:
        console.print("\n[bold]Detected locally:[/bold]")
        for a in local:
            console.print(f"  ✅ [cyan]{a['id']}[/cyan] → {a['path']}")

    console.print("\n[dim]💡 [cyan]ag compose claude:coder codex:reviewer[/cyan] to compose[/dim]")


# ═══════════════════════════════════════════════════════════════════
# Init — ag init
# ═══════════════════════════════════════════════════════════════════

@main.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """🎉 Initialize agentbox in the current project."""
    project_path = ctx.obj["project_path"]
    project_name = Path(project_path).name

    agents_md = Path(project_path) / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(f"""# {project_name} - Agent Guide

This file helps AI agents understand your project.

## Project Overview

<!-- Describe your project here -->

## Architecture

<!-- Key directories and their purposes -->

## Development

<!-- How to build, test, and run -->

## Conventions

<!-- Coding style, commit messages, etc. -->
""")
        console.print("[green]✓ Created AGENTS.md[/green]")
    else:
        console.print("[dim]AGENTS.md already exists[/dim]")

    agentbox_dir = Path(project_path) / ".agentbox"
    agentbox_dir.mkdir(exist_ok=True)
    console.print("[green]✓ Created .agentbox/[/green]")

    gitignore = Path(project_path) / ".gitignore"
    try:
        gitignore_text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        ignored = any(line.strip() in {".agentbox", ".agentbox/"} for line in gitignore_text.splitlines())
        if ignored:
            console.print("[dim].agentbox/ already ignored[/dim]")
        else:
            prefix = "\n" if gitignore_text and not gitignore_text.endswith("\n") else ""
            spacer = "\n" if gitignore_text else ""
            with open(gitignore, "a", encoding="utf-8") as f:
                f.write(f"{prefix}{spacer}# Agentbox runtime\n.agentbox/\n")
            console.print("[green]✓ Added .agentbox/ to .gitignore[/green]")
    except OSError:
        console.print("[yellow]⚠ Could not update .gitignore[/yellow]")

    console.print(Panel(
        f"[bold green]🧊 Agentbox initialized for {project_name}![/bold green]\n\n"
        f"Next steps:\n"
        f"  [cyan]ag[/cyan]                  Pick an agent interactively\n"
        f"  [cyan]ag claude[/cyan]           Run Claude Code in sandbox\n"
        f"  [cyan]ag compose claude:coder codex:reviewer[/cyan]\n"
        f"  [cyan]ag status[/cyan]           View all sessions & sandboxes",
        title="🧊 Agentbox",
        border_style="cyan",
    ))


# ═══════════════════════════════════════════════════════════════════
# Pipeline — ag pipeline dev/research/compare/custom
# ═══════════════════════════════════════════════════════════════════

@main.group()
@click.pass_context
def pipeline(ctx: click.Context) -> None:
    """🧠 Orchestrated multi-agent pipelines."""
    pass


@pipeline.command(name="dev")
@click.argument("prompt")
@click.pass_context
def pipeline_dev(ctx: click.Context, prompt: str) -> None:
    """🔧 Plan → Code → Review."""
    orch = Orchestrator(ctx.obj["config"])
    pipe = dev_pipeline(prompt)
    orch.execute(pipe, ctx.obj["project_path"])


@pipeline.command(name="research")
@click.argument("topic")
@click.pass_context
def pipeline_research(ctx: click.Context, topic: str) -> None:
    """🔍 Research → Summarize → Critique."""
    orch = Orchestrator(ctx.obj["config"])
    pipe = research_pipeline(topic)
    orch.execute(pipe, ctx.obj["project_path"])


@pipeline.command(name="compare")
@click.argument("prompt")
@click.option("-a", "--agents", multiple=True, default=["claude", "codex"], help="Agents to compare")
@click.pass_context
def pipeline_compare(ctx: click.Context, prompt: str, agents: tuple[str, ...]) -> None:
    """⚡ Compare on multiple agents, then synthesize."""
    orch = Orchestrator(ctx.obj["config"])
    pipe = compare_pipeline(prompt, list(agents))
    orch.execute(pipe, ctx.obj["project_path"])


@pipeline.command(name="custom")
@click.argument("specs", nargs=-1, required=True)
@click.option("-p", "--prompt", default="Help me with this project", help="Initial prompt")
@click.pass_context
def pipeline_custom(ctx: click.Context, specs: tuple[str, ...], prompt: str) -> None:
    """🔧 Custom pipeline with AGENT:ROLE steps."""
    steps = []
    for spec in specs:
        parsed = _parse_agent_role(spec)
        step_id = parsed["role"]
        if steps:
            prev_id = steps[-1].step_id
            step_prompt = f"{{{{original_prompt}}}}\n\nPrevious step ({prev_id}) output:\n{{{prev_id}}}\n\nBased on the above, perform your role as {parsed['role']}."
        else:
            step_prompt = "{original_prompt}"

        steps.append(PipelineStep(
            agent=parsed["agent"],
            role=parsed["role"],
            step_id=step_id,
            prompt=step_prompt,
        ))

    pipe = Pipeline(
        name="custom-pipeline",
        description=f"Custom pipeline: {' → '.join(s.role for s in steps)}",
        steps=steps,
        shared_context={"original_prompt": prompt},
    )

    orch = Orchestrator(ctx.obj["config"])
    orch.execute(pipe, ctx.obj["project_path"])


@pipeline.command(name="list")
@click.pass_context
def pipeline_list(ctx: click.Context) -> None:
    """📋 List pipeline run history."""
    Orchestrator.print_pipeline_runs()


@pipeline.command(name="show")
@click.argument("run_id")
@click.pass_context
def pipeline_show(ctx: click.Context, run_id: str) -> None:
    """📊 Show details of a pipeline run."""
    import json as json_mod
    data = Orchestrator.get_pipeline_run(run_id)
    if not data:
        console.print(f"[red]Pipeline run not found: {run_id}[/red]")
        return

    console.print(Panel(
        f"[bold]{data.get('pipeline_name', '?')}[/bold]\n\n"
        f"Status: {data.get('status', '?')}\n"
        f"Session: {data.get('session_name', '?')}\n"
        f"Project: {data.get('project_path', '?')}\n"
        f"Started: {data.get('started_at', '?')}\n"
        f"Completed: {data.get('completed_at', 'running...')}",
        title=f"Pipeline Run: {run_id}",
        border_style="cyan",
    ))

    steps = data.get("steps", {})
    if steps:
        table = Table(title="Step Results")
        table.add_column("Step", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Output Preview", style="dim", max_width=60)

        for step_id, result in steps.items():
            status = result.get("status", "?")
            output = result.get("output", "")
            preview = output[:100] + "..." if len(output) > 100 else output
            status_icon = "✅" if status == "completed" else "❌"
            table.add_row(step_id, f"{status_icon} {status}", preview)

        console.print(table)


# ═══════════════════════════════════════════════════════════════════
# Config — ag config show/edit/reset
# ═══════════════════════════════════════════════════════════════════

@main.group()
@click.pass_context
def config(ctx: click.Context) -> None:
    """⚙️ Manage configuration."""
    pass


@config.command(name="show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Show current configuration."""
    import yaml
    cfg = ctx.obj["config"]
    console.print(yaml.dump(cfg, default_flow_style=False, allow_unicode=True))


@config.command(name="path")
@click.pass_context
def config_path(ctx: click.Context) -> None:
    """Show config file path."""
    console.print(str(DEFAULT_CONFIG_FILE))


@config.command(name="edit")
@click.pass_context
def config_edit(ctx: click.Context) -> None:
    """Open config in editor."""
    import shlex
    import subprocess

    editor = os.environ.get("EDITOR", "vim")
    editor_cmd = shlex.split(editor) or ["vim"]
    try:
        subprocess.run([*editor_cmd, str(DEFAULT_CONFIG_FILE)])
    except FileNotFoundError:
        console.print(f"[red]Editor not found:[/red] {editor}")


@config.command(name="reset")
@click.confirmation_option(prompt="Reset config to defaults?")
@click.pass_context
def config_reset(ctx: click.Context) -> None:
    """Reset configuration to defaults."""
    save_config({})
    from .config import DEFAULT_CONFIG
    save_config(DEFAULT_CONFIG)
    console.print("[green]✓ Configuration reset to defaults[/green]")


# ═══════════════════════════════════════════════════════════════════
# Sandbox — ag sandbox exec/build (less common, kept as subgroup)
# ═══════════════════════════════════════════════════════════════════

@main.group()
@click.pass_context
def sandbox(ctx: click.Context) -> None:
    """📦 Advanced sandbox management."""
    pass


@sandbox.command(name="exec")
@click.argument("name")
@click.argument("command", nargs=-1, required=True)
@click.option("-i", "--interactive", is_flag=True, help="Interactive mode")
@click.pass_context
def sandbox_exec(ctx: click.Context, name: str, command: tuple[str, ...], interactive: bool) -> None:
    """Execute command in a sandbox."""
    mgr = SandboxManager(ctx.obj["config"])
    mgr.exec_in_sandbox(name, list(command), interactive)


@sandbox.command(name="build")
@click.argument("agent_id")
@click.pass_context
def sandbox_build(ctx: click.Context, agent_id: str) -> None:
    """Build Docker image for an agent."""
    mgr = SandboxManager(ctx.obj["config"])
    mgr.build_agent_image(agent_id)


# ═══════════════════════════════════════════════════════════════════
# Stack — ag stack up/down/logs/status  (Docker Compose)
# ═══════════════════════════════════════════════════════════════════

@main.group(name="stack")
@click.pass_context
def stack_group(ctx: click.Context) -> None:
    """🐳 Docker Compose multi-agent stacks."""
    pass


@stack_group.command(name="up")
@click.argument("agents", nargs=-1, required=True)
@click.option("--foreground", is_flag=True, help="Run compose in the foreground")
@click.pass_context
def stack_up(ctx: click.Context, agents: tuple[str, ...], foreground: bool) -> None:
    """Start a Docker Compose stack for AGENTS."""
    mgr = DockerComposeManager(ctx.obj["config"])
    mgr.up(list(agents), ctx.obj["project_path"], detach=not foreground)


@stack_group.command(name="down")
@click.pass_context
def stack_down(ctx: click.Context) -> None:
    """Stop and remove the project's Docker Compose stack."""
    mgr = DockerComposeManager(ctx.obj["config"])
    mgr.down(ctx.obj["project_path"])


@stack_group.command(name="logs")
@click.option("--tail", default=100, help="Number of log lines per service")
@click.pass_context
def stack_logs(ctx: click.Context, tail: int) -> None:
    """Show Docker Compose stack logs."""
    mgr = DockerComposeManager(ctx.obj["config"])
    mgr.logs(ctx.obj["project_path"], tail=tail)


@stack_group.command(name="status")
@click.pass_context
def stack_status(ctx: click.Context) -> None:
    """Show Docker Compose stack status."""
    mgr = DockerComposeManager(ctx.obj["config"])
    mgr.status(ctx.obj["project_path"])


if __name__ == "__main__":
    main()
"""Agentbox CLI - main entry point."""

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
from .state import cleanup_stale_sessions, get_session_info, list_all_sessions, unregister_session
from .tmux_mgr import TmuxManager
from .workflow import WorkflowEngine

console = Console()


def _get_project_path(ctx: click.Context) -> str:
    """Get project path from context or current directory."""
    return ctx.obj.get("project_path", os.getcwd())


def _should_use_sandbox(ctx: click.Context, sandbox_flag: bool) -> bool:
    """Determine whether to use sandbox.

    If --sandbox is explicitly passed, always True.
    Otherwise, fall back to config sandbox.default_sandbox.
    """
    if sandbox_flag:
        return True
    config = ctx.obj.get("config", {})
    return bool(config.get("sandbox", {}).get("default_sandbox", False))


def _parse_agent_role(spec: str) -> dict[str, str]:
    """Parse an 'agent:role' specification.

    Formats:
      - 'claude'         → {"agent": "claude", "role": "claude"}
      - 'claude:planner' → {"agent": "claude", "role": "planner"}
      - 'codex:reviewer' → {"agent": "codex", "role": "reviewer"}
    """
    if ":" in spec:
        parts = spec.split(":", 1)
        return {"agent": parts[0], "role": parts[1]}
    return {"agent": spec, "role": spec}


@click.group()
@click.version_option(version=__version__, prog_name="agentbox")
@click.option("-p", "--project", "project_path", default=None, help="Project directory path")
@click.pass_context
def main(ctx: click.Context, project_path: str | None) -> None:
    """🧊 Agentbox - AI Agent orchestration CLI

    Run multiple coding agents in Docker sandboxes via tmux.

    \b
    Quick start:
      agentbox claude                Run Claude Code
      agentbox codex                 Run OpenAI Codex
      agentbox compose codex:planner claude:coder  Compose agents with roles
      agentbox team dev-team         Run a team of agents
      agentbox compare claude codex  Compare agents side by side
      agentbox list                  List available agents
      agentbox sandbox               Manage Docker sandboxes
    """
    ctx.ensure_object(dict)
    ctx.obj["project_path"] = project_path or os.getcwd()
    ctx.obj["config"] = load_config()


# ─── Agent commands ──────────────────────────────────────────────

@main.command(name="claude")
@click.option("-p", "--prompt", default=None, help="Prompt to send to Claude")
@click.option("-r", "--role", default=None, help="Role label (e.g., 'planner', 'coder')")
@click.option("--sandbox", is_flag=True, help="Run in Docker sandbox")
@click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
@click.pass_context
def run_claude(ctx: click.Context, prompt: str | None, role: str | None, sandbox: bool, no_attach: bool) -> None:
    """🤖 Run Claude Code."""
    runner = AgentRunner(ctx.obj["config"])
    runner.run_agent("claude", ctx.obj["project_path"], prompt, _should_use_sandbox(ctx, sandbox), attach=not no_attach, role=role)


@main.command(name="codex")
@click.option("-p", "--prompt", default=None, help="Prompt to send to Codex")
@click.option("-r", "--role", default=None, help="Role label (e.g., 'planner', 'coder')")
@click.option("--sandbox", is_flag=True, help="Run in Docker sandbox")
@click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
@click.pass_context
def run_codex(ctx: click.Context, prompt: str | None, role: str | None, sandbox: bool, no_attach: bool) -> None:
    """🤖 Run OpenAI Codex."""
    runner = AgentRunner(ctx.obj["config"])
    runner.run_agent("codex", ctx.obj["project_path"], prompt, _should_use_sandbox(ctx, sandbox), attach=not no_attach, role=role)


@main.command(name="aider")
@click.option("-p", "--prompt", default=None, help="Prompt to send to Aider")
@click.option("-r", "--role", default=None, help="Role label")
@click.option("--sandbox", is_flag=True, help="Run in Docker sandbox")
@click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
@click.pass_context
def run_aider(ctx: click.Context, prompt: str | None, role: str | None, sandbox: bool, no_attach: bool) -> None:
    """🤖 Run Aider."""
    runner = AgentRunner(ctx.obj["config"])
    runner.run_agent("aider", ctx.obj["project_path"], prompt, _should_use_sandbox(ctx, sandbox), attach=not no_attach, role=role)


@main.command(name="goose")
@click.option("-p", "--prompt", default=None, help="Prompt to send to Goose")
@click.option("-r", "--role", default=None, help="Role label")
@click.option("--sandbox", is_flag=True, help="Run in Docker sandbox")
@click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
@click.pass_context
def run_goose(ctx: click.Context, prompt: str | None, role: str | None, sandbox: bool, no_attach: bool) -> None:
    """🤖 Run Goose."""
    runner = AgentRunner(ctx.obj["config"])
    runner.run_agent("goose", ctx.obj["project_path"], prompt, _should_use_sandbox(ctx, sandbox), attach=not no_attach, role=role)


@main.command(name="opencode")
@click.option("-p", "--prompt", default=None, help="Prompt to send to OpenCode")
@click.option("-r", "--role", default=None, help="Role label")
@click.option("--sandbox", is_flag=True, help="Run in Docker sandbox")
@click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
@click.pass_context
def run_opencode(ctx: click.Context, prompt: str | None, role: str | None, sandbox: bool, no_attach: bool) -> None:
    """🤖 Run OpenCode."""
    runner = AgentRunner(ctx.obj["config"])
    runner.run_agent("opencode", ctx.obj["project_path"], prompt, _should_use_sandbox(ctx, sandbox), attach=not no_attach, role=role)


@main.command()
@click.argument("agent_id")
@click.option("-p", "--prompt", default=None, help="Prompt to send")
@click.option("-r", "--role", default=None, help="Role label (e.g., 'planner', 'coder')")
@click.option("--sandbox", is_flag=True, help="Run in Docker sandbox")
@click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
@click.pass_context
def run(ctx: click.Context, agent_id: str, prompt: str | None, role: str | None, sandbox: bool, no_attach: bool) -> None:
    """🚀 Run any configured agent by ID."""
    runner = AgentRunner(ctx.obj["config"])
    runner.run_agent(agent_id, ctx.obj["project_path"], prompt, _should_use_sandbox(ctx, sandbox), attach=not no_attach, role=role)


# ─── Compose command (dynamic agent:role composition) ────────────

@main.command()
@click.argument("specs", nargs=-1, required=True)
@click.option("-p", "--prompt", default=None, help="Shared prompt for all agents")
@click.option("--sandbox", is_flag=True, help="Run in Docker sandboxes")
@click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
@click.pass_context
def compose(ctx: click.Context, specs: tuple[str, ...], prompt: str | None, sandbox: bool, no_attach: bool) -> None:
    """✨ Compose agents with roles dynamically.

    \b
    Use AGENT:ROLE syntax to assign roles:
      agentbox compose codex:planner claude:coder codex:reviewer
      agentbox compose claude:architect aider:test-writer -p "Build auth module"
      agentbox compose codex:planner claude:coder --sandbox

    \b
    Without a role, the agent ID is used as the role:
      agentbox compose claude codex
    """
    composition = [_parse_agent_role(spec) for spec in specs]

    console.print(f"[dim]Composition:[/dim]")
    for comp in composition:
        console.print(f"  [cyan]{comp['agent']}[/cyan] as [yellow]{comp['role']}[/yellow]")

    runner = AgentRunner(ctx.obj["config"])
    runner.run_compose(composition, ctx.obj["project_path"], prompt, _should_use_sandbox(ctx, sandbox), attach=not no_attach)


# ─── Team commands ───────────────────────────────────────────────

@main.command()
@click.argument("team_id")
@click.option("-p", "--prompt", default=None, help="Prompt for all agents")
@click.option("--sandbox", is_flag=True, help="Run in Docker sandboxes")
@click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
@click.pass_context
def team(ctx: click.Context, team_id: str, prompt: str | None, sandbox: bool, no_attach: bool) -> None:
    """👥 Run a team of agents."""
    runner = AgentRunner(ctx.obj["config"])
    runner.run_team(team_id, ctx.obj["project_path"], prompt, _should_use_sandbox(ctx, sandbox), attach=not no_attach)


@main.command()
@click.argument("agents", nargs=-1, required=True)
@click.option("-p", "--prompt", default=None, help="Prompt for all agents")
@click.pass_context
def compare(ctx: click.Context, agents: tuple[str, ...], prompt: str | None) -> None:
    """⚡ Compare agents side by side."""
    runner = AgentRunner(ctx.obj["config"])
    runner.run_compare(list(agents), ctx.obj["project_path"], prompt)


# ─── Ask command (shortcut) ──────────────────────────────────────

@main.command()
@click.argument("question", nargs=-1, required=True)
@click.option("-a", "--agent", "agent_id", default="claude", help="Agent to use (default: claude)")
@click.option("-r", "--role", default=None, help="Role label")
@click.option("--sandbox", is_flag=True, help="Run in Docker sandbox")
@click.option("--test", "ask_tests", is_flag=True, help="Ask the agent to run the detected test command")
@click.option("--no-attach", is_flag=True, help="Don't attach to tmux session")
@click.pass_context
def ask(
    ctx: click.Context,
    question: tuple[str, ...],
    agent_id: str,
    role: str | None,
    sandbox: bool,
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
        use_sandbox=_should_use_sandbox(ctx, sandbox),
        role=role,
        attach=not no_attach,
    )


# ─── Workflow commands ───────────────────────────────────────────

@main.command(name="review")
@click.option("--no-test", is_flag=True, help="Skip running tests")
@click.option("--test-cmd", default=None, help="Test command to run")
@click.pass_context
def review(ctx: click.Context, no_test: bool, test_cmd: str | None) -> None:
    """🔍 Review current git changes, run tests, then merge or discard."""
    engine = WorkflowEngine(ctx.obj["config"])
    engine.review(ctx.obj["project_path"], auto_test=not no_test, test_cmd=test_cmd)


@main.command(name="diff")
@click.option("--patch", is_flag=True, help="Show the full diff after the summary")
@click.pass_context
def diff_cmd(ctx: click.Context, patch: bool) -> None:
    """📊 Show a git diff summary for the project."""
    engine = WorkflowEngine(ctx.obj["config"])
    if engine.print_diff_summary(ctx.obj["project_path"]) and patch:
        diff_text = engine.get_git_diff(ctx.obj["project_path"])
        console.print(diff_text or "[dim]No diff.[/dim]")


@main.command(name="merge")
@click.option("-m", "--message", default="Update project", help="Commit message")
@click.pass_context
def merge(ctx: click.Context, message: str) -> None:
    """✅ Stage all changes and commit them."""
    engine = WorkflowEngine(ctx.obj["config"])
    engine.merge_changes(ctx.obj["project_path"], message)


@main.command(name="test")
@click.option("-c", "--command", "test_command", default=None, help="Test command to run")
@click.pass_context
def test_cmd(ctx: click.Context, test_command: str | None) -> None:
    """🧪 Run project tests."""
    engine = WorkflowEngine(ctx.obj["config"])
    results = engine.run_tests(ctx.obj["project_path"], test_command)
    engine.print_test_results(results)


# ─── List commands ───────────────────────────────────────────────

@main.command()
@click.option("--all", "show_all", is_flag=True, help="Show all details")
@click.pass_context
def list(ctx: click.Context, show_all: bool) -> None:
    """📋 List available agents and teams."""
    config = ctx.obj["config"]
    runner = AgentRunner(config)
    runner.list_available_agents()

    # Show teams
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

    # Show local detection
    local = detect_local_agents()
    if local:
        console.print("\n[bold]Detected locally:[/bold]")
        for a in local:
            console.print(f"  ✅ [cyan]{a['id']}[/cyan] → {a['path']}")

    # Show compose examples
    console.print("\n[bold]Compose examples:[/bold]")
    console.print("  [dim]agentbox compose codex:planner claude:coder codex:reviewer[/dim]")
    console.print("  [dim]agentbox compose claude:architect aider:test-writer -p \"Build auth\"[/dim]")


# ─── Sandbox commands ────────────────────────────────────────────

@main.group()
@click.pass_context
def sandbox(ctx: click.Context) -> None:
    """📦 Manage Docker sandboxes."""
    pass


@sandbox.command(name="list")
@click.pass_context
def sandbox_list(ctx: click.Context) -> None:
    """List running sandboxes."""
    mgr = SandboxManager(ctx.obj["config"])
    mgr.print_sandboxes()


@sandbox.command(name="create")
@click.argument("agent_id")
@click.option("--image", default=None, help="Docker image to use")
@click.pass_context
def sandbox_create(ctx: click.Context, agent_id: str, image: str | None) -> None:
    """Create a sandbox for an agent."""
    mgr = SandboxManager(ctx.obj["config"])
    mgr.create_sandbox(
        name=f"{agent_id}-{Path(ctx.obj['project_path']).name}",
        agent_id=agent_id,
        project_path=ctx.obj["project_path"],
        image=image,
    )


@sandbox.command(name="kill")
@click.argument("name", required=False)
@click.option("--all", "kill_all", is_flag=True, help="Kill all sandboxes")
@click.pass_context
def sandbox_kill(ctx: click.Context, name: str | None, kill_all: bool) -> None:
    """Stop and remove sandbox(es)."""
    mgr = SandboxManager(ctx.obj["config"])
    if kill_all:
        count = mgr.kill_all_sandboxes()
        console.print(f"[green]Killed {count} sandbox(es)[/green]")
    elif name:
        mgr.kill_sandbox(name)
    else:
        console.print("[red]Specify a sandbox name or --all[/red]")


@sandbox.command(name="logs")
@click.argument("name")
@click.option("--tail", default=50, help="Number of lines to show")
@click.pass_context
def sandbox_logs(ctx: click.Context, name: str, tail: int) -> None:
    """View sandbox logs."""
    mgr = SandboxManager(ctx.obj["config"])
    logs = mgr.get_sandbox_logs(name, tail)
    console.print(logs)


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


# ─── Stack commands (Docker Compose) ─────────────────────────────

@main.group(name="stack")
@click.pass_context
def stack_group(ctx: click.Context) -> None:
    """🐳 Manage Docker Compose multi-agent stacks."""
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


# ─── Session commands ────────────────────────────────────────────

@main.group(name="session")
@click.pass_context
def session_group(ctx: click.Context) -> None:
    """🖥️ Manage tmux sessions."""
    pass


@session_group.command(name="list")
@click.pass_context
def session_list(ctx: click.Context) -> None:
    """List agentbox tmux sessions with details."""
    tmux_mgr = TmuxManager(ctx.obj["config"])

    # Cleanup stale sessions first
    active_sessions = tmux_mgr.list_sessions()
    active_names = [s["name"] for s in active_sessions]
    cleaned = cleanup_stale_sessions(active_names)
    if cleaned > 0:
        console.print(f"[dim]Cleaned up {cleaned} stale session(s)[/dim]")

    # Get tracked state
    all_state = list_all_sessions()

    if not active_sessions and not all_state:
        console.print("[dim]No agentbox sessions running.[/dim]")
        return

    # Combine tmux info with state
    table = Table(title="🧊 Agentbox Sessions")
    table.add_column("Session", style="cyan")
    table.add_column("Project", style="green")
    table.add_column("Path", style="dim", max_width=40)
    table.add_column("Windows", style="magenta")
    table.add_column("Attached", style="yellow")
    table.add_column("Agents", style="blue", max_width=60)

    for s in active_sessions:
        name = s["name"]
        state = all_state.get(name, {})
        project = state.get("project_name", "")
        path = state.get("project_path", "")

        # Build agents summary from state
        windows_state = state.get("windows", {})
        if windows_state:
            agent_parts = []
            for wname, winfo in windows_state.items():
                agent = winfo.get("agent", "?")
                role = winfo.get("role", agent)
                if role != agent:
                    agent_parts.append(f"{agent}→{role}")
                else:
                    agent_parts.append(agent)
            agents_str = ", ".join(agent_parts)
        else:
            agents_str = ""

        table.add_row(
            name,
            project,
            path,
            s["windows"],
            s["attached"],
            agents_str,
        )

    # Show sessions in state but not in tmux (stale)
    for sname, sstate in all_state.items():
        if sname not in active_names:
            table.add_row(
                sname,
                sstate.get("project_name", ""),
                sstate.get("project_path", ""),
                "?",
                "dead",
                "[dim](stale)[/dim]",
            )

    console.print(table)


@session_group.command(name="attach")
@click.argument("session_name")
@click.pass_context
def session_attach(ctx: click.Context, session_name: str) -> None:
    """Attach to a tmux session."""
    mgr = TmuxManager(ctx.obj["config"])
    mgr.attach_session(session_name)


@session_group.command(name="kill")
@click.argument("session_name")
@click.pass_context
def session_kill(ctx: click.Context, session_name: str) -> None:
    """Kill a tmux session."""
    mgr = TmuxManager(ctx.obj["config"])
    mgr.kill_session(session_name)
    unregister_session(session_name)


@session_group.command(name="windows")
@click.argument("session_name")
@click.pass_context
def session_windows(ctx: click.Context, session_name: str) -> None:
    """List windows in a session with agent details."""
    mgr = TmuxManager(ctx.obj["config"])
    windows = mgr.list_windows(session_name)

    if not windows:
        console.print(f"[dim]No windows in {session_name}[/dim]")
        return

    # Get state info for this session
    state_info = get_session_info(session_name)
    windows_state = state_info.get("windows", {}) if state_info else {}

    table = Table(title=f"🪟 Windows in {session_name}")
    table.add_column("#", style="dim")
    table.add_column("Window", style="cyan")
    table.add_column("Agent", style="green")
    table.add_column("Role", style="yellow")
    table.add_column("Mode", style="magenta")
    table.add_column("Active", style="bold")
    table.add_column("Prompt", style="dim", max_width=40)

    for w in windows:
        wname = w["name"]
        wstate = windows_state.get(wname, {})
        agent = wstate.get("agent", "-")
        role = wstate.get("role", "-")
        sandbox_mode = "🐳 sandbox" if wstate.get("sandbox") else "💻 local"
        prompt = wstate.get("prompt", "")

        table.add_row(
            w["index"],
            wname,
            agent,
            role,
            sandbox_mode,
            w["active"],
            prompt[:40] if prompt else "",
        )

    console.print(table)

    # Show session project info
    if state_info:
        console.print(f"\n[dim]Project: {state_info.get('project_name', '')} ({state_info.get('project_path', '')})[/dim]")


# ─── Pipeline commands (orchestrated multi-agent workflows) ──────

@main.group()
@click.pass_context
def pipeline(ctx: click.Context) -> None:
    """🧠 Run orchestrated multi-agent pipelines.

    Pipelines coordinate agents sequentially, passing outputs
    between steps. Each step can use a different agent with a
    different role and prompt template.

    \b
    Built-in pipelines:
      dev       Plan → Code → Review (codex:planner, claude:coder, codex:reviewer)
      research  Research → Summarize → Critique
      compare   Run same prompt on multiple agents, then synthesize
    """
    pass


@pipeline.command(name="dev")
@click.argument("prompt")
@click.pass_context
def pipeline_dev(ctx: click.Context, prompt: str) -> None:
    """🔧 Dev pipeline: Plan → Code → Review.

    codex:planner breaks down the task, claude:coder implements,
    codex:reviewer checks the code.
    """
    orch = Orchestrator(ctx.obj["config"])
    pipe = dev_pipeline(prompt)
    orch.execute(pipe, ctx.obj["project_path"])


@pipeline.command(name="research")
@click.argument("topic")
@click.pass_context
def pipeline_research(ctx: click.Context, topic: str) -> None:
    """🔍 Research pipeline: Research → Summarize → Critique."""
    orch = Orchestrator(ctx.obj["config"])
    pipe = research_pipeline(topic)
    orch.execute(pipe, ctx.obj["project_path"])


@pipeline.command(name="compare")
@click.argument("prompt")
@click.option("-a", "--agents", multiple=True, default=["claude", "codex"], help="Agents to compare")
@click.pass_context
def pipeline_compare(ctx: click.Context, prompt: str, agents: tuple[str, ...]) -> None:
    """⚡ Compare pipeline: Run on multiple agents, then synthesize."""
    orch = Orchestrator(ctx.obj["config"])
    pipe = compare_pipeline(prompt, list(agents))
    orch.execute(pipe, ctx.obj["project_path"])


@pipeline.command(name="custom")
@click.argument("specs", nargs=-1, required=True)
@click.option("-p", "--prompt", default="Help me with this project", help="Initial prompt")
@click.pass_context
def pipeline_custom(ctx: click.Context, specs: tuple[str, ...], prompt: str) -> None:
    """🔧 Custom pipeline with AGENT:ROLE steps.

    \b
    Steps run sequentially, each receiving previous step outputs:
      agentbox pipeline custom codex:planner claude:coder codex:reviewer -p "Build auth"
      agentbox pipeline custom claude:researcher claude:writer
    """
    steps = []
    for spec in specs:
        parsed = _parse_agent_role(spec)
        step_id = parsed["role"]
        # Build prompt template that references previous step output
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


# ─── Config commands ─────────────────────────────────────────────

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


# ─── Init command ────────────────────────────────────────────────

@main.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """🎉 Initialize agentbox in the current project."""
    project_path = ctx.obj["project_path"]
    project_name = Path(project_path).name

    # Create AGENTS.md if not exists
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
        console.print(f"[green]✓ Created AGENTS.md[/green]")
    else:
        console.print(f"[dim]AGENTS.md already exists[/dim]")

    # Create .agentbox directory
    agentbox_dir = Path(project_path) / ".agentbox"
    agentbox_dir.mkdir(exist_ok=True)
    console.print(f"[green]✓ Created .agentbox/[/green]")

    # Keep generated compose files, state, and logs out of project commits.
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
        f"  [cyan]agentbox list[/cyan]                     - See available agents\n"
        f"  [cyan]agentbox claude[/cyan]                   - Run Claude Code\n"
        f"  [cyan]agentbox codex -r planner[/cyan]         - Run Codex as planner\n"
        f"  [cyan]agentbox compose codex:planner claude:coder[/cyan] - Compose team\n"
        f"  [cyan]agentbox session list[/cyan]             - View running sessions",
        title="🧊 Agentbox",
        border_style="cyan",
    ))


if __name__ == "__main__":
    main()

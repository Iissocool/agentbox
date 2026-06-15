"""Agent command builder — single source of truth for how each agent CLI accepts prompts.

Every module that needs to construct an agent command string (runner, workflow,
orchestrator) should call `build_agent_command()` from here instead of
duplicating the logic.
"""

import shlex


# ── Agent prompt-style registry ────────────────────────────────────
# Each entry maps an agent_id to the flag it uses to receive a prompt.
#   "flag"  → the CLI flag (e.g. "-p", "--message")
#   "style" → "flagged" (flag + value) | "positional" (bare value)
_AGENT_PROMPT_STYLE: dict[str, dict[str, str]] = {
    "claude": {"flag": "-p",        "style": "flagged"},
    "aider":  {"flag": "--message", "style": "flagged"},
    # All unlisted agents default to positional style
}


def build_agent_command(agent_id: str, run_cmd: str, prompt: str | None = None) -> str:
    """Build a shell-safe agent command string.

    Parameters
    ----------
    agent_id:
        The agent identifier (e.g. ``"claude"``, ``"aider"``).
    run_cmd:
        The base run command from config (e.g. ``"claude"``, ``"aider"``).
    prompt:
        Optional prompt to pass.  When *None*, returns *run_cmd* unchanged.

    Returns
    -------
    str
        A ready-to-execute shell command with the prompt properly quoted.
    """
    if not prompt:
        return run_cmd

    quoted = shlex.quote(prompt)
    style = _AGENT_PROMPT_STYLE.get(agent_id, {})

    if style.get("style") == "flagged":
        return f"{run_cmd} {style['flag']} {quoted}"

    # Default: pass prompt as a positional argument
    return f"{run_cmd} {quoted}"


def build_docker_exec(container_name: str, command: str) -> str:
    """Wrap a command with ``docker exec -it`` for execution inside a sandbox.

    Parameters
    ----------
    container_name:
        The Docker container name (e.g. ``"agentbox-claude-myproject"``).
    command:
        The command to execute inside the container.

    Returns
    -------
    str
        A shell command like ``docker exec -it agentbox-claude-myproject claude -p 'hello'``
    """
    return f"docker exec -it {container_name} {command}"

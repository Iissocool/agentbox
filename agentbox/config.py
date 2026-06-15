"""Configuration management — YAML-based settings with deep-merge defaults.

Agentbox stores its configuration in ``~/.agentbox/config.yaml``.  On first
run a default configuration is written automatically.  User-provided values
are deep-merged on top of the defaults so that partial overrides work
correctly.
"""

import copy
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_DIR = Path.home() / ".agentbox"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"


# ── Default Configuration ──────────────────────────────────


DEFAULT_CONFIG = {
    "sandbox": {
        "base_image": "agentbox-base:latest",
        "mount_point": "/workspace",
        "network": "agentbox-net",
        "auto_remove": True,
        "memory_limit": "4g",
        "cpu_limit": 2,
    },
    "tmux": {
        "session_prefix": "ag-",
        "default_shell": "/bin/bash",
    },
    "agents": {
        "claude": {
            "name": "Claude Code",
            "cli": "claude",
            "type": "cli",
            "docker_image": "agentbox-claude:latest",
            "install_cmd": "npm install -g @anthropic-ai/claude-code",
            "run_cmd": "claude",
        },
        "codex": {
            "name": "OpenAI Codex",
            "cli": "codex",
            "type": "cli",
            "docker_image": "agentbox-codex:latest",
            "install_cmd": "npm install -g @openai/codex",
            "run_cmd": "codex",
        },
        "opencode": {
            "name": "OpenCode",
            "cli": "opencode",
            "type": "tui",
            "docker_image": "agentbox-opencode:latest",
            "install_cmd": "go install github.com/opencode-ai/opencode@latest",
            "run_cmd": "opencode",
        },
        "aider": {
            "name": "Aider",
            "cli": "aider",
            "type": "cli",
            "docker_image": "agentbox-aider:latest",
            "install_cmd": "pip install aider-chat",
            "run_cmd": "aider",
        },
        "goose": {
            "name": "Goose",
            "cli": "goose",
            "type": "cli",
            "docker_image": "agentbox-goose:latest",
            "install_cmd": "curl -fsSL https://github.com/block/goose/releases/latest/download/install.sh | sh",
            "run_cmd": "goose session",
        },
        "copilot": {
            "name": "GitHub Copilot CLI",
            "cli": "github-copilot-cli",
            "type": "cli",
            "docker_image": "agentbox-copilot:latest",
            "install_cmd": "npm install -g @githubnext/github-copilot-cli",
            "run_cmd": "github-copilot-cli",
        },
    },
    "teams": {
        "dev-team": {
            "description": "Full development team",
            "agents": [
                {"role": "planner", "agent": "claude", "prompt": "You are the planner. Break down tasks into steps."},
                {"role": "coder", "agent": "codex", "prompt": "You are the coder. Write clean, tested code."},
                {"role": "reviewer", "agent": "claude", "prompt": "You are the reviewer. Check code quality and suggest fixes."},
            ],
        },
        "compare": {
            "description": "Run same task on multiple agents for comparison",
            "agents": [
                {"role": "claude", "agent": "claude"},
                {"role": "codex", "agent": "codex"},
            ],
        },
    },
}


# ── Public API ─────────────────────────────────────────────


def ensure_config_dir() -> Path:
    """Ensure config directory exists."""
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_CONFIG_DIR


def load_config() -> dict[str, Any]:
    """Load configuration from file, creating default if not exists."""
    if not DEFAULT_CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)

    with open(DEFAULT_CONFIG_FILE, "r") as f:
        config = yaml.safe_load(f)

    # Deep copy defaults so _deep_merge doesn't pollute DEFAULT_CONFIG
    merged = copy.deepcopy(DEFAULT_CONFIG)
    _deep_merge(merged, config)

    # Migrate old base_image value
    if merged.get("sandbox", {}).get("base_image") == "ubuntu:22.04":
        merged["sandbox"]["base_image"] = "agentbox-base:latest"

    return merged


# ── Persistence ────────────────────────────────────────────


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to file."""
    ensure_config_dir()
    with open(DEFAULT_CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


# ── Config Accessors ───────────────────────────────────────


def get_agent_config(config: dict[str, Any], agent_name: str) -> dict[str, Any] | None:
    """Get a specific agent's configuration."""
    return config.get("agents", {}).get(agent_name)


def get_team_config(config: dict[str, Any], team_name: str) -> dict[str, Any] | None:
    """Get a specific team's configuration."""
    return config.get("teams", {}).get(team_name)


def list_agents(config: dict[str, Any]) -> list[dict[str, Any]]:
    """List all configured agents."""
    agents = []
    for key, val in config.get("agents", {}).items():
        agents.append({"id": key, **val})
    return agents


def list_teams(config: dict[str, Any]) -> list[dict[str, Any]]:
    """List all configured teams."""
    teams = []
    for key, val in config.get("teams", {}).items():
        teams.append({"id": key, **val})
    return teams


def detect_local_agents() -> list[dict[str, str]]:
    """Detect which agents are installed locally."""
    import shutil

    known_agents = {
        "claude": "claude",
        "codex": "codex",
        "aider": "aider",
        "goose": "goose",
        "opencode": "opencode",
        "github-copilot-cli": "copilot",
    }

    found = []
    for cli_name, agent_id in known_agents.items():
        path = shutil.which(cli_name)
        if path:
            found.append({"id": agent_id, "cli": cli_name, "path": path})

    return found


# ── Internal Helpers ───────────────────────────────────────


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


# ── Skills & Contracts ──────────────────────────────────


def load_skills_registry() -> dict[str, dict]:
    """Load all skill definitions into a name->skill registry."""
    from .skills import load_all_skills
    return {s["name"]: s for s in load_all_skills()}


def load_contracts_registry() -> dict[str, dict]:
    """Load all agent contracts into a name->contract registry."""
    from .agents.contracts import load_all_contracts
    result = {}
    for c in load_all_contracts():
        agent = c.get("agent", {})
        name = agent.get("name", "")
        if name:
            result[name] = c
    return result

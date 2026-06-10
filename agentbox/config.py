"""Configuration management for agentbox."""

import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_DIR = Path.home() / ".agentbox"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"


DEFAULT_CONFIG = {
    "sandbox": {
        "base_image": "ubuntu:22.04",
        "mount_point": "/workspace",
        "network": "agentbox-net",
        "auto_remove": True,
        "memory_limit": "4g",
        "cpu_limit": 2,
        "default_local": False,
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
            "env_vars": ["ANTHROPIC_API_KEY"],
            "install_cmd": "npm install -g @anthropic-ai/claude-code",
            "run_cmd": "claude",
        },
        "codex": {
            "name": "OpenAI Codex",
            "cli": "codex",
            "type": "cli",
            "docker_image": "agentbox-codex:latest",
            "env_vars": ["OPENAI_API_KEY"],
            "install_cmd": "npm install -g @openai/codex",
            "run_cmd": "codex",
        },
        "opencode": {
            "name": "OpenCode",
            "cli": "opencode",
            "type": "tui",
            "docker_image": "agentbox-opencode:latest",
            "env_vars": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
            "install_cmd": "go install github.com/opencode-ai/opencode@latest",
            "run_cmd": "opencode",
        },
        "aider": {
            "name": "Aider",
            "cli": "aider",
            "type": "cli",
            "docker_image": "agentbox-aider:latest",
            "env_vars": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
            "install_cmd": "pip install aider-chat",
            "run_cmd": "aider",
        },
        "goose": {
            "name": "Goose",
            "cli": "goose",
            "type": "cli",
            "docker_image": "agentbox-goose:latest",
            "env_vars": ["GOOSE_API_KEY"],
            "install_cmd": "curl -fsSL https://github.com/block/goose/releases/latest/download/install.sh | sh",
            "run_cmd": "goose session",
        },
        "copilot": {
            "name": "GitHub Copilot CLI",
            "cli": "github-copilot-cli",
            "type": "cli",
            "docker_image": "agentbox-copilot:latest",
            "env_vars": ["GITHUB_TOKEN"],
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


def ensure_config_dir() -> Path:
    """Ensure config directory exists."""
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_CONFIG_DIR


def load_config() -> dict[str, Any]:
    """Load configuration from file, creating default if not exists."""
    if not DEFAULT_CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    with open(DEFAULT_CONFIG_FILE, "r") as f:
        config = yaml.safe_load(f)

    # Merge with defaults for any missing keys
    merged = DEFAULT_CONFIG.copy()
    _deep_merge(merged, config)
    return merged


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to file."""
    ensure_config_dir()
    with open(DEFAULT_CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


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


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base
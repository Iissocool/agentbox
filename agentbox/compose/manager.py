"""Docker Compose manager for multi-agent stacks."""

import os
import subprocess
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.panel import Panel

console = Console()


class DockerComposeManager:
    """Generates and controls a Docker Compose stack for multiple agents."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.sandbox_config = config.get("sandbox", {})
        self.network_name = self.sandbox_config.get("network", "agentbox-net")

    def generate_compose(self, agents: list[str], project_path: str | Path) -> Path:
        """Generate a compose file for the requested agents.

        Environment variables are written to a ``.env`` file inside
        ``.agentbox/`` so that secrets never appear in the compose YAML
        itself.  The compose file references the env file via ``env_file``.
        """
        path = Path(project_path).expanduser().resolve()
        agentbox_dir = path / ".agentbox"
        agentbox_dir.mkdir(exist_ok=True)
        compose_file = agentbox_dir / "docker-compose.yml"
        env_file = agentbox_dir / ".env"
        mount_point = self.sandbox_config.get("mount_point", "/workspace")

        # Collect env var names per service (values go to .env, not compose)
        services: dict[str, Any] = {}
        env_lines: list[str] = []
        seen: dict[str, int] = {}
        for agent_id in agents:
            agent_config = self.config.get("agents", {}).get(agent_id)
            if not agent_config:
                console.print(f"[yellow]Skipping unknown agent: {agent_id}[/yellow]")
                continue

            seen[agent_id] = seen.get(agent_id, 0) + 1
            service_name = agent_id if seen[agent_id] == 1 else f"{agent_id}-{seen[agent_id]}"
            env_var_names = agent_config.get("env_vars", [])
            # Write actual values to .env file (git-ignored)
            for var_name in env_var_names:
                value = os.environ.get(var_name)
                if value is not None:
                    env_lines.append(f"{var_name}={_shell_quote(value)}")
            services[service_name] = {
                "image": agent_config.get("docker_image", self.sandbox_config.get("base_image", "ubuntu:22.04")),
                "container_name": f"agentbox-{path.name}-{service_name}",
                "working_dir": mount_point,
                "volumes": [f"{path}:{mount_point}"],
                "env_file": [str(env_file)],
                "environment": env_var_names,  # pass-through list (names only)
                "command": "tail -f /dev/null",
                "labels": [
                    "agentbox=true",
                    f"agentbox.agent={agent_id}",
                    f"agentbox.project={path.name}",
                ],
                "networks": [self.network_name],
            }

        if not services:
            raise ValueError("No valid agents were provided.")

        # Write .env with secrets (permissions 600)
        if env_lines:
            env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
            env_file.chmod(0o600)

        data = {
            "services": services,
            "networks": {
                self.network_name: {
                    "name": self.network_name,
                    "external": True,
                }
            },
        }
        compose_file.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")

        # Ensure .agentbox/ is in project .gitignore
        _ensure_gitignore(path)

        return compose_file

    def up(self, agents: list[str], project_path: str | Path, detach: bool = True) -> bool:
        """Create and start the compose stack."""
        try:
            compose_file = self.generate_compose(agents, project_path)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return False
        if not self._ensure_network():
            return False
        cmd = [*self._compose_cmd(), "-f", str(compose_file), "up"]
        if detach:
            cmd.append("-d")
        return self._run(cmd, "Stack started", compose_file)

    def down(self, project_path: str | Path) -> bool:
        """Stop and remove the compose stack."""
        compose_file = self._compose_file(project_path)
        if not compose_file.exists():
            console.print(f"[yellow]Compose file not found:[/yellow] {compose_file}")
            return False
        return self._run([*self._compose_cmd(), "-f", str(compose_file), "down"], "Stack stopped", compose_file)

    def logs(self, project_path: str | Path, tail: int = 100) -> bool:
        """Print compose service logs."""
        compose_file = self._compose_file(project_path)
        if not compose_file.exists():
            console.print(f"[yellow]Compose file not found:[/yellow] {compose_file}")
            return False
        return self._run(
            [*self._compose_cmd(), "-f", str(compose_file), "logs", "--tail", str(tail)],
            "Stack logs",
            compose_file,
            passthrough=True,
        )

    def status(self, project_path: str | Path) -> bool:
        """Print compose service status."""
        compose_file = self._compose_file(project_path)
        if not compose_file.exists():
            console.print(f"[yellow]Compose file not found:[/yellow] {compose_file}")
            return False
        return self._run(
            [*self._compose_cmd(), "-f", str(compose_file), "ps"],
            "Stack status",
            compose_file,
            passthrough=True,
        )

    def _compose_file(self, project_path: str | Path) -> Path:
        return Path(project_path).expanduser().resolve() / ".agentbox" / "docker-compose.yml"

    def _compose_cmd(self) -> list[str]:
        try:
            result = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
        except FileNotFoundError:
            return ["docker", "compose"]
        if result.returncode == 0:
            return ["docker", "compose"]
        return ["docker-compose"]

    def _ensure_network(self) -> bool:
        try:
            result = subprocess.run(
                ["docker", "network", "inspect", self.network_name],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return True
            create = subprocess.run(
                ["docker", "network", "create", self.network_name],
                capture_output=True,
                text=True,
            )
            if create.returncode == 0:
                return True
            console.print(Panel(
                create.stderr.strip() or "Failed to create Docker network.",
                title="Docker Network Error",
                border_style="red",
            ))
            return False
        except FileNotFoundError:
            console.print("[red]Docker is not available.[/red]")
            return False

    def _run(
        self,
        cmd: list[str],
        success_title: str,
        compose_file: Path,
        passthrough: bool = False,
    ) -> bool:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            console.print("[red]Docker Compose is not available.[/red]")
            return False

        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            console.print(Panel(output or "Command failed", title="Docker Compose Error", border_style="red"))
            return False

        if passthrough:
            console.print(output or "[dim]No output.[/dim]")
        else:
            console.print(Panel(
                f"Compose file: [cyan]{compose_file}[/cyan]\n\n{output}",
                title=success_title,
                border_style="green",
            ))
        return True


def _shell_quote(value: str) -> str:
    """Quote a value for a .env file, wrapping in single quotes if it contains
    spaces, special characters, or is empty.  Single quotes inside the value
    are escaped as ``'\\'``."""
    if not value:
        return "''"
    # Only quote if needed
    if any(c in value for c in " \t\n\"'#$&|;<>`"):
        escaped = value.replace("'", "'\\''")
        return f"'{escaped}'"
    return value


def _ensure_gitignore(project_path: Path) -> None:
    """Add ``.agentbox/`` to the project's ``.gitignore`` if not already present."""
    gitignore = project_path / ".gitignore"
    entry = ".agentbox/"
    try:
        if gitignore.exists():
            content = gitignore.read_text(encoding="utf-8")
            if entry in content.splitlines():
                return
            # Add a blank line + entry if file doesn't end with newline
            if content and not content.endswith("\n"):
                content += "\n"
            content += entry + "\n"
        else:
            content = entry + "\n"
        gitignore.write_text(content, encoding="utf-8")
    except OSError:
        # Non-critical — don't block compose generation
        pass

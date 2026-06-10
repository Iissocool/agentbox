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
        """Generate a compose file for the requested agents."""
        path = Path(project_path).expanduser().resolve()
        agentbox_dir = path / ".agentbox"
        agentbox_dir.mkdir(exist_ok=True)
        compose_file = agentbox_dir / "docker-compose.yml"
        mount_point = self.sandbox_config.get("mount_point", "/workspace")

        services: dict[str, Any] = {}
        seen: dict[str, int] = {}
        for agent_id in agents:
            agent_config = self.config.get("agents", {}).get(agent_id)
            if not agent_config:
                console.print(f"[yellow]Skipping unknown agent: {agent_id}[/yellow]")
                continue

            seen[agent_id] = seen.get(agent_id, 0) + 1
            service_name = agent_id if seen[agent_id] == 1 else f"{agent_id}-{seen[agent_id]}"
            env = {
                var_name: os.environ[var_name]
                for var_name in agent_config.get("env_vars", [])
                if os.environ.get(var_name)
            }
            services[service_name] = {
                "image": agent_config.get("docker_image", self.sandbox_config.get("base_image", "ubuntu:22.04")),
                "container_name": f"agentbox-{path.name}-{service_name}",
                "working_dir": mount_point,
                "volumes": [f"{path}:{mount_point}"],
                "environment": env,
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

"""Docker Compose orchestration — generating, launching, and managing
multi-agent container stacks for Agentbox projects."""

import subprocess
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.panel import Panel

console = Console()


# ── Compose Manager ────────────────────────────────


class DockerComposeManager:
    """Generates and controls a Docker Compose stack for multiple agents.

    Each agent is materialized as a long-running service inside a shared
    Docker network.  Secrets and environment values are kept out of the
    compose YAML itself and written to a companion ``.env`` file instead.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.sandbox_config = config.get("sandbox", {})
        self.network_name = self.sandbox_config.get("network", "agentbox-net")
        self.command_timeout = int(self.sandbox_config.get("compose_timeout", 120))
        self._compose_command: list[str] | None = None

    # ── Public API ────────────────────────────────────

    def generate_compose(self, agents: list[str], project_path: str | Path) -> Path:
        """Generate a compose file for the requested agents.

        Each agent becomes a service running ``tail -f /dev/null`` so that
        the user can ``docker exec`` into it.  The project directory is
        bind-mounted as the working directory.

        Args:
            agents: Agent identifiers to include as services.
            project_path: Root directory of the project to mount.

        Returns:
            Path to the generated ``docker-compose.yml`` file.

        Raises:
            ValueError: If none of the requested agents are recognized.
        """
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

            service = {
                "image": agent_config.get(
                    "docker_image",
                    self.sandbox_config.get("base_image", "agentbox-base:latest"),
                ),
                "container_name": f"agentbox-{path.name}-{service_name}",
                "working_dir": mount_point,
                "volumes": [f"{path}:{mount_point}"],
                "command": "tail -f /dev/null",
                "labels": [
                    "agentbox=true",
                    f"agentbox.agent={agent_id}",
                    f"agentbox.project={path.name}",
                ],
                "networks": [self.network_name],
            }
            services[service_name] = service

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

        # Ensure .agentbox/ is in project .gitignore
        _ensure_gitignore(path)

        return compose_file

    def up(self, agents: list[str], project_path: str | Path, detach: bool = True) -> bool:
        """Create and start the compose stack.

        Args:
            agents: Agent identifiers to include as services.
            project_path: Root directory of the project to mount.
            detach: When True, run the stack in the background.

        Returns:
            True if the stack started successfully, False otherwise.
        """
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

        return self._run(cmd, "Stack started", compose_file, timeout=None, stream=True)

    def down(self, project_path: str | Path) -> bool:
        """Stop and remove the compose stack.

        Args:
            project_path: Root directory of the project whose stack to tear down.

        Returns:
            True if the stack was stopped successfully, False otherwise.
        """
        compose_file = self._compose_file(project_path)
        if not compose_file.exists():
            console.print(f"[yellow]Compose file not found:[/yellow] {compose_file}")
            return False

        return self._run(
            [*self._compose_cmd(), "-f", str(compose_file), "down"],
            "Stack stopped",
            compose_file,
        )

    def logs(self, project_path: str | Path, tail: int = 100) -> bool:
        """Print compose service logs.

        Args:
            project_path: Root directory of the project whose logs to retrieve.
            tail: Number of most-recent log lines to display per service.

        Returns:
            True if logs were retrieved successfully, False otherwise.
        """
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
        """Print compose service status.

        Args:
            project_path: Root directory of the project whose status to inspect.

        Returns:
            True if status was retrieved successfully, False otherwise.
        """
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

    # ── Private Helpers ───────────────────────────────

    def _compose_file(self, project_path: str | Path) -> Path:
        """Resolve the path to the project's compose file.

        Args:
            project_path: Root directory of the project.

        Returns:
            Absolute path to ``.agentbox/docker-compose.yml``.
        """
        return Path(project_path).expanduser().resolve() / ".agentbox" / "docker-compose.yml"

    def _compose_cmd(self) -> list[str]:
        """Detect and cache the correct Docker Compose invocation.

        Prefers the ``docker compose`` plugin syntax but falls back to
        the standalone ``docker-compose`` binary when necessary.

        Returns:
            A list of command components (e.g. ``["docker", "compose"]``).
        """
        if self._compose_command:
            return self._compose_command

        try:
            result = subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            self._compose_command = ["docker", "compose"]
            return self._compose_command
        except subprocess.TimeoutExpired:
            self._compose_command = ["docker-compose"]
            return self._compose_command

        if result.returncode == 0:
            self._compose_command = ["docker", "compose"]
        else:
            self._compose_command = ["docker-compose"]

        return self._compose_command

    def _ensure_network(self) -> bool:
        """Verify that the shared Docker network exists, creating it if needed.

        Returns:
            True if the network is available, False on failure.
        """
        try:
            result = subprocess.run(
                ["docker", "network", "inspect", self.network_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return True

            create = subprocess.run(
                ["docker", "network", "create", self.network_name],
                capture_output=True,
                text=True,
                timeout=30,
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
        except subprocess.TimeoutExpired:
            console.print("[red]Timed out while preparing Docker network.[/red]")
            return False

    def _run(
        self,
        cmd: list[str],
        success_title: str,
        compose_file: Path,
        passthrough: bool = False,
        timeout: int | None = None,
        stream: bool = False,
    ) -> bool:
        """Execute a Docker Compose command and report the outcome.

        Args:
            cmd: Full command list to execute.
            success_title: Title for the Rich panel on success.
            compose_file: Path to the compose file (used for working directory).
            passthrough: When True, print raw output instead of a panel.
            timeout: Override the default command timeout in seconds.
            stream: When True, stream output live instead of capturing it.

        Returns:
            True if the command exited cleanly, False otherwise.
        """
        cwd = compose_file.parent.parent

        try:
            if stream:
                result = subprocess.run(cmd, cwd=str(cwd), timeout=timeout)
            else:
                result = subprocess.run(
                    cmd,
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    timeout=self.command_timeout if timeout is None else timeout,
                )
        except FileNotFoundError:
            console.print("[red]Docker Compose is not available.[/red]")
            return False
        except subprocess.TimeoutExpired:
            console.print(Panel(
                f"Command timed out after {self.command_timeout} seconds.",
                title="Docker Compose Timeout",
                border_style="red",
            ))
            return False

        output = (
            (getattr(result, "stdout", "") or "")
            + (getattr(result, "stderr", "") or "")
        ).strip()

        if result.returncode != 0:
            console.print(Panel(
                output or "Command failed",
                title="Docker Compose Error",
                border_style="red",
            ))
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


# ── Module Utilities ────────────────────────────────


def _ensure_gitignore(project_path: Path) -> None:
    """Add ``.agentbox/`` to the project's ``.gitignore`` if not already present.

    Args:
        project_path: Root directory of the project.
    """
    gitignore = project_path / ".gitignore"
    entry = ".agentbox/"

    try:
        if gitignore.exists():
            content = gitignore.read_text(encoding="utf-8")
            if any(line.strip() in {".agentbox", ".agentbox/"} for line in content.splitlines()):
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

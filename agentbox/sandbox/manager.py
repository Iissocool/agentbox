"""Docker sandbox manager - create, manage, and destroy isolated agent environments."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()


class SandboxManager:
    """Manages Docker-based sandboxes for running AI agents in isolation."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.sandbox_config = config.get("sandbox", {})
        self.network_name = self.sandbox_config.get("network", "agentbox-net")

    def _docker_available(self) -> bool:
        """Check if Docker is available and running."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _image_exists(self, image_name: str) -> bool:
        """Check if a Docker image exists locally."""
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", image_name],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def ensure_network(self) -> None:
        """Ensure the Docker network exists."""
        try:
            result = subprocess.run(
                ["docker", "network", "inspect", self.network_name],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                console.print(f"[dim]Creating Docker network: {self.network_name}[/dim]")
                subprocess.run(
                    ["docker", "network", "create", self.network_name],
                    capture_output=True,
                    check=True,
                )
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Failed to create network: {e}[/red]")

    def create_sandbox(
        self,
        name: str,
        agent_id: str,
        project_path: str | None = None,
        image: str | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Create a new sandbox container for an agent.

        Returns dict with container_id, name, status, needs_install.
        """
        if not self._docker_available():
            console.print("[red]Docker is not available or not running![/red]")
            console.print("[dim]Start Docker Desktop or Docker daemon first.[/dim]")
            return {}

        self.ensure_network()

        agent_config = self.config.get("agents", {}).get(agent_id, {})
        docker_image = image or agent_config.get("docker_image", self.sandbox_config.get("base_image", "ubuntu:22.04"))
        mount_point = self.sandbox_config.get("mount_point", "/workspace")
        memory_limit = self.sandbox_config.get("memory_limit", "4g")
        cpu_limit = self.sandbox_config.get("cpu_limit", 2)

        # Check if the agent-specific image exists, fall back to base image
        needs_install = False
        if not self._image_exists(docker_image):
            fallback_image = self.sandbox_config.get("base_image", "ubuntu:22.04")
            if docker_image != fallback_image:
                console.print(f"[yellow]⚠ Image '{docker_image}' not found locally.[/yellow]")
                console.print(f"[dim]Falling back to base image: {fallback_image}[/dim]")
                console.print(f"[dim]Agent will be installed inside the container after startup.[/dim]")
                docker_image = fallback_image
                needs_install = True
            else:
                # Even the base image doesn't exist - try to pull it
                console.print(f"[yellow]⚠ Base image '{docker_image}' not found locally, pulling...[/yellow]")
                self._pull_image(docker_image)

        container_name = f"agentbox-{name}"

        # Remove existing container with same name if any
        try:
            subprocess.run(["docker", "rm", "-f", container_name],
                          capture_output=True, check=False)
        except Exception:
            pass

        # Build docker run command
        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", self.network_name,
            "--label", "agentbox=true",
            "--label", f"agentbox.agent={agent_id}",
            f"--memory={memory_limit}",
            f"--cpus={cpu_limit}",
            "-w", mount_point,
        ]

        # Mount project directory
        if project_path:
            abs_path = str(Path(project_path).resolve())
            cmd.extend(["-v", f"{abs_path}:{mount_point}"])

        # Pass environment variables from host
        agent_env_vars = agent_config.get("env_vars", [])
        all_env = env_vars or {}
        for var_name in agent_env_vars:
            val = all_env.get(var_name) or os.environ.get(var_name, "")
            if val:
                cmd.extend(["-e", f"{var_name}={val}"])

        cmd.append(docker_image)

        # Keep container alive
        cmd.extend(["tail", "-f", "/dev/null"])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            container_id = result.stdout.strip()[:12]
            console.print(f"[green]✓ Sandbox created:[/green] {container_name} ({container_id})")

            # Install agent inside container if needed
            if needs_install:
                install_cmd = agent_config.get("install_cmd", "")
                if install_cmd:
                    console.print(f"[dim]Installing {agent_id} inside sandbox (this may take a while)...[/dim]")
                    # First install prerequisites
                    self.exec_in_sandbox(name, ["bash", "-c",
                        "apt-get update && apt-get install -y curl git build-essential 2>/dev/null || true"])
                    # Install Node.js if needed (for npm-based agents)
                    if "npm" in install_cmd:
                        self.exec_in_sandbox(name, ["bash", "-c",
                            "curl -fsSL https://deb.nodesource.com/setup_22.x | bash - 2>/dev/null && "
                            "apt-get install -y nodejs 2>/dev/null || true"])
                    # Install the agent
                    self.exec_in_sandbox(name, ["bash", "-c", install_cmd])
                    console.print(f"[green]✓ {agent_id} installed in sandbox[/green]")

            return {
                "container_id": container_id,
                "name": container_name,
                "image": docker_image,
                "status": "running",
                "needs_install": needs_install,
            }
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr or ""
            if "mounts denied" in error_msg or "not shared from the host" in error_msg:
                console.print(f"[red]Failed to create sandbox: Docker mount denied[/red]")
                console.print(f"[yellow]The path {project_path} is not shared with Docker.[/yellow]")
                console.print("[dim]Fix: Docker Desktop → Preferences → Resources → File Sharing[/dim]")
                console.print(f"[dim]Add the path: {project_path}[/dim]")
                console.print("")
                console.print("[dim]Alternatively, run without --sandbox to use local mode.[/dim]")
            else:
                console.print(f"[red]Failed to create sandbox: {error_msg}[/red]")
            return {}

    def _pull_image(self, image_name: str) -> bool:
        """Pull a Docker image from registry."""
        try:
            console.print(f"[dim]Pulling {image_name}...[/dim]")
            result = subprocess.run(
                ["docker", "pull", image_name],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                console.print(f"[green]✓ Image pulled: {image_name}[/green]")
                return True
            else:
                console.print(f"[red]Failed to pull image: {result.stderr}[/red]")
                return False
        except FileNotFoundError:
            return False

    def list_sandboxes(self, agent_id: str | None = None) -> list[dict[str, str]]:
        """List all agentbox sandboxes."""
        try:
            filter_label = "agentbox=true"
            if agent_id:
                filter_label = f"agentbox.agent={agent_id}"

            result = subprocess.run(
                [
                    "docker", "ps", "-a",
                    "--filter", f"label={filter_label}",
                    "--format", "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Labels}}",
                ],
                capture_output=True,
                text=True,
            )

            sandboxes = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 4:
                    labels = {}
                    if len(parts) >= 5:
                        for label in parts[4].split(","):
                            if "=" in label:
                                k, v = label.split("=", 1)
                                labels[k] = v
                    sandboxes.append({
                        "container_id": parts[0],
                        "name": parts[1],
                        "image": parts[2],
                        "status": parts[3],
                        "agent": labels.get("agentbox.agent", "unknown"),
                    })

            return sandboxes
        except FileNotFoundError:
            return []

    def kill_sandbox(self, name: str) -> bool:
        """Stop and remove a sandbox container."""
        container_name = f"agentbox-{name}"
        try:
            subprocess.run(["docker", "stop", container_name], capture_output=True, check=False)
            subprocess.run(["docker", "rm", container_name], capture_output=True, check=True)
            console.print(f"[green]✓ Sandbox removed:[/green] {container_name}")
            return True
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Failed to remove sandbox: {e.stderr}[/red]")
            return False

    def kill_all_sandboxes(self) -> int:
        """Kill all agentbox sandboxes. Returns count removed."""
        sandboxes = self.list_sandboxes()
        count = 0
        for sb in sandboxes:
            name = sb["name"].replace("agentbox-", "", 1)
            if self.kill_sandbox(name):
                count += 1
        return count

    def exec_in_sandbox(self, name: str, command: list[str], interactive: bool = False) -> int:
        """Execute a command inside a sandbox container."""
        container_name = f"agentbox-{name}"
        cmd = ["docker", "exec"]
        if interactive:
            cmd.extend(["-it"])
        cmd.extend([container_name] + command)

        try:
            result = subprocess.run(cmd)
            return result.returncode
        except FileNotFoundError:
            console.print("[red]Docker not found[/red]")
            return 1

    def get_sandbox_logs(self, name: str, tail: int = 50) -> str:
        """Get logs from a sandbox container."""
        container_name = f"agentbox-{name}"
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(tail), container_name],
                capture_output=True,
                text=True,
            )
            return result.stdout + result.stderr
        except FileNotFoundError:
            return "Docker not found"

    def build_agent_image(self, agent_id: str) -> bool:
        """Build Docker image for a specific agent."""
        agent_config = self.config.get("agents", {}).get(agent_id)
        if not agent_config:
            console.print(f"[red]Unknown agent: {agent_id}[/red]")
            return False

        image_name = agent_config.get("docker_image", f"agentbox-{agent_id}:latest")
        install_cmd = agent_config.get("install_cmd", "")

        # Use the templates directory for Dockerfile
        template_dir = Path(__file__).parent.parent / "templates" / "docker"
        dockerfile_path = template_dir / f"Dockerfile.{agent_id}"

        if dockerfile_path.exists():
            console.print(f"[dim]Building {image_name} from {dockerfile_path}...[/dim]")
            try:
                subprocess.run(
                    ["docker", "build", "-t", image_name, "-f", str(dockerfile_path), str(template_dir)],
                    check=True,
                )
                console.print(f"[green]✓ Image built: {image_name}[/green]")
                return True
            except subprocess.CalledProcessError as e:
                console.print(f"[red]Build failed: {e}[/red]")
                return False
        else:
            # Generate a Dockerfile on the fly
            console.print(f"[dim]Generating Dockerfile for {agent_id}...[/dim]")
            return self._generate_agent_image(agent_id, image_name, install_cmd)

    def _generate_agent_image(self, agent_id: str, image_name: str, install_cmd: str) -> bool:
        """Generate and build a Docker image for an agent."""
        dockerfile = f"""FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \\
    curl git build-essential \\
    && rm -rf /var/lib/apt/lists/*

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \\
    && apt-get install -y nodejs

# Install Python
RUN apt-get update && apt-get install -y python3 python3-pip \\
    && rm -rf /var/lib/apt/lists/*

# Install the agent
RUN {install_cmd}

# Create workspace
RUN mkdir -p /workspace
WORKDIR /workspace

# Keep container alive
CMD ["tail", "-f", "/dev/null"]
"""
        # Write temporary Dockerfile
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".Dockerfile", delete=False) as f:
            f.write(dockerfile)
            tmp_path = f.name

        try:
            build_dir = str(Path(tmp_path).parent)
            subprocess.run(
                ["docker", "build", "-t", image_name, "-f", tmp_path, build_dir],
                check=True,
            )
            console.print(f"[green]✓ Image built: {image_name}[/green]")
            return True
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Build failed: {e}[/red]")
            return False
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def print_sandboxes(self, agent_id: str | None = None) -> None:
        """Print a formatted table of sandboxes."""
        sandboxes = self.list_sandboxes(agent_id)
        if not sandboxes:
            console.print("[dim]No sandboxes running.[/dim]")
            return

        table = Table(title="Agentbox Sandboxes")
        table.add_column("ID", style="dim")
        table.add_column("Name", style="cyan")
        table.add_column("Agent", style="magenta")
        table.add_column("Image", style="green")
        table.add_column("Status")

        for sb in sandboxes:
            status_style = "green" if "Up" in sb["status"] else "red"
            table.add_row(
                sb["container_id"],
                sb["name"],
                sb["agent"],
                sb["image"],
                f"[{status_style}]{sb['status']}[/{status_style}]",
            )

        console.print(table)
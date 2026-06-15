"""Docker sandbox manager -- create, manage, and destroy isolated agent environments.

Orchestrates the full lifecycle of Docker-based sandboxes that run AI agents
in isolation -- from provisioning and image caching to teardown and cleanup.
Each sandbox is a lightweight container on a shared Docker network, with
optional project-directory mounts and resource limits enforced per container.
"""

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()


# ── Sandbox Manager ────────────────────────────────────────────────────────────


class SandboxManager:
    """Manages Docker-based sandboxes for running AI agents in isolation.

    Provides methods to create, reuse, stop, and remove sandbox containers,
    as well as build and cache agent-specific Docker images for fast startup.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the sandbox manager with the given configuration.

        Parameters:
            config: Application configuration dictionary containing
                ``sandbox`` and ``agents`` top-level keys.
        """
        self.config = config
        self.sandbox_config = config.get("sandbox", {})
        self.network_name = self.sandbox_config.get("network", "agentbox-net")

    # ── Docker Primitives ──────────────────────────────────────────────────

    def _docker_available(self) -> bool:
        """Check whether Docker is installed and the daemon is reachable.

        Returns:
            ``True`` if ``docker info`` succeeds, ``False`` otherwise.
        """
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
        """Check whether a Docker image exists in the local store.

        Parameters:
            image_name: Image tag or digest to look up (e.g. ``agentbox-base:latest``).

        Returns:
            ``True`` if the image is present, ``False`` otherwise.
        """
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", image_name],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def _container_exists(self, container_name: str) -> bool:
        """Check whether a container exists (running or stopped).

        Parameters:
            container_name: Name of the container to inspect.

        Returns:
            ``True`` if the container is present, ``False`` otherwise.
        """
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", container_name],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def _container_is_running(self, container_name: str) -> bool:
        """Check whether a container is currently in the running state.

        Parameters:
            container_name: Name of the container to inspect.

        Returns:
            ``True`` if the container status is ``Running``, ``False`` otherwise.
        """
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Running}}", container_name],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0 and "true" in result.stdout.lower()
        except FileNotFoundError:
            return False

    def _get_container_id(self, container_name: str) -> str:
        """Retrieve the short (12-character) container ID for a named container.

        Parameters:
            container_name: Name of the container to look up.

        Returns:
            The first 12 characters of the container ID, or ``"unknown"`` on
            failure.
        """
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.Id}}", container_name],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip()[:12]
        except FileNotFoundError:
            pass
        return "unknown"

    # ── Network ────────────────────────────────────────────────────────────

    def ensure_network(self) -> None:
        """Ensure the shared Docker network exists, creating it if necessary."""
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

    # ── Image Management ───────────────────────────────────────────────────

    def _commit_container_as_image(self, container_name: str, image_name: str) -> bool:
        """Save a container's current filesystem state as a Docker image.

        Used to cache an agent installation so subsequent sandboxes can start
        from the pre-installed image instead of running the install command
        every time.

        Parameters:
            container_name: Name of the running container to commit.
            image_name: Tag to assign to the resulting image.

        Returns:
            ``True`` if the commit succeeded, ``False`` otherwise.
        """
        try:
            result = subprocess.run(
                ["docker", "commit", container_name, image_name],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                console.print(f"[dim]Saved image cache: {image_name}[/dim]")
                return True
            return False
        except FileNotFoundError:
            return False

    def _ensure_base_image(self, base_image: str = "agentbox-base:latest") -> bool:
        """Ensure the base image exists, building from Dockerfile.base if not.

        The base image contains Node.js, Python, Go, git, and other shared
        dependencies.  All agent-specific images are built on top of it to
        share these layers and minimise rebuild time.

        Parameters:
            base_image: Tag of the base image to ensure.

        Returns:
            ``True`` if the image is available (pre-existing or freshly built),
            ``False`` if the build failed.
        """
        if self._image_exists(base_image):
            return True

        console.print(f"[yellow]Base image '{base_image}' not found, building from Dockerfile.base...[/yellow]")
        template_dir = Path(__file__).parent.parent / "templates" / "docker"
        dockerfile_path = template_dir / "Dockerfile.base"

        if not dockerfile_path.exists():
            console.print(f"[red]Dockerfile.base not found at {dockerfile_path}[/red]")
            return False

        try:
            console.print("[dim]Building base image (first time only, ~3-5 minutes)...[/dim]")
            subprocess.run(
                ["docker", "build", "-t", base_image, "-f", str(dockerfile_path), str(template_dir)],
                check=True,
            )
            console.print(f"[green]Base image built: {base_image}[/green]")
            return True
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Failed to build base image: {e}[/red]")
            console.print("[dim]You can build it manually: ag build base[/dim]")
            return False

    def _pull_image(self, image_name: str) -> bool:
        """Pull a Docker image from a remote registry.

        Parameters:
            image_name: Fully qualified image tag to pull.

        Returns:
            ``True`` if the pull succeeded, ``False`` otherwise.
        """
        try:
            console.print(f"[dim]Pulling {image_name}...[/dim]")
            result = subprocess.run(
                ["docker", "pull", image_name],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                console.print(f"[green]Image pulled: {image_name}[/green]")
                return True
            else:
                console.print(f"[red]Failed to pull image: {result.stderr}[/red]")
                return False
        except FileNotFoundError:
            return False

    def build_agent_image(self, agent_id: str) -> bool:
        """Build a Docker image for a specific agent.

        If a ``Dockerfile.<agent_id>`` exists in the templates directory it is
        used directly; otherwise a minimal Dockerfile is generated on the fly
        that layers the agent's install command on top of the base image.

        Parameters:
            agent_id: Identifier of the agent whose image should be built.

        Returns:
            ``True`` if the image was built successfully, ``False`` otherwise.
        """
        agent_config = self.config.get("agents", {}).get(agent_id)
        if not agent_config:
            console.print(f"[red]Unknown agent: {agent_id}[/red]")
            return False

        image_name = agent_config.get("docker_image", f"agentbox-{agent_id}:latest")
        install_cmd = agent_config.get("install_cmd", "")

        template_dir = Path(__file__).parent.parent / "templates" / "docker"
        dockerfile_path = template_dir / f"Dockerfile.{agent_id}"

        if dockerfile_path.exists():
            base_image = self.sandbox_config.get("base_image", "agentbox-base:latest")
            self._ensure_base_image(base_image)

            console.print(f"[dim]Building {image_name} from {dockerfile_path}...[/dim]")
            try:
                subprocess.run(
                    ["docker", "build", "-t", image_name, "-f", str(dockerfile_path), str(template_dir)],
                    check=True,
                )
                console.print(f"[green]Image built: {image_name}[/green]")
                return True
            except subprocess.CalledProcessError as e:
                console.print(f"[red]Build failed: {e}[/red]")
                return False
        else:
            console.print(f"[dim]Generating Dockerfile for {agent_id}...[/dim]")
            return self._generate_agent_image(agent_id, image_name, install_cmd)

    def _generate_agent_image(self, agent_id: str, image_name: str, install_cmd: str) -> bool:
        """Generate and build a Docker image for an agent on top of the base image.

        Writes a temporary Dockerfile that inherits from the base image and
        runs the agent's install command, then builds it and cleans up.

        Parameters:
            agent_id: Identifier of the agent (used for logging only).
            image_name: Tag to assign to the built image.
            install_cmd: Shell command that installs the agent inside the image.

        Returns:
            ``True`` if the image was built successfully, ``False`` otherwise.
        """
        base_image = self.sandbox_config.get("base_image", "agentbox-base:latest")
        self._ensure_base_image(base_image)

        dockerfile = f"""FROM {base_image}

# Install the agent
RUN {install_cmd}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".Dockerfile", delete=False) as f:
            f.write(dockerfile)
            tmp_path = f.name

        try:
            build_dir = str(Path(tmp_path).parent)
            subprocess.run(
                ["docker", "build", "-t", image_name, "-f", tmp_path, build_dir],
                check=True,
            )
            console.print(f"[green]Image built: {image_name}[/green]")
            return True
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Build failed: {e}[/red]")
            return False
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ── Sandbox Lifecycle ──────────────────────────────────────────────────

    def create_sandbox(
        self,
        name: str,
        agent_id: str,
        project_path: str | None = None,
        image: str | None = None,
    ) -> dict[str, str]:
        """Create or reuse a sandbox container for an agent.

        Employs a layered strategy that avoids re-installing agents every time:

        1. If a **running** container with the same name exists, reuse it.
        2. If a **stopped** container exists, restart it.
        3. If an agent-specific Docker image exists locally, create from it.
        4. Otherwise, create from the base image and install the agent, then
           commit the result as a cached image for future use.

        Parameters:
            name: Human-readable sandbox name (prefixed with ``agentbox-``).
            agent_id: Identifier of the agent to run inside the sandbox.
            project_path: Host directory to mount inside the container, or
                ``None`` to skip mounting.
            image: Docker image to use instead of the agent's configured image.

        Returns:
            A dictionary with keys ``container_id``, ``name``, ``image``,
            ``status``, and ``needs_install``; or an empty dict on failure.
        """
        if not self._docker_available():
            console.print("[red]Docker is not available or not running![/red]")
            console.print("[dim]Start Docker Desktop or Docker daemon first.[/dim]")
            return {}

        self.ensure_network()

        agent_config = self.config.get("agents", {}).get(agent_id, {})
        docker_image = image or agent_config.get(
            "docker_image",
            self.sandbox_config.get("base_image", "agentbox-base:latest"),
        )
        mount_point = self.sandbox_config.get("mount_point", "/workspace")
        memory_limit = self.sandbox_config.get("memory_limit", "4g")
        cpu_limit = self.sandbox_config.get("cpu_limit", 2)

        container_name = f"agentbox-{name}"

        # -- Strategy 1: Reuse running container --
        if self._container_is_running(container_name):
            container_id = self._get_container_id(container_name)

            run_cmd = agent_config.get("run_cmd", agent_id)
            check_result = subprocess.run(
                ["docker", "exec", container_name, "which", run_cmd.split()[0]],
                capture_output=True,
                text=True,
            )
            if check_result.returncode != 0:
                console.print(f"[yellow]Agent '{agent_id}' not found in running container, installing...[/yellow]")
                install_cmd = agent_config.get("install_cmd", "")
                if install_cmd:
                    console.print(f"[dim]Installing {agent_id} inside sandbox...[/dim]")
                    self.exec_in_sandbox(name, ["bash", "-c", install_cmd])
                    console.print(f"[green]{agent_id} installed in sandbox[/green]")
                    target_image = agent_config.get("docker_image", f"agentbox-{agent_id}:latest")
                    self._commit_container_as_image(container_name, target_image)

            console.print(f"[green]Reusing running sandbox:[/green] {container_name} ({container_id})")
            return {
                "container_id": container_id,
                "name": container_name,
                "image": docker_image,
                "status": "running",
                "needs_install": False,
            }

        # -- Strategy 2: Restart stopped container --
        if self._container_exists(container_name):
            try:
                subprocess.run(
                    ["docker", "start", container_name],
                    capture_output=True,
                    check=True,
                )
                container_id = self._get_container_id(container_name)

                run_cmd = agent_config.get("run_cmd", agent_id)
                check_result = subprocess.run(
                    ["docker", "exec", container_name, "which", run_cmd.split()[0]],
                    capture_output=True,
                    text=True,
                )
                if check_result.returncode != 0:
                    console.print(f"[yellow]Agent '{agent_id}' not found in restarted container, installing...[/yellow]")
                    install_cmd = agent_config.get("install_cmd", "")
                    if install_cmd:
                        console.print(f"[dim]Installing {agent_id} inside sandbox...[/dim]")
                        self.exec_in_sandbox(name, ["bash", "-c", install_cmd])
                        console.print(f"[green]{agent_id} installed in sandbox[/green]")
                        target_image = agent_config.get("docker_image", f"agentbox-{agent_id}:latest")
                        self._commit_container_as_image(container_name, target_image)

                console.print(f"[green]Restarted sandbox:[/green] {container_name} ({container_id})")
                return {
                    "container_id": container_id,
                    "name": container_name,
                    "image": docker_image,
                    "status": "running",
                    "needs_install": False,
                }
            except subprocess.CalledProcessError:
                console.print(f"[yellow]Failed to restart, recreating...[/yellow]")
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    capture_output=True,
                    check=False,
                )

        # -- Strategy 3 & 4: Create new container --
        needs_install = False
        if not self._image_exists(docker_image):
            base_image = self.sandbox_config.get("base_image", "agentbox-base:latest")
            if docker_image != base_image:
                console.print(f"[yellow]Image '{docker_image}' not found locally.[/yellow]")

                if self.build_agent_image(agent_id):
                    docker_image = agent_config.get("docker_image", f"agentbox-{agent_id}:latest")
                    console.print(f"[green]Agent image built: {docker_image}[/green]")
                else:
                    self._ensure_base_image(base_image)
                    console.print(f"[dim]Using base image: {base_image}[/dim]")
                    console.print("[dim]Agent will be installed inside the container after startup.[/dim]")
                    docker_image = base_image
                    needs_install = True
            else:
                self._ensure_base_image(base_image)

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

        if project_path:
            abs_path = str(Path(project_path).resolve())
            cmd.extend(["-v", f"{abs_path}:{mount_point}"])

        cmd.append(docker_image)
        cmd.extend(["tail", "-f", "/dev/null"])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            container_id = result.stdout.strip()[:12]
            console.print(f"[green]Sandbox created:[/green] {container_name} ({container_id})")

            # Verify agent is installed (even from cached image -- cache may be stale)
            run_cmd = agent_config.get("run_cmd", agent_id)
            verify_result = subprocess.run(
                ["docker", "exec", container_name, "which", run_cmd.split()[0]],
                capture_output=True,
                text=True,
            )
            if verify_result.returncode != 0:
                needs_install = True

            if needs_install:
                install_cmd = agent_config.get("install_cmd", "")
                if install_cmd:
                    console.print(f"[dim]Installing {agent_id} inside sandbox...[/dim]")
                    self.exec_in_sandbox(name, ["bash", "-c", install_cmd])

                    verify_again = subprocess.run(
                        ["docker", "exec", container_name, "which", run_cmd.split()[0]],
                        capture_output=True,
                        text=True,
                    )
                    if verify_again.returncode == 0:
                        console.print(f"[green]{agent_id} installed in sandbox[/green]")
                        target_image = agent_config.get("docker_image", f"agentbox-{agent_id}:latest")
                        self._commit_container_as_image(container_name, target_image)
                    else:
                        console.print(f"[red]Failed to install {agent_id} in sandbox[/red]")

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
                console.print("[red]Failed to create sandbox: Docker mount denied[/red]")
                console.print(f"[yellow]The path {project_path} is not shared with Docker.[/yellow]")
                console.print("[dim]Fix: Docker Desktop -> Preferences -> Resources -> File Sharing[/dim]")
                console.print(f"[dim]Add the path: {project_path}[/dim]")
            else:
                console.print(f"[red]Failed to create sandbox: {error_msg}[/red]")
            return {}

    def stop_sandbox(self, name: str) -> bool:
        """Stop a sandbox container without removing it.

        If the agent is installed inside the container, its state is committed
        to a cached image so the next startup can skip reinstallation.

        Parameters:
            name: Sandbox name (without the ``agentbox-`` prefix).

        Returns:
            ``True`` if the sandbox was stopped successfully, ``False`` otherwise.
        """
        container_name = f"agentbox-{name}"

        try:
            # Commit the container state only when the agent is actually installed
            try:
                agent_result = subprocess.run(
                    [
                        "docker", "inspect", "--format",
                        '{{index .Config.Labels "agentbox.agent"}}',
                        container_name,
                    ],
                    capture_output=True,
                    text=True,
                )
                if agent_result.returncode == 0:
                    agent_id = agent_result.stdout.strip()
                    if agent_id:
                        agent_config = self.config.get("agents", {}).get(agent_id, {})
                        run_cmd = agent_config.get("run_cmd", agent_id)
                        check = subprocess.run(
                            ["docker", "exec", container_name, "which", run_cmd.split()[0]],
                            capture_output=True,
                            text=True,
                        )
                        if check.returncode == 0:
                            target_image = f"agentbox-{agent_id}:latest"
                            self._commit_container_as_image(container_name, target_image)
                        else:
                            console.print(
                                f"[yellow]Agent '{agent_id}' not installed in container, "
                                "skipping image cache[/yellow]"
                            )
            except Exception:
                pass

            subprocess.run(["docker", "stop", container_name], capture_output=True, check=False)
            console.print(
                f"[green]Sandbox stopped:[/green] {container_name} "
                "[dim](preserved, use --rm to delete)[/dim]"
            )
            return True
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Failed to stop sandbox: {e.stderr}[/red]")
            return False

    def kill_sandbox(self, name: str) -> bool:
        """Stop and remove a sandbox container.

        Warning: all data inside the container is lost after removal.

        Parameters:
            name: Sandbox name (without the ``agentbox-`` prefix).

        Returns:
            ``True`` if the sandbox was removed successfully, ``False`` otherwise.
        """
        container_name = f"agentbox-{name}"

        try:
            subprocess.run(["docker", "stop", container_name], capture_output=True, check=False)
            subprocess.run(["docker", "rm", container_name], capture_output=True, check=True)
            console.print(f"[green]Sandbox removed:[/green] {container_name}")
            return True
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Failed to remove sandbox: {e.stderr}[/red]")
            return False

    def kill_all_sandboxes(self) -> int:
        """Stop and remove every agentbox sandbox.

        Returns:
            The number of sandboxes successfully removed.
        """
        sandboxes = self.list_sandboxes()
        count = 0
        for sb in sandboxes:
            name = sb["name"].replace("agentbox-", "", 1)
            if self.kill_sandbox(name):
                count += 1
        return count

    # ── Container Operations ───────────────────────────────────────────────

    def exec_in_sandbox(self, name: str, command: list[str], interactive: bool = False) -> int:
        """Execute a command inside a running sandbox container.

        Parameters:
            name: Sandbox name (without the ``agentbox-`` prefix).
            command: Command and arguments to run inside the container.
            interactive: If ``True``, attach an interactive TTY (``-it``).

        Returns:
            The exit code of the executed process, or ``1`` if Docker is not
            found.
        """
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
        """Retrieve recent logs from a sandbox container.

        Parameters:
            name: Sandbox name (without the ``agentbox-`` prefix).
            tail: Number of log lines to retrieve from the end.

        Returns:
            Combined stdout and stderr output, or an error message if Docker
            is not available.
        """
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

    # ── Display ────────────────────────────────────────────────────────────

    def list_sandboxes(self, agent_id: str | None = None) -> list[dict[str, str]]:
        """List all agentbox sandboxes, optionally filtered by agent.

        Parameters:
            agent_id: If provided, only return sandboxes running this agent.

        Returns:
            A list of dictionaries, each with keys ``container_id``, ``name``,
            ``image``, ``status``, and ``agent``.
        """
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

    def print_sandboxes(self, agent_id: str | None = None) -> None:
        """Print a formatted table of all agentbox sandboxes.

        Parameters:
            agent_id: If provided, only display sandboxes running this agent.
        """
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

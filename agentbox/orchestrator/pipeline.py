"""Pipeline definitions -- composable, multi-agent workflows built from sequential and parallel steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Step Types ──────────────────────────────────────────


class StepType(Enum):
    """Classification of how a pipeline step executes relative to its neighbours."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


# ── Data Structures ─────────────────────────────────────


@dataclass
class PipelineStep:
    """A single step within a pipeline, bound to one agent.

    Attributes:
        agent: Identifier of the agent that will execute this step.
        role: Human-readable role label (e.g. ``"planner"``, ``"reviewer"``).
        prompt: Prompt template; may contain ``{key}`` placeholders resolved
            against the shared pipeline context.
        step_id: Unique identifier for this step. Defaults to ``"{role}-{agent}"``.
        step_type: Whether this step runs sequentially or in parallel.
        output_format: Hint for the expected output format (default ``"text"``).
        timeout: Maximum seconds to wait for the agent to finish.
    """

    agent: str
    role: str
    prompt: str = ""
    step_id: str = ""
    step_type: StepType = StepType.SEQUENTIAL
    output_format: str = "text"
    timeout: int = 300

    def __post_init__(self) -> None:
        """Auto-generate ``step_id`` when none is provided."""
        if not self.step_id:
            self.step_id = f"{self.role}-{self.agent}"


@dataclass
class Pipeline:
    """A named, ordered sequence of agent steps with a shared context.

    Attributes:
        name: Pipeline identifier.
        description: Brief human-readable summary.
        steps: Ordered list of :class:`PipelineStep` instances.
        shared_context: Key-value store propagated across steps.
    """

    name: str
    description: str = ""
    steps: list[PipelineStep] = field(default_factory=list)
    shared_context: dict[str, Any] = field(default_factory=dict)

    def add_step(
        self,
        agent: str,
        role: str,
        prompt: str = "",
        step_id: str = "",
        step_type: StepType = StepType.SEQUENTIAL,
        output_format: str = "text",
        timeout: int = 300,
    ) -> "Pipeline":
        """Append a new step to the pipeline and return ``self`` for chaining.

        Args:
            agent: Agent identifier for the step.
            role: Role label for the step.
            prompt: Prompt template with optional ``{key}`` placeholders.
            step_id: Explicit step identifier (auto-generated if empty).
            step_type: Execution mode -- sequential or parallel.
            output_format: Expected output format hint.
            timeout: Maximum wait time in seconds.

        Returns:
            The pipeline instance, for fluent chaining.
        """
        step = PipelineStep(
            agent=agent,
            role=role,
            prompt=prompt,
            step_id=step_id,
            step_type=step_type,
            output_format=output_format,
            timeout=timeout,
        )
        self.steps.append(step)
        return self

    def resolve_prompt(self, step: PipelineStep, context: dict[str, Any]) -> str:
        """Replace ``{key}`` placeholders in a step's prompt with context values.

        Values longer than 4 000 characters are truncated with an ellipsis marker.

        Args:
            step: The pipeline step whose prompt template will be resolved.
            context: Mapping of placeholder keys to substitution values.

        Returns:
            The resolved prompt string with all known placeholders replaced.
        """
        prompt = step.prompt
        for key, value in context.items():
            placeholder = "{" + key + "}"
            if placeholder in prompt:
                val = str(value)
                if len(val) > 4000:
                    val = val[:4000] + "\n... (truncated)"
                prompt = prompt.replace(placeholder, val)
        return prompt


# ── Factory Functions ───────────────────────────────────


def dev_pipeline(prompt: str) -> Pipeline:
    """Build a plan-code-review pipeline for software development tasks.

    Args:
        prompt: The original task description passed to the planner.

    Returns:
        A three-step pipeline: planner, coder, reviewer.
    """
    return Pipeline(
        name="dev-pipeline",
        description="Plan -> Code -> Review",
        shared_context={"original_prompt": prompt},
        steps=[
            PipelineStep(
                agent="codex",
                role="planner",
                step_id="plan",
                prompt=(
                    "You are the planner. Break down this task into clear steps.\n\n"
                    "Task: {original_prompt}\n\n"
                    "Provide a detailed plan."
                ),
                timeout=120,
            ),
            PipelineStep(
                agent="claude",
                role="coder",
                step_id="code",
                prompt=(
                    "You are the coder. Implement the following plan.\n\n"
                    "Plan:\n{plan}\n\n"
                    "Original task: {original_prompt}\n\n"
                    "Write clean code."
                ),
                timeout=300,
            ),
            PipelineStep(
                agent="codex",
                role="reviewer",
                step_id="review",
                prompt=(
                    "You are the reviewer. Review this implementation.\n\n"
                    "Implementation:\n{code}\n\n"
                    "Plan:\n{plan}\n\n"
                    "Check correctness and quality."
                ),
                timeout=120,
            ),
        ],
    )


def research_pipeline(topic: str) -> Pipeline:
    """Build a research-summarize-critique pipeline for investigative tasks.

    Args:
        topic: The research topic or question to investigate.

    Returns:
        A three-step pipeline: researcher, summarizer, critic.
    """
    return Pipeline(
        name="research-pipeline",
        description="Research -> Summarize -> Critique",
        shared_context={"original_prompt": topic},
        steps=[
            PipelineStep(
                agent="claude",
                role="researcher",
                step_id="research",
                prompt="Research this topic:\n\n{original_prompt}\n\nProvide findings.",
                timeout=180,
            ),
            PipelineStep(
                agent="codex",
                role="summarizer",
                step_id="summary",
                prompt="Summarize:\n\n{research}\n\nKey takeaways only.",
                timeout=60,
            ),
            PipelineStep(
                agent="claude",
                role="critic",
                step_id="critique",
                prompt=(
                    "Critique this summary:\n\n"
                    "Research: {research}\n\n"
                    "Summary: {summary}\n\n"
                    "Identify gaps."
                ),
                timeout=120,
            ),
        ],
    )


def compare_pipeline(prompt: str, agents: list[str] | None = None) -> Pipeline:
    """Build a pipeline that runs multiple agents in parallel, then synthesizes.

    The first agent runs sequentially; subsequent agents run in parallel.
    A final synthesizer step merges all outputs.

    Args:
        prompt: The shared task prompt given to every agent.
        agents: List of agent identifiers. Defaults to ``["claude", "codex"]``.

    Returns:
        A pipeline ending with a synthesis step across all agent outputs.
    """
    if agents is None:
        agents = ["claude", "codex"]

    steps: list[PipelineStep] = []
    for agent in agents:
        steps.append(
            PipelineStep(
                agent=agent,
                role=f"compare-{agent}",
                step_id=f"result_{agent}",
                prompt="{original_prompt}",
                step_type=StepType.PARALLEL if steps else StepType.SEQUENTIAL,
                timeout=300,
            )
        )

    steps.append(
        PipelineStep(
            agent="claude",
            role="synthesizer",
            step_id="synthesis",
            prompt=(
                "Compare and synthesize these outputs:\n\n"
                + "\n\n".join(
                    f"--- {a.upper()} ---\n{{{f'result_{a}'}}}" for a in agents
                )
                + f"\n\nOriginal: {{original_prompt}}\n\nProvide a unified response."
            ),
            timeout=120,
        )
    )

    return Pipeline(
        name="compare-pipeline",
        description=f"Compare {len(agents)} agents then synthesize",
        shared_context={"original_prompt": prompt},
        steps=steps,
    )

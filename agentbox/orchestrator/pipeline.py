"""Pipeline definition - defines multi-agent workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepType(Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


@dataclass
class PipelineStep:
    agent: str
    role: str
    prompt: str = ""
    step_id: str = ""
    step_type: StepType = StepType.SEQUENTIAL
    output_format: str = "text"
    timeout: int = 300

    def __post_init__(self):
        if not self.step_id:
            self.step_id = f"{self.role}-{self.agent}"


@dataclass
class Pipeline:
    name: str
    description: str = ""
    steps: list[PipelineStep] = field(default_factory=list)
    shared_context: dict[str, Any] = field(default_factory=dict)

    def add_step(self, agent: str, role: str, prompt: str = "",
                 step_id: str = "", step_type: StepType = StepType.SEQUENTIAL,
                 output_format: str = "text", timeout: int = 300) -> "Pipeline":
        step = PipelineStep(agent=agent, role=role, prompt=prompt,
                            step_id=step_id, step_type=step_type,
                            output_format=output_format, timeout=timeout)
        self.steps.append(step)
        return self

    def resolve_prompt(self, step: PipelineStep, context: dict[str, Any]) -> str:
        prompt = step.prompt
        for key, value in context.items():
            placeholder = "{" + key + "}"
            if placeholder in prompt:
                val = str(value)
                if len(val) > 4000:
                    val = val[:4000] + "\n... (truncated)"
                prompt = prompt.replace(placeholder, val)
        return prompt


def dev_pipeline(prompt: str) -> Pipeline:
    return Pipeline(
        name="dev-pipeline",
        description="Plan -> Code -> Review",
        shared_context={"original_prompt": prompt},
        steps=[
            PipelineStep(
                agent="codex", role="planner", step_id="plan",
                prompt="You are the planner. Break down this task into clear steps.\n\nTask: {original_prompt}\n\nProvide a detailed plan.",
                timeout=120,
            ),
            PipelineStep(
                agent="claude", role="coder", step_id="code",
                prompt="You are the coder. Implement the following plan.\n\nPlan:\n{plan}\n\nOriginal task: {original_prompt}\n\nWrite clean code.",
                timeout=300,
            ),
            PipelineStep(
                agent="codex", role="reviewer", step_id="review",
                prompt="You are the reviewer. Review this implementation.\n\nImplementation:\n{code}\n\nPlan:\n{plan}\n\nCheck correctness and quality.",
                timeout=120,
            ),
        ],
    )


def research_pipeline(topic: str) -> Pipeline:
    return Pipeline(
        name="research-pipeline",
        description="Research -> Summarize -> Critique",
        shared_context={"original_prompt": topic},
        steps=[
            PipelineStep(
                agent="claude", role="researcher", step_id="research",
                prompt="Research this topic:\n\n{original_prompt}\n\nProvide findings.",
                timeout=180,
            ),
            PipelineStep(
                agent="codex", role="summarizer", step_id="summary",
                prompt="Summarize:\n\n{research}\n\nKey takeaways only.",
                timeout=60,
            ),
            PipelineStep(
                agent="claude", role="critic", step_id="critique",
                prompt="Critique this summary:\n\nResearch: {research}\n\nSummary: {summary}\n\nIdentify gaps.",
                timeout=120,
            ),
        ],
    )


def compare_pipeline(prompt: str, agents: list[str] | None = None) -> Pipeline:
    if agents is None:
        agents = ["claude", "codex"]
    steps = []
    for agent in agents:
        steps.append(PipelineStep(
            agent=agent, role=f"compare-{agent}", step_id=f"result_{agent}",
            prompt="{original_prompt}",
            step_type=StepType.PARALLEL if steps else StepType.SEQUENTIAL,
            timeout=300,
        ))
    steps.append(PipelineStep(
        agent="claude", role="synthesizer", step_id="synthesis",
        prompt="Compare and synthesize these outputs:\n\n"
               + "\n\n".join(f"--- {a.upper()} ---\n{{{f'result_{a}'}}}" for a in agents)
               + f"\n\nOriginal: {{original_prompt}}\n\nProvide a unified response.",
        timeout=120,
    ))
    return Pipeline(
        name="compare-pipeline",
        description=f"Compare {len(agents)} agents then synthesize",
        shared_context={"original_prompt": prompt},
        steps=steps,
    )
"""Skill loader — discovers, loads and validates skill YAML definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


SKILLS_DIR = Path(__file__).parent

# Valid layers in dependency order (lowest → highest)
VALID_LAYERS = ("system", "coding", "orchestration", "ui")


def load_skill(name: str) -> dict[str, Any] | None:
    """Load a single skill definition by name.

    Args:
        name: Skill filename stem (e.g. ``"code_refactor"``).

    Returns:
        Parsed skill dictionary, or ``None`` if not found.
    """
    path = SKILLS_DIR / f"{name}.yaml"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["_source"] = str(path)
    return data


def load_all_skills() -> list[dict[str, Any]]:
    """Load every skill YAML found in the skills directory.

    Returns:
        List of parsed skill dictionaries.
    """
    skills: list[dict[str, Any]] = []
    for path in sorted(SKILLS_DIR.glob("*.yaml")):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data["_source"] = str(path)
        skills.append(data)
    return skills


def get_skills_by_layer(layer: str) -> list[dict[str, Any]]:
    """Return all skills belonging to a specific layer.

    Args:
        layer: One of ``system``, ``coding``, ``orchestration``, ``ui``.

    Returns:
        Filtered list of skill dictionaries.
    """
    if layer not in VALID_LAYERS:
        return []
    return [s for s in load_all_skills() if s.get("layer") == layer]


def get_skill_names_for_agent(agent_contract: dict[str, Any]) -> list[str]:
    """Resolve the list of skill names declared in an agent contract.

    Args:
        agent_contract: Parsed agent contract dictionary.

    Returns:
        List of skill name strings.
    """
    return list(agent_contract.get("skills", []))


def validate_skill(skill: dict[str, Any]) -> list[str]:
    """Validate a skill definition and return a list of issues.

    Args:
        skill: Parsed skill dictionary.

    Returns:
        List of validation error strings (empty if valid).
    """
    errors: list[str] = []
    if not skill.get("name"):
        errors.append("Missing required field: name")
    if skill.get("layer") not in VALID_LAYERS:
        errors.append(f"Invalid layer: {skill.get('layer')!r} (expected one of {VALID_LAYERS})")
    if not skill.get("capabilities"):
        errors.append("Missing required field: capabilities")
    return errors
"""Contract loader — discovers, loads and validates agent contract YAML definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


CONTRACTS_DIR = Path(__file__).parent


def load_contract(name: str) -> dict[str, Any] | None:
    """Load a single agent contract by name."""
    path = CONTRACTS_DIR / f"{name}.yaml"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["_source"] = str(path)
    return data


def load_all_contracts() -> list[dict[str, Any]]:
    """Load every agent contract YAML found in the contracts directory."""
    contracts: list[dict[str, Any]] = []
    for path in sorted(CONTRACTS_DIR.glob("*.yaml")):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data["_source"] = str(path)
        contracts.append(data)
    return contracts


def get_contract_skills(contract: dict[str, Any]) -> list[str]:
    """Return the list of skill names declared in a contract."""
    return list(contract.get("skills", []))


def validate_contract(contract: dict[str, Any]) -> list[str]:
    """Validate a contract definition and return a list of issues."""
    errors: list[str] = []
    agent = contract.get("agent", {})
    if not agent.get("name"):
        errors.append("Missing required field: agent.name")
    if not contract.get("skills"):
        errors.append("Missing required field: skills")
    if not contract.get("policy"):
        errors.append("Missing required field: policy")
    return errors
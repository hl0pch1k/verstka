"""Layout strategies (the axis of the three variants)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

STRATEGY_NAMES = ("structured", "visual", "compact")


class Strategy(BaseModel):
    name: str
    title: str = ""
    description: str = ""
    planner_instructions: str = ""
    kind_weights: dict[str, float] = Field(default_factory=dict)
    slide_ratio: float = 1.0
    synth_threshold: float = 0.45
    prefer_clone: float = 1.0

    def weight(self, kind: str) -> float:
        return float(self.kind_weights.get(kind, 1.0))


def default_strategies_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "strategies.yaml"


def load_strategies(path: Optional[Path | str] = None) -> dict[str, Strategy]:
    path = Path(path) if path else default_strategies_path()
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    out: dict[str, Strategy] = {}
    for name, cfg in data.items():
        out[name] = Strategy(name=name, **(cfg or {}))
    return out


def get_strategy(name: str, path: Optional[Path | str] = None) -> Strategy:
    strategies = load_strategies(path)
    if name not in strategies:
        raise KeyError(f"unknown strategy {name!r}; available: {sorted(strategies)}")
    return strategies[name]

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass
class RunRequest:
    case_id: str
    run_index: int
    params: dict[str, Any]
    mode: str = "mock"


@dataclass
class AnalysisResult:
    pass_fail: str
    metrics: dict[str, Any]
    key_events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TriageResult:
    hypotheses: list[str]
    next_experiments: list[dict[str, Any]]
    suggested_fix: str


@dataclass
class RunResult:
    run_id: str
    run_dir: str
    status: str
    params: dict[str, Any]
    flash_method: str
    diagnostics: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

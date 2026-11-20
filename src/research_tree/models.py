from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str = "b") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@dataclass
class BranchNode:
    id: str
    question: str
    angle: str
    depth: int
    parent_id: str | None = None
    status: str = "pending"
    attempts: int = 0
    last_score: int | None = None
    rejection_feedback: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    summary: str = ""
    accepted_findings: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""
    created_at: str = field(default_factory=now_iso)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BranchNode":
        return cls(
            id=value["id"], question=value["question"], angle=value.get("angle", ""),
            depth=int(value["depth"]), parent_id=value.get("parent_id"),
            status=value.get("status", "pending"), attempts=int(value.get("attempts", 0)),
            last_score=value.get("last_score"),
            rejection_feedback=list(value.get("rejection_feedback", [])),
            children=list(value.get("children", [])), summary=value.get("summary", ""),
            accepted_findings=list(value.get("accepted_findings", [])),
            checkpoints=list(value.get("checkpoints", [])), note=value.get("note", ""),
            created_at=value.get("created_at", now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "angle": self.angle,
            "depth": self.depth,
            "parent_id": self.parent_id,
            "status": self.status,
            "attempts": self.attempts,
            "last_score": self.last_score,
            "rejection_feedback": self.rejection_feedback,
            "children": self.children,
            "summary": self.summary,
            "accepted_findings": self.accepted_findings,
            "checkpoints": self.checkpoints,
            "note": self.note,
            "created_at": self.created_at,
        }


@dataclass
class ResearchResult:
    summary: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    child_angles: list[str] = field(default_factory=list)
    raw: str = ""


@dataclass
class JudgeResult:
    score: int
    reasons: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    next_direction: str = ""
    raw: str = ""


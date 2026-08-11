# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared, serialisable types for Novato's bounded Linux agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    VERIFIED = "verified"


class ToolRisk(str, Enum):
    READ_ONLY = "read_only"
    CHANGE = "change"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: ToolRisk = ToolRisk.READ_ONLY

    def as_groq_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolResult:
    tool: str
    ok: bool
    facts: dict[str, Any] = field(default_factory=dict)
    source: str = "local"
    exit_status: int = 0
    timestamp: str = ""
    truncated: bool = False
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentMessage:
    role: str
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def as_api_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content or None}
        if self.tool_calls:
            data["tool_calls"] = self.tool_calls
        return data


@dataclass
class ActionProposal:
    id: str
    purpose: str
    operation: str = "command"
    argv: tuple[str, ...] = ()
    risk: ToolRisk = ToolRisk.CHANGE
    preview: str = ""
    expected_result: str = ""
    verification_tool: str = ""
    verification_args: dict[str, Any] = field(default_factory=dict)
    path: str = ""
    key: str = ""
    value: str = ""


@dataclass
class TaskRecord:
    id: str
    purpose: str
    state: TaskState = TaskState.PENDING
    detail: str = ""


@dataclass(frozen=True)
class MemoryFact:
    id: str
    timestamp: str
    category: str
    subject: str
    summary: str
    evidence_source: str
    action_outcome: str
    invalidation: str = ""


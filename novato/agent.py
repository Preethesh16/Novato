# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded Groq reasoning loop grounded in Novato's registered local tools."""

from __future__ import annotations

import datetime as dt
import json
import shlex
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from .agent_memory import MemoryStore
from .agent_curriculum import build_agent_prompt
from .agent_tools import ToolRegistry
from .agent_types import (
    ActionProposal, MemoryFact, TaskRecord, TaskState, ToolResult,
)
from .executor import execute_argv
from .privacy import redact, redact_text

_MAX_ROUNDS = 8
_SYSTEM_PROMPT = build_agent_prompt("""You are Novato, a careful Linux mentor and maintenance agent.
Lead with the outcome. Never assume system state: use the registered read-only tools.
Inspect before proposing a change and do not repeat a completed action. For package
requests, inspect the named package, preserve install/update/remove semantics, and use
propose_package_action so Novato—not you—selects the distro package manager and source.
For other changes, call propose_action or propose_config_edit with exactly one change and a
registered read-only verification tool. The application, not you, decides whether it
is safe and asks the user. Never claim success until the returned verification passes.
Explain what changed, why it matters, material tradeoffs, and the next action in plain
language. Prefer concise answers. Do not ask the user to paste facts a tool can inspect.
If a tool is blocked or fails, explain the limitation instead of inventing a result.""")


@dataclass(frozen=True)
class AgentOutcome:
    handled: bool
    exit_code: int = 0
    reason: str = ""


class AgentSession:
    """One stateful conversation; only verified summaries outlive it."""

    def __init__(self, *, backend, system, presenter, dry_run: bool = False,
                 registry: Optional[ToolRegistry] = None,
                 memory: Optional[MemoryStore] = None) -> None:
        self.backend = backend
        self.system = system
        self.ui = presenter
        self.dry_run = dry_run
        self.registry = registry or ToolRegistry(system)
        self.memory = memory or MemoryStore()
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        self.ledger: dict[str, TaskRecord] = {}
        self._tool_call_ids: set[str] = set()
        self._completed_actions: set[str] = set()
        self._attempted_actions: set[str] = set()
        self._context_consent: Optional[bool] = None

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        self.ledger.clear()
        self._tool_call_ids.clear()
        self._completed_actions.clear()
        self._attempted_actions.clear()
        # Consent is once per session and intentionally survives /new.

    def ask(self, query: str) -> AgentOutcome:
        query = query.strip()
        if not query:
            return AgentOutcome(True)
        # User text may itself contain a pasted path or token. Keep the original
        # local, but send the privacy-safe form to the hosted model.
        self.messages.append({"role": "user", "content": redact_text(query)})
        malformed = 0
        tool_steps = 0
        inspections_this_turn: set[str] = set()
        for _round in range(_MAX_ROUNDS):
            reply = self.backend.agent_completion(self.messages, self.registry.groq_tools())
            if reply is None:
                if tool_steps:
                    self.ui.warn("Groq could not finish the explanation; no additional action was taken.")
                    return AgentOutcome(True, 0, "Groq stopped after local tool use")
                return AgentOutcome(False, 1, "Groq was unavailable or rejected tool use")
            self.messages.append(reply.as_api_dict())
            if not reply.tool_calls:
                if reply.content:
                    self.ui.console.print(reply.content, markup=False)
                    return AgentOutcome(True)
                return AgentOutcome(False, 1, "Groq returned no answer")
            for call in reply.tool_calls:
                tool_steps += 1
                if tool_steps > _MAX_ROUNDS:
                    self.ui.warn("I stopped after eight tool steps to keep this task bounded.")
                    return AgentOutcome(True, 1, "tool limit reached")
                call_id = str(call.get("id") or "")
                function = call.get("function") or {}
                name = str(function.get("name") or "")
                if not call_id or call_id in self._tool_call_ids:
                    result = ToolResult(name or "unknown", False, error="duplicate or missing tool-call id")
                else:
                    self._tool_call_ids.add(call_id)
                    try:
                        arguments = json.loads(str(function.get("arguments") or "{}"))
                        if not isinstance(arguments, dict):
                            raise ValueError("arguments must be an object")
                    except (json.JSONDecodeError, ValueError):
                        malformed += 1
                        result = ToolResult(name or "unknown", False,
                                            error="malformed tool arguments; return valid JSON")
                        if malformed > 1:
                            self.ui.warn("Groq returned malformed tool calls twice, so I stopped safely.")
                            return AgentOutcome(True, 1, "malformed tool calls")
                    else:
                        result = self.registry.execute(name, arguments)
                        if isinstance(result, ActionProposal):
                            required = (
                                "inspect_packages" if result.operation == "package_action"
                                else None
                            )
                            if not inspections_this_turn or (
                                required is not None and required not in inspections_this_turn
                            ):
                                result = ToolResult(
                                    name, False,
                                    error=(
                                        f"run {required} for the named package before proposing this change"
                                        if required else
                                        "inspect current state with a read-only tool before proposing a change"
                                    ),
                                )
                            else:
                                result = self._handle_action(result)
                        elif result.ok and name not in ("propose_action", "propose_config_edit"):
                            inspections_this_turn.add(name)
                outbound = result.as_dict()
                if not self._allow_context(outbound):
                    # Keep the API message sequence valid without disclosing the
                    # withheld result. Future chat turns can still get a plain
                    # answer or fall back locally.
                    self.messages.append({
                        "role": "tool", "tool_call_id": call_id, "name": name,
                        "content": json.dumps({"ok": False, "error": "local context withheld by user"}),
                    })
                    return AgentOutcome(False, 0, "online context consent declined")
                self.messages.append({
                    "role": "tool", "tool_call_id": call_id, "name": name,
                    "content": json.dumps(redact(outbound), ensure_ascii=False),
                })
                if result.facts.get("declined"):
                    self.ui.info("Okay — nothing was changed.")
                    return AgentOutcome(True)
        self.ui.warn("I reached the reasoning limit without a reliable final answer.")
        return AgentOutcome(True, 1, "reasoning limit reached")

    def _allow_context(self, current: dict[str, Any]) -> bool:
        if self._context_consent is not None:
            return self._context_consent
        # Protocol/policy errors contain no local evidence. They can be sent
        # back so the model corrects its tool call without consuming the user's
        # one consent decision on an empty preview.
        if not current.get("facts"):
            return True
        preview = {
            "current_tool_result": redact(current),
            "remembered_verified_facts": [
                {"category": fact.category, "subject": fact.subject,
                 "summary": fact.summary, "verified": fact.timestamp}
                for fact in self.memory.load()[-12:]
            ],
        }
        encoded = json.dumps(preview, ensure_ascii=False, indent=2)
        if len(encoded) > 1600:
            encoded = encoded[:1600] + "\n… <preview truncated>"
        self.ui.info("Groq needs this redacted local evidence to continue:")
        self.ui.console.print(encoded, markup=False)
        self._context_consent = self.ui.ask_yes_no(
            "Send this redacted evidence to Groq for this chat session?", default_no=True,
        )
        if not self._context_consent:
            self.ui.info("Okay — no system evidence was sent. Falling back to local Novato.")
            return False
        # Add remembered facts only after consent, and only as compact verified summaries.
        facts = preview["remembered_verified_facts"]
        if facts:
            self.messages.insert(1, {
                "role": "system",
                "content": "Locally stored verified history (revalidate volatile facts): "
                           + json.dumps(facts, ensure_ascii=False),
            })
        return True

    def _handle_action(self, proposal: ActionProposal) -> ToolResult:
        fingerprint = json.dumps({
            "operation": proposal.operation, "argv": proposal.argv,
            "path": proposal.path, "key": proposal.key, "value": proposal.value,
        }, sort_keys=True)
        if fingerprint in self._attempted_actions:
            return ToolResult(
                "action", False,
                error="identical action was already proposed in this session; do not repeat it",
            )
        self._attempted_actions.add(fingerprint)
        record = TaskRecord(proposal.id, proposal.purpose)
        self.ledger[proposal.id] = record
        self.ui.blank()
        self.ui.info(f"Proposed change: {proposal.purpose}")
        if proposal.operation == "config_edit":
            self.ui.console.print(proposal.preview, markup=False)
            display = f"edit {proposal.path}: set {proposal.key}"
        else:
            display = shlex.join(proposal.argv)
            self.ui.show_command(display)
        self.ui.info(f"Expected result: {proposal.expected_result}")
        if not self.ui.confirm(display, default_no=True):
            record.state = TaskState.FAILED
            record.detail = "declined by user"
            return ToolResult("action", False, facts={"declined": True}, error="user declined")
        record.state = TaskState.RUNNING
        self.ui.status_line("online", f"Running {proposal.purpose}...")
        if proposal.operation == "config_edit":
            result = self.registry.apply_config_edit(proposal, dry_run=self.dry_run)
        else:
            executed = execute_argv(proposal.argv, dry_run=self.dry_run,
                                    note=f"agent action {proposal.id}: {proposal.purpose}",
                                    on_progress=lambda seconds: self.ui.status_line(
                                        "online", f"Still running ({int(seconds)}s elapsed)...",
                                    ))
            result = ToolResult("action", executed.exit_code == 0, {
                "command": executed.command, "elapsed_seconds": round(executed.elapsed_seconds, 2),
                "dry_run": executed.dry_run,
            }, exit_status=executed.exit_code, error=executed.reason if executed.exit_code else "")
            if executed.executed:
                self.ui.info(
                    f"Command finished after {executed.elapsed_seconds:.1f}s "
                    f"(exit {executed.exit_code})."
                )
        if not result.ok:
            record.state = TaskState.FAILED
            record.detail = result.error
            return result
        record.state = TaskState.COMPLETED
        if self.dry_run:
            record.detail = "dry-run; not verified or remembered"
            return result
        verification = self.registry.execute(proposal.verification_tool, proposal.verification_args)
        if isinstance(verification, ActionProposal) or not verification.ok:
            record.detail = "change completed but verification failed"
            return ToolResult("action", False, facts={"change_result": result.as_dict()},
                              error="change completed but verification failed")
        record.state = TaskState.VERIFIED
        record.detail = proposal.expected_result
        self._completed_actions.add(fingerprint)
        fact = MemoryFact(
            id=uuid.uuid4().hex[:12], timestamp=dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
            category="system_change", subject=proposal.purpose,
            summary=redact_text(proposal.expected_result), evidence_source=proposal.verification_tool,
            action_outcome="completed and verified", invalidation="revalidate before future changes",
        )
        try:
            self.memory.append(fact)
        except OSError:
            pass
        return ToolResult("action", True, {
            "state": "verified", "expected_result": proposal.expected_result,
            "verification": verification.as_dict(), "memory_fact_id": fact.id,
        })

    def status_lines(self) -> list[str]:
        return [f"{item.id}  {item.state.value:<9}  {item.purpose}" for item in self.ledger.values()]

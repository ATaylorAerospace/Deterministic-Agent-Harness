"""Governor: the deterministic FSM execution engine.

Author: A Taylor

The Governor owns every state transition. The language model never
selects an edge; routing is resolved from TRANSITIONS, a static table
frozen at import time. Every transition, input, output, and halt is
written to the Flight Recorder before execution proceeds. Every failure
mode collapses into a typed halt; no exception propagates out of run().

The DRY_RUN gate is armed by default. Only the literal string "false"
(case-insensitive) in the DRY_RUN environment variable disarms it.
While armed, any step declared side_effectful is blocked before it is
ever invoked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from pydantic import ValidationError

from schemas.models import AuditEvent, HaltReason, IntentEnvelope, IntentType, StepResult
from src.logger import FlightRecorder


class State(str, Enum):
    IDLE = "IDLE"
    INTENT_RECEIVED = "INTENT_RECEIVED"
    VALIDATING = "VALIDATING"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    HALTED = "HALTED"


# Static routing, frozen at import time. COMPLETED and HALTED are
# terminal: they have no outgoing edges and nothing may leave them.
TRANSITIONS: Mapping[State, frozenset[State]] = MappingProxyType(
    {
        State.IDLE: frozenset({State.INTENT_RECEIVED, State.HALTED}),
        State.INTENT_RECEIVED: frozenset({State.VALIDATING, State.HALTED}),
        State.VALIDATING: frozenset({State.EXECUTING, State.HALTED}),
        State.EXECUTING: frozenset({State.COMPLETED, State.HALTED}),
        State.COMPLETED: frozenset(),
        State.HALTED: frozenset(),
    }
)

TERMINAL_STATES = frozenset({State.COMPLETED, State.HALTED})


def dry_run_armed() -> bool:
    """True unless DRY_RUN is the literal string "false" (any case).

    Unset, empty, "0", "no", "off", and every other value keep the
    safety gate armed.
    """
    return os.environ.get("DRY_RUN", "").strip().lower() != "false"


@dataclass(frozen=True)
class WorkflowStep:
    """One hardcoded unit of work. The run callable takes the previous
    step's output dictionary and must return a typed StepResult."""

    name: str
    run: Callable[[Dict[str, Any]], StepResult]
    side_effectful: bool = False


@dataclass(frozen=True)
class RunOutcome:
    """Final, immutable result of a Governor run."""

    final_state: State
    halt_reason: Optional[HaltReason]
    detail: str
    output: Dict[str, Any]


class Governor:
    """Executes a static intent-to-workflow routing table as an FSM."""

    def __init__(
        self,
        routing_table: Mapping[IntentType, Sequence[WorkflowStep]],
        recorder: FlightRecorder,
    ) -> None:
        self._routing = dict(routing_table)
        self._recorder = recorder
        self._state = State.IDLE

    @property
    def state(self) -> State:
        return self._state

    def _audit(self, event: str, details: Dict[str, Any]) -> None:
        record = AuditEvent(event=event, details=details)
        self._recorder.record(
            {
                "event": record.event,
                "timestamp": record.timestamp.isoformat(),
                "details": record.details,
            }
        )

    def _transition(self, target: State) -> bool:
        """Move to target if the static table allows it.

        The audit event is written before the move takes effect. An
        illegal request does not move the machine; the caller must halt.
        """
        if target not in TRANSITIONS[self._state]:
            return False
        self._audit(
            "transition", {"from": self._state.value, "to": target.value}
        )
        self._state = target
        return True

    def _halt(self, reason: HaltReason, detail: str) -> RunOutcome:
        self._audit("halt", {"reason": reason.value, "detail": detail})
        if self._state not in TERMINAL_STATES:
            if State.HALTED in TRANSITIONS[self._state]:
                self._transition(State.HALTED)
            else:
                # Unreachable with the static table above, but never
                # leave the machine in a live state after a halt.
                self._state = State.HALTED
        return RunOutcome(
            final_state=self._state, halt_reason=reason, detail=detail, output={}
        )

    def run(self, raw_intent: Dict[str, Any]) -> RunOutcome:
        """Drive one intent through the FSM. Never raises."""
        try:
            return self._run(raw_intent)
        except Exception as exc:  # pragma: no cover - defensive last resort
            return self._halt(HaltReason.STEP_FAILURE, f"unhandled: {exc!r}")

    def _run(self, raw_intent: Dict[str, Any]) -> RunOutcome:
        if self._state is not State.IDLE:
            return self._halt(
                HaltReason.ILLEGAL_TRANSITION,
                f"run() requires IDLE, machine is {self._state.value}",
            )

        self._audit("input_received", {"raw": raw_intent})
        if not self._transition(State.INTENT_RECEIVED):
            return self._halt(HaltReason.ILLEGAL_TRANSITION, "cannot leave IDLE")

        try:
            envelope = IntentEnvelope.model_validate(raw_intent)
        except ValidationError as exc:
            return self._halt(
                HaltReason.SCHEMA_VIOLATION, f"envelope rejected: {exc.error_count()} error(s)"
            )

        if not self._transition(State.VALIDATING):
            return self._halt(HaltReason.ILLEGAL_TRANSITION, "cannot enter VALIDATING")

        steps = self._routing.get(envelope.intent)
        if envelope.intent is IntentType.UNSUPPORTED or not steps:
            return self._halt(
                HaltReason.UNSUPPORTED_INTENT,
                f"no workflow routed for intent {envelope.intent.value!r}",
            )

        if not self._transition(State.EXECUTING):
            return self._halt(HaltReason.ILLEGAL_TRANSITION, "cannot enter EXECUTING")

        data: Dict[str, Any] = dict(envelope.payload)
        for step in steps:
            if step.side_effectful and dry_run_armed():
                return self._halt(
                    HaltReason.DRY_RUN_BLOCK,
                    f"step {step.name!r} is side_effectful and DRY_RUN is armed",
                )
            self._audit("step_input", {"step": step.name, "input": data})
            try:
                result = step.run(data)
            except Exception as exc:
                return self._halt(
                    HaltReason.STEP_FAILURE, f"step {step.name!r} raised {type(exc).__name__}"
                )
            if not isinstance(result, StepResult):
                return self._halt(
                    HaltReason.STEP_FAILURE,
                    f"step {step.name!r} returned a non-typed result",
                )
            self._audit(
                "step_output",
                {"step": step.name, "ok": result.ok, "error": result.error},
            )
            if not result.ok:
                return self._halt(
                    HaltReason.STEP_FAILURE,
                    f"step {step.name!r} failed: {result.error}",
                )
            data = dict(result.output)

        if not self._transition(State.COMPLETED):
            return self._halt(HaltReason.ILLEGAL_TRANSITION, "cannot enter COMPLETED")
        self._audit("completed", {"output": data})
        return RunOutcome(
            final_state=self._state, halt_reason=None, detail="ok", output=data
        )

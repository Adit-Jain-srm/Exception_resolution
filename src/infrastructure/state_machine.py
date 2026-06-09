"""Case state machine with validated transitions.

Enforces that cases can only move through valid state transitions,
preventing corruption from concurrent updates or programming errors.
"""

from __future__ import annotations

from ..models.enums import CaseStatus

VALID_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.RECEIVED: {CaseStatus.VALIDATING},
    CaseStatus.VALIDATING: {CaseStatus.INVESTIGATING, CaseStatus.CANCELLED},
    CaseStatus.INVESTIGATING: {CaseStatus.EVIDENCE_COMPLETE, CaseStatus.ESCALATED},
    CaseStatus.EVIDENCE_COMPLETE: {CaseStatus.DECIDING},
    CaseStatus.DECIDING: {
        CaseStatus.ACTION_TAKEN,
        CaseStatus.ESCALATED,
        CaseStatus.HELD,
    },
    CaseStatus.ACTION_TAKEN: {CaseStatus.MONITORING, CaseStatus.RESOLVED, CaseStatus.ESCALATED, CaseStatus.HELD},
    CaseStatus.MONITORING: {CaseStatus.RESOLVED, CaseStatus.ESCALATED},
    CaseStatus.HELD: {CaseStatus.AWAITING_INPUT, CaseStatus.DECIDING, CaseStatus.CANCELLED},
    CaseStatus.AWAITING_INPUT: {CaseStatus.DECIDING, CaseStatus.CANCELLED, CaseStatus.ESCALATED},
    CaseStatus.ESCALATED: {CaseStatus.RESOLVED, CaseStatus.CANCELLED},
    CaseStatus.RESOLVED: set(),
    CaseStatus.CANCELLED: set(),
}


class InvalidTransitionError(Exception):
    def __init__(self, current: CaseStatus, target: CaseStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Invalid state transition: {current} → {target}")


class CaseStateMachine:
    """Enforces valid state transitions for an exception case."""

    def __init__(self, initial_status: CaseStatus = CaseStatus.RECEIVED) -> None:
        self._status = initial_status

    @property
    def status(self) -> CaseStatus:
        return self._status

    @property
    def is_terminal(self) -> bool:
        return self._status in (CaseStatus.RESOLVED, CaseStatus.CANCELLED)

    @property
    def allowed_transitions(self) -> set[CaseStatus]:
        return VALID_TRANSITIONS.get(self._status, set())

    def can_transition_to(self, target: CaseStatus) -> bool:
        return target in self.allowed_transitions

    def transition_to(self, target: CaseStatus) -> CaseStatus:
        """Attempt state transition. Raises InvalidTransitionError if not allowed."""
        if not self.can_transition_to(target):
            raise InvalidTransitionError(self._status, target)
        self._status = target
        return self._status

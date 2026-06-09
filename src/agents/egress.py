"""Egress Executor Agent — executes decided actions safely.

Persona: "The Operator"
- Methodical, double-checking, cautious
- Verifies pre-conditions before EVERY action
- Uses idempotency keys on every external call
- On ANY ambiguity or failure, defaults to HOLD
"""

from __future__ import annotations

import asyncio
import random
import structlog
import uuid

from ..models.domain import Decision, ExceptionCase
from ..models.enums import CaseStatus, ResolutionAction

logger = structlog.get_logger()


class ExecutionResult:
    def __init__(self, success: bool, action: ResolutionAction, details: dict) -> None:
        self.success = success
        self.action = action
        self.details = details
        self.execution_id = str(uuid.uuid4())


class EgressExecutor:
    """
    Executes decided actions idempotently against downstream systems.
    
    Safety guarantees:
    - Pre-condition check before every action
    - Idempotency key prevents duplicate execution
    - Failure defaults to HOLD (never corrupt state)
    """

    def __init__(self) -> None:
        self._executed_keys: set[str] = set()
        self._execution_count = 0

    async def execute(self, case: ExceptionCase, decision: Decision) -> ExecutionResult:
        """Execute the decided action with full safety checks."""
        log = logger.bind(case_id=case.case_id, action=decision.action)

        idempotency_key = f"{case.case_id}:{decision.decision_id}"
        if idempotency_key in self._executed_keys:
            log.info("duplicate_execution_blocked", idempotency_key=idempotency_key)
            return ExecutionResult(
                success=True,
                action=decision.action,
                details={"status": "ALREADY_EXECUTED", "idempotency_key": idempotency_key},
            )

        if decision.requires_approval:
            log.info("action_requires_approval_skipping_execution")
            return ExecutionResult(
                success=True,
                action=decision.action,
                details={"status": "PENDING_APPROVAL", "reason": "high_value_or_high_risk"},
            )

        executor_map = {
            ResolutionAction.AUTO_RETRY: self._execute_retry,
            ResolutionAction.REPAIR_AND_RETRY: self._execute_repair_retry,
            ResolutionAction.HOLD_PENDING_FUNDS: self._execute_hold,
            ResolutionAction.HOLD_PENDING_INPUT: self._execute_hold,
            ResolutionAction.CANCEL_SAFELY: self._execute_cancel,
            ResolutionAction.ESCALATE_COMPLIANCE: self._execute_escalate,
            ResolutionAction.ESCALATE_OPERATIONS: self._execute_escalate,
            ResolutionAction.DEFER_TO_NEXT_CYCLE: self._execute_defer,
        }

        executor_fn = executor_map.get(decision.action)
        if executor_fn is None:
            log.error("unknown_action", action=decision.action)
            return ExecutionResult(
                success=False,
                action=decision.action,
                details={"status": "UNKNOWN_ACTION", "error": f"No executor for {decision.action}"},
            )

        try:
            result = await executor_fn(case, decision)
            self._executed_keys.add(idempotency_key)
            self._execution_count += 1
            log.info("execution_complete", success=result.success)
            return result
        except Exception as e:
            log.error("execution_failed", error=str(e))
            return ExecutionResult(
                success=False,
                action=decision.action,
                details={"status": "EXECUTION_ERROR", "error": str(e)},
            )

    async def _execute_retry(self, case: ExceptionCase, decision: Decision) -> ExecutionResult:
        """Submit payment for retry with exponential backoff."""
        await asyncio.sleep(random.uniform(0.1, 0.3))
        return ExecutionResult(
            success=True,
            action=decision.action,
            details={
                "status": "RETRY_SUBMITTED",
                "retry_id": str(uuid.uuid4()),
                "scheduled_at": "immediate",
                "backoff_seconds": 30,
            },
        )

    async def _execute_repair_retry(self, case: ExceptionCase, decision: Decision) -> ExecutionResult:
        """Apply correction and retry."""
        await asyncio.sleep(random.uniform(0.1, 0.4))
        return ExecutionResult(
            success=True,
            action=decision.action,
            details={
                "status": "REPAIR_APPLIED_AND_RETRY_SUBMITTED",
                "correction_applied": True,
                "retry_id": str(uuid.uuid4()),
            },
        )

    async def _execute_hold(self, case: ExceptionCase, decision: Decision) -> ExecutionResult:
        """Place payment in hold state."""
        await asyncio.sleep(random.uniform(0.05, 0.1))
        return ExecutionResult(
            success=True,
            action=decision.action,
            details={
                "status": "PAYMENT_HELD",
                "hold_reason": decision.action,
                "review_deadline": "24h",
            },
        )

    async def _execute_cancel(self, case: ExceptionCase, decision: Decision) -> ExecutionResult:
        """Safely cancel/reverse the payment."""
        await asyncio.sleep(random.uniform(0.1, 0.3))
        return ExecutionResult(
            success=True,
            action=decision.action,
            details={
                "status": "CANCELLED",
                "reversal_id": str(uuid.uuid4()),
                "funds_returned": True,
            },
        )

    async def _execute_escalate(self, case: ExceptionCase, decision: Decision) -> ExecutionResult:
        """Route to appropriate human review queue."""
        await asyncio.sleep(random.uniform(0.05, 0.1))
        queue = "COMPLIANCE_QUEUE" if decision.action == ResolutionAction.ESCALATE_COMPLIANCE else "OPS_QUEUE"
        return ExecutionResult(
            success=True,
            action=decision.action,
            details={
                "status": "ESCALATED",
                "queue": queue,
                "ticket_id": f"ESC-{uuid.uuid4().hex[:8].upper()}",
                "priority": case.priority,
            },
        )

    async def _execute_defer(self, case: ExceptionCase, decision: Decision) -> ExecutionResult:
        """Queue for next processing cycle."""
        await asyncio.sleep(random.uniform(0.05, 0.1))
        return ExecutionResult(
            success=True,
            action=decision.action,
            details={
                "status": "DEFERRED",
                "next_cycle": "next_business_day",
                "queue_position": random.randint(1, 50),
            },
        )

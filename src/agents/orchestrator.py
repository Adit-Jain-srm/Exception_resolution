"""Orchestrator Agent — sequences the resolution workflow end-to-end.

Persona: "The Conductor"
- Calm under pressure, decisive, time-aware
- Parallelizes investigations aggressively
- Escalates early rather than risking SLA breach
- Treats timeout as a decision (ESCALATE), not an error

Concurrency model:
- Cases processed independently (case-level parallelism)
- Investigators fan-out in parallel per case (asyncio.gather)
- LLM calls rate-limited via semaphore
"""

from __future__ import annotations

import asyncio
import time
import structlog
from datetime import datetime, timezone

from ..models.domain import ExceptionCase
from ..models.enums import CaseStatus, ResolutionAction
from ..infrastructure.case_store import CaseStore
from ..infrastructure.state_machine import InvalidTransitionError
from ..agents.ingress import IngressGateway
from ..agents.investigators import BaseInvestigator, get_investigators_for_case
from ..agents.decision_engine import DecisionEngine
from ..agents.egress import EgressExecutor, ExecutionResult
from ..guardrails.llm_guardrails import GuardrailPipeline

logger = structlog.get_logger()


class ResolutionOutcome:
    """Final outcome of processing an exception case."""

    def __init__(
        self,
        case: ExceptionCase,
        action_taken: ResolutionAction | None,
        execution_result: ExecutionResult | None,
        elapsed_ms: float,
        steps: list[str],
    ) -> None:
        self.case = case
        self.action_taken = action_taken
        self.execution_result = execution_result
        self.elapsed_ms = elapsed_ms
        self.steps = steps

    @property
    def success(self) -> bool:
        return self.execution_result is not None and self.execution_result.success


class Orchestrator:
    """
    Coordinates the full exception resolution pipeline:
    Ingress → Investigation (parallel) → Decision → Guardrails → Egress

    Manages case state transitions, timeouts, and failure handling.
    """

    def __init__(
        self,
        case_store: CaseStore | None = None,
        investigation_timeout: float = 15.0,
        max_concurrent_cases: int = 100,
    ) -> None:
        self._store = case_store or CaseStore()
        self._ingress = IngressGateway(self._store)
        self._decision_engine = DecisionEngine()
        self._egress = EgressExecutor()
        self._guardrails = GuardrailPipeline()
        self._investigation_timeout = investigation_timeout
        self._semaphore = asyncio.Semaphore(max_concurrent_cases)
        self._processed_count = 0

    @property
    def stats(self) -> dict:
        return {
            "processed": self._processed_count,
            "ingress": self._ingress.stats,
            "guardrail_violations": self._guardrails.violations_count,
        }

    async def process_event(self, raw_event: dict) -> ResolutionOutcome | None:
        """Full end-to-end processing of a single exception event."""
        async with self._semaphore:
            return await self._process_single(raw_event)

    async def process_batch(self, events: list[dict]) -> list[ResolutionOutcome | None]:
        """Process multiple events concurrently (case-level parallelism)."""
        tasks = [self.process_event(event) for event in events]
        return await asyncio.gather(*tasks, return_exceptions=False)

    async def _process_single(self, raw_event: dict) -> ResolutionOutcome | None:
        start = time.perf_counter()
        steps: list[str] = []

        case = await self._ingress.process_event(raw_event)
        if case is None:
            return None
        steps.append("INGRESS: case accepted")

        log = logger.bind(case_id=case.case_id, exception_type=case.exception_type)

        try:
            await self._store.transition(case.case_id, CaseStatus.VALIDATING, "orchestrator")
            steps.append("STATE: RECEIVED → VALIDATING")

            await self._store.transition(case.case_id, CaseStatus.INVESTIGATING, "orchestrator")
            steps.append("STATE: VALIDATING → INVESTIGATING")

            investigators = get_investigators_for_case(case)
            evidence_list = await self._run_investigations(case, investigators)
            for evidence in evidence_list:
                case.add_evidence(evidence)
            steps.append(f"INVESTIGATION: {len(evidence_list)} investigators completed")

            await self._store.transition(case.case_id, CaseStatus.EVIDENCE_COMPLETE, "orchestrator")
            steps.append("STATE: INVESTIGATING → EVIDENCE_COMPLETE")

            await self._store.transition(case.case_id, CaseStatus.DECIDING, "orchestrator")
            steps.append("STATE: EVIDENCE_COMPLETE → DECIDING")

            decision = await self._decision_engine.decide(case)
            case.add_decision(decision)
            steps.append(f"DECISION: {decision.action} (confidence={decision.confidence})")

            try:
                validated_decision = await self._guardrails.validate(decision, case)
            except Exception as guardrail_error:
                log.warning("guardrail_violation", error=str(guardrail_error))
                decision.action = ResolutionAction.ESCALATE_OPERATIONS
                decision.justification += f" [GUARDRAIL OVERRIDE: {guardrail_error}]"
                validated_decision = decision
                steps.append(f"GUARDRAIL: violation — overriding to ESCALATE")

            await self._store.transition(case.case_id, CaseStatus.ACTION_TAKEN, "orchestrator")
            steps.append("STATE: DECIDING → ACTION_TAKEN")

            execution_result = await self._egress.execute(case, validated_decision)
            steps.append(f"EGRESS: {execution_result.details.get('status', 'UNKNOWN')}")

            terminal_status = self._determine_terminal_status(validated_decision)
            await self._store.transition(case.case_id, terminal_status, "orchestrator")
            steps.append(f"STATE: ACTION_TAKEN → {terminal_status}")

            case.add_audit(
                agent="orchestrator",
                action="resolution_complete",
                details={
                    "action": validated_decision.action,
                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )

            self._processed_count += 1
            elapsed = (time.perf_counter() - start) * 1000

            log.info(
                "case_resolved",
                action=validated_decision.action,
                elapsed_ms=round(elapsed, 2),
                final_status=terminal_status,
            )

            return ResolutionOutcome(
                case=case,
                action_taken=validated_decision.action,
                execution_result=execution_result,
                elapsed_ms=elapsed,
                steps=steps,
            )

        except InvalidTransitionError as e:
            log.error("invalid_state_transition", error=str(e))
            steps.append(f"ERROR: {e}")
            elapsed = (time.perf_counter() - start) * 1000
            return ResolutionOutcome(
                case=case, action_taken=None, execution_result=None, elapsed_ms=elapsed, steps=steps
            )
        except Exception as e:
            log.error("orchestration_error", error=str(e))
            steps.append(f"ERROR: {e}")
            elapsed = (time.perf_counter() - start) * 1000
            return ResolutionOutcome(
                case=case, action_taken=None, execution_result=None, elapsed_ms=elapsed, steps=steps
            )

    async def _run_investigations(
        self, case: ExceptionCase, investigators: list[BaseInvestigator]
    ) -> list:
        """Fan-out all investigators in parallel with case-level timeout."""
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*(inv.investigate(case) for inv in investigators)),
                timeout=self._investigation_timeout,
            )
            return list(results)
        except asyncio.TimeoutError:
            logger.warning(
                "investigation_budget_exceeded",
                case_id=case.case_id,
                timeout=self._investigation_timeout,
            )
            return []

    def _determine_terminal_status(self, decision) -> CaseStatus:
        """Map decision action to appropriate terminal case status."""
        action_to_status = {
            ResolutionAction.AUTO_RETRY: CaseStatus.MONITORING,
            ResolutionAction.REPAIR_AND_RETRY: CaseStatus.MONITORING,
            ResolutionAction.HOLD_PENDING_FUNDS: CaseStatus.HELD,
            ResolutionAction.HOLD_PENDING_INPUT: CaseStatus.HELD,
            ResolutionAction.CANCEL_SAFELY: CaseStatus.RESOLVED,
            ResolutionAction.ESCALATE_COMPLIANCE: CaseStatus.ESCALATED,
            ResolutionAction.ESCALATE_OPERATIONS: CaseStatus.ESCALATED,
            ResolutionAction.DEFER_TO_NEXT_CYCLE: CaseStatus.MONITORING,
        }
        return action_to_status.get(decision.action, CaseStatus.ESCALATED)

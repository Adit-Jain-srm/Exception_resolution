"""Decision Engine — evaluates evidence and determines resolution action.

Persona: "The Judge"
- Analytical, conservative, principled
- Errs on the side of caution — when uncertain, HOLD or ESCALATE
- Deterministic: same evidence → same decision
- Generates explicit justification for every decision
- Never recommends actions the system cannot safely execute

Architecture:
- Rule-based first pass (deterministic, auditable)
- LLM advisor for complex cases (with full guardrail pipeline)
- Confidence scoring with threshold gates
"""

from __future__ import annotations

import structlog
from decimal import Decimal

from ..models.domain import Decision, Evidence, ExceptionCase
from ..models.enums import (
    Confidence,
    EvidenceType,
    ExceptionType,
    ResolutionAction,
    RiskLevel,
)

logger = structlog.get_logger()

AMOUNT_THRESHOLD_HIGH_VALUE = Decimal("50000")
MAX_RETRY_ATTEMPTS = 5


class DecisionEngine:
    """
    Rule-based decision engine with confidence scoring.
    
    Design: LLMs ADVISE, deterministic code EXECUTES.
    The rule engine handles 80% of cases. Complex cases that rules
    cannot confidently resolve are escalated to human review.
    """

    def __init__(self, high_value_threshold: Decimal = AMOUNT_THRESHOLD_HIGH_VALUE) -> None:
        self._high_value_threshold = high_value_threshold
        self._decisions_made = 0

    async def decide(self, case: ExceptionCase) -> Decision:
        """Evaluate evidence bundle and produce a resolution decision."""
        log = logger.bind(case_id=case.case_id, exception_type=case.exception_type)

        evidence_map = self._index_evidence(case.evidence_bundle)
        decision = self._apply_rules(case, evidence_map)

        if case.amount >= self._high_value_threshold and decision.risk_level != RiskLevel.LOW:
            decision.requires_approval = True
            log.info("high_value_requires_approval", amount=float(case.amount))

        self._decisions_made += 1
        log.info(
            "decision_rendered",
            action=decision.action,
            confidence=decision.confidence,
            risk_level=decision.risk_level,
            requires_approval=decision.requires_approval,
        )
        return decision

    def _index_evidence(self, evidence_bundle: list[Evidence]) -> dict[EvidenceType, Evidence]:
        """Index evidence by type for quick lookup. Latest evidence wins on duplicates."""
        indexed: dict[EvidenceType, Evidence] = {}
        for e in evidence_bundle:
            indexed[e.evidence_type] = e
        return indexed

    def _apply_rules(self, case: ExceptionCase, evidence: dict[EvidenceType, Evidence]) -> Decision:
        """Apply exception-type-specific rules to determine action."""
        rule_map = {
            ExceptionType.INSUFFICIENT_FUNDS: self._rule_insufficient_funds,
            ExceptionType.DUPLICATE: self._rule_duplicate,
            ExceptionType.INCORRECT_BENEFICIARY: self._rule_incorrect_beneficiary,
            ExceptionType.COMPLIANCE_HOLD: self._rule_compliance_hold,
            ExceptionType.NETWORK_FAILURE: self._rule_network_failure,
            ExceptionType.CUTOFF_MISS: self._rule_cutoff_miss,
            ExceptionType.UNCERTAIN_RETRY: self._rule_uncertain_retry,
        }

        rule_fn = rule_map.get(case.exception_type)
        if rule_fn is None:
            return self._escalate_unknown(case, evidence)

        return rule_fn(case, evidence)

    def _rule_insufficient_funds(self, case: ExceptionCase, evidence: dict[EvidenceType, Evidence]) -> Decision:
        balance_evidence = evidence.get(EvidenceType.ACCOUNT_BALANCE)
        if not balance_evidence or balance_evidence.confidence == Confidence.INCONCLUSIVE:
            return self._build_decision(
                case, ResolutionAction.ESCALATE_OPERATIONS, Confidence.LOW,
                "Cannot determine account balance — escalating for manual review",
                [], ["RULE: insufficient_funds_no_evidence → escalate"],
                RiskLevel.MEDIUM,
            )

        data = balance_evidence.data
        shortfall = data.get("shortfall", 0)
        pending_credits = data.get("pending_credits", 0)

        if pending_credits >= shortfall:
            return self._build_decision(
                case, ResolutionAction.HOLD_PENDING_FUNDS, Confidence.HIGH,
                f"Shortfall of {shortfall} covered by pending credits of {pending_credits}. "
                f"Holding for fund availability.",
                [balance_evidence.evidence_id],
                ["RULE: shortfall_covered_by_pending → hold_pending_funds"],
                RiskLevel.LOW,
            )

        return self._build_decision(
            case, ResolutionAction.HOLD_PENDING_FUNDS, Confidence.MEDIUM,
            f"Insufficient balance. Shortfall: {shortfall}. Pending credits: {pending_credits}. "
            f"Holding for client funding.",
            [balance_evidence.evidence_id],
            ["RULE: insufficient_funds → hold_pending_funds"],
            RiskLevel.LOW,
        )

    def _rule_duplicate(self, case: ExceptionCase, evidence: dict[EvidenceType, Evidence]) -> Decision:
        dup_evidence = evidence.get(EvidenceType.DUPLICATE_CHECK)
        if not dup_evidence:
            return self._escalate_unknown(case, evidence)

        data = dup_evidence.data
        if data.get("duplicate_found") and data.get("original_status") == "COMPLETED":
            return self._build_decision(
                case, ResolutionAction.CANCEL_SAFELY, Confidence.HIGH,
                f"Confirmed duplicate of payment {data.get('original_payment_id')} "
                f"which completed successfully. Safe to cancel.",
                [dup_evidence.evidence_id],
                ["RULE: duplicate_confirmed_completed → cancel_safely"],
                RiskLevel.MEDIUM,
            )

        if data.get("duplicate_found") and data.get("match_confidence") != "EXACT":
            return self._build_decision(
                case, ResolutionAction.ESCALATE_OPERATIONS, Confidence.LOW,
                "Potential duplicate found but match is not exact. Requires manual verification.",
                [dup_evidence.evidence_id],
                ["RULE: duplicate_uncertain_match → escalate"],
                RiskLevel.MEDIUM,
            )

        return self._build_decision(
            case, ResolutionAction.CANCEL_SAFELY, Confidence.HIGH,
            "Duplicate payment detected. Cancelling to prevent double-debit.",
            [dup_evidence.evidence_id],
            ["RULE: duplicate_detected → cancel_safely"],
            RiskLevel.MEDIUM,
        )

    def _rule_incorrect_beneficiary(self, case: ExceptionCase, evidence: dict[EvidenceType, Evidence]) -> Decision:
        ben_evidence = evidence.get(EvidenceType.BENEFICIARY_VALIDATION)
        if not ben_evidence:
            return self._escalate_unknown(case, evidence)

        data = ben_evidence.data
        if data.get("suggested_correction") and data.get("correction_confidence") == "HIGH":
            return self._build_decision(
                case, ResolutionAction.REPAIR_AND_RETRY, Confidence.HIGH,
                f"Invalid IFSC '{data.get('original_ifsc')}' auto-corrected to "
                f"'{data.get('suggested_correction')}'. Repairing and retrying.",
                [ben_evidence.evidence_id],
                ["RULE: beneficiary_auto_correctable → repair_and_retry"],
                RiskLevel.MEDIUM,
            )

        if data.get("prior_successful_payments_to_beneficiary", 0) > 0:
            return self._build_decision(
                case, ResolutionAction.ESCALATE_OPERATIONS, Confidence.MEDIUM,
                "Beneficiary details invalid but prior successful payments exist. "
                "Possible directory change — requires manual investigation.",
                [ben_evidence.evidence_id],
                ["RULE: beneficiary_invalid_but_prior_success → escalate"],
                RiskLevel.MEDIUM,
            )

        return self._build_decision(
            case, ResolutionAction.HOLD_PENDING_INPUT, Confidence.HIGH,
            "Beneficiary details invalid and no auto-correction available. "
            "Holding for client to provide corrected details.",
            [ben_evidence.evidence_id],
            ["RULE: beneficiary_invalid_no_correction → hold_pending_input"],
            RiskLevel.LOW,
        )

    def _rule_compliance_hold(self, case: ExceptionCase, evidence: dict[EvidenceType, Evidence]) -> Decision:
        comp_evidence = evidence.get(EvidenceType.COMPLIANCE_CHECK)
        if not comp_evidence:
            return self._build_decision(
                case, ResolutionAction.ESCALATE_COMPLIANCE, Confidence.MEDIUM,
                "Compliance hold detected but screening details unavailable. Escalating.",
                [],
                ["RULE: compliance_hold_no_evidence → escalate_compliance"],
                RiskLevel.HIGH,
            )

        data = comp_evidence.data
        if data.get("requires_human_review"):
            return self._build_decision(
                case, ResolutionAction.ESCALATE_COMPLIANCE, Confidence.HIGH,
                f"Compliance hold type: {data.get('hold_type')}. "
                f"Requires mandatory human review per regulatory requirements.",
                [comp_evidence.evidence_id],
                ["RULE: compliance_requires_human → escalate_compliance"],
                RiskLevel.HIGH,
            )

        return self._build_decision(
            case, ResolutionAction.ESCALATE_COMPLIANCE, Confidence.HIGH,
            "Compliance hold — escalating to compliance team regardless of auto-clear status.",
            [comp_evidence.evidence_id],
            ["RULE: compliance_hold_always_escalate"],
            RiskLevel.HIGH,
        )

    def _rule_network_failure(self, case: ExceptionCase, evidence: dict[EvidenceType, Evidence]) -> Decision:
        net_evidence = evidence.get(EvidenceType.NETWORK_STATUS)
        retry_evidence = evidence.get(EvidenceType.RETRY_HISTORY)

        retries_remaining = 5
        if retry_evidence:
            retries_remaining = retry_evidence.data.get("retries_remaining", 0)

        if retries_remaining <= 0:
            return self._build_decision(
                case, ResolutionAction.ESCALATE_OPERATIONS, Confidence.HIGH,
                "Maximum retry attempts exhausted. Escalating for manual intervention.",
                [e.evidence_id for e in [net_evidence, retry_evidence] if e],
                ["RULE: max_retries_exhausted → escalate"],
                RiskLevel.MEDIUM,
            )

        if net_evidence and net_evidence.data.get("network_available") is False:
            recovery = net_evidence.data.get("estimated_recovery_minutes", 60)
            if recovery <= 30:
                return self._build_decision(
                    case, ResolutionAction.AUTO_RETRY, Confidence.HIGH,
                    f"Network outage detected. Estimated recovery: {recovery}min. "
                    f"Scheduling retry after recovery window.",
                    [net_evidence.evidence_id],
                    ["RULE: network_down_recoverable → auto_retry"],
                    RiskLevel.LOW,
                )
            else:
                return self._build_decision(
                    case, ResolutionAction.HOLD_PENDING_INPUT, Confidence.MEDIUM,
                    f"Network outage with estimated recovery > 30min ({recovery}min). Holding.",
                    [net_evidence.evidence_id],
                    ["RULE: network_down_extended → hold"],
                    RiskLevel.LOW,
                )

        return self._build_decision(
            case, ResolutionAction.AUTO_RETRY, Confidence.MEDIUM,
            "Network failure — transient. Retrying with exponential backoff.",
            [e.evidence_id for e in [net_evidence, retry_evidence] if e],
            ["RULE: network_failure_transient → auto_retry"],
            RiskLevel.LOW,
        )

    def _rule_cutoff_miss(self, case: ExceptionCase, evidence: dict[EvidenceType, Evidence]) -> Decision:
        return self._build_decision(
            case, ResolutionAction.DEFER_TO_NEXT_CYCLE, Confidence.HIGH,
            "Payment submitted after rail cutoff time. "
            "Deferring to next processing cycle automatically.",
            [e.evidence_id for e in evidence.values()],
            ["RULE: cutoff_miss → defer_to_next_cycle"],
            RiskLevel.LOW,
        )

    def _rule_uncertain_retry(self, case: ExceptionCase, evidence: dict[EvidenceType, Evidence]) -> Decision:
        retry_evidence = evidence.get(EvidenceType.RETRY_HISTORY)
        dup_evidence = evidence.get(EvidenceType.DUPLICATE_CHECK)

        if dup_evidence and dup_evidence.data.get("duplicate_found"):
            return self._build_decision(
                case, ResolutionAction.CANCEL_SAFELY, Confidence.HIGH,
                "Uncertain retry outcome resolved: original payment completed. "
                "Cancelling retry to prevent duplicate.",
                [e.evidence_id for e in [retry_evidence, dup_evidence] if e],
                ["RULE: uncertain_retry_duplicate_found → cancel"],
                RiskLevel.MEDIUM,
            )

        if retry_evidence:
            data = retry_evidence.data
            if data.get("consistent_failure_point"):
                return self._build_decision(
                    case, ResolutionAction.ESCALATE_OPERATIONS, Confidence.MEDIUM,
                    f"Consistent failure at '{data['consistent_failure_point']}' point. "
                    f"Requires investigation before further retries.",
                    [retry_evidence.evidence_id],
                    ["RULE: uncertain_retry_consistent_failure → escalate"],
                    RiskLevel.MEDIUM,
                )
            if data.get("retries_remaining", 0) > 0:
                return self._build_decision(
                    case, ResolutionAction.AUTO_RETRY, Confidence.LOW,
                    f"Retry outcome uncertain. {data.get('retries_remaining')} retries remaining. "
                    f"Attempting cautious retry with extended timeout.",
                    [retry_evidence.evidence_id],
                    ["RULE: uncertain_retry_retries_available → auto_retry_cautious"],
                    RiskLevel.MEDIUM,
                    requires_approval=case.amount >= self._high_value_threshold,
                )

        return self._build_decision(
            case, ResolutionAction.ESCALATE_OPERATIONS, Confidence.LOW,
            "Cannot determine retry safety. Escalating for manual investigation.",
            [e.evidence_id for e in evidence.values() if e],
            ["RULE: uncertain_retry_no_clarity → escalate"],
            RiskLevel.MEDIUM,
        )

    def _escalate_unknown(self, case: ExceptionCase, evidence: dict[EvidenceType, Evidence]) -> Decision:
        return self._build_decision(
            case, ResolutionAction.ESCALATE_OPERATIONS, Confidence.LOW,
            "Unable to determine appropriate action from available evidence. "
            "Escalating for manual review.",
            [e.evidence_id for e in evidence.values()],
            ["RULE: fallback_insufficient_evidence → escalate"],
            RiskLevel.MEDIUM,
        )

    def _build_decision(
        self,
        case: ExceptionCase,
        action: ResolutionAction,
        confidence: Confidence,
        justification: str,
        evidence_used: list[str],
        rules_applied: list[str],
        risk_level: RiskLevel,
        requires_approval: bool = False,
    ) -> Decision:
        return Decision(
            case_id=case.case_id,
            action=action,
            confidence=confidence,
            justification=justification,
            evidence_used=evidence_used,
            rules_applied=rules_applied,
            risk_level=risk_level,
            requires_approval=requires_approval,
        )

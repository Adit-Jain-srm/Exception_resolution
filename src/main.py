"""Payment Exception Resolution Agent — Main entry point.

Demonstrates end-to-end processing of all 7 exception types
through the complete agent pipeline:
  Ingress → Orchestration → Investigation → Decision → Guardrails → Egress
"""

from __future__ import annotations

import asyncio
import structlog
from decimal import Decimal

from .agents.orchestrator import Orchestrator

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(colors=True),
    ],
)

SAMPLE_EVENTS = [
    {
        "payment_id": "PAY-001-INSF",
        "client_id": "CLIENT-100",
        "account_id": "ACC-9876543210",
        "payment_rail": "NEFT",
        "payment_type": "DOMESTIC",
        "exception_type": "INSUFFICIENT_FUNDS",
        "amount": 75000,
        "currency": "INR",
        "beneficiary_name": "Raj Kumar",
        "beneficiary_account": "1234567890",
        "beneficiary_ifsc": "HDFC0001234",
    },
    {
        "payment_id": "PAY-002-DUP",
        "client_id": "CLIENT-200",
        "account_id": "ACC-1122334455",
        "payment_rail": "UPI",
        "payment_type": "DOMESTIC",
        "exception_type": "DUPLICATE",
        "amount": 15000,
        "currency": "INR",
        "beneficiary_name": "Priya Sharma",
        "beneficiary_upi": "priya@upi",
    },
    {
        "payment_id": "PAY-003-BEN",
        "client_id": "CLIENT-300",
        "account_id": "ACC-5566778899",
        "payment_rail": "NEFT",
        "payment_type": "DOMESTIC",
        "exception_type": "INCORRECT_BENEFICIARY",
        "amount": 250000,
        "currency": "INR",
        "beneficiary_name": "Amit Patel",
        "beneficiary_account": "9876543210",
        "beneficiary_ifsc": "SBIN00XXXXX",
    },
    {
        "payment_id": "PAY-004-COMP",
        "client_id": "CLIENT-400",
        "account_id": "ACC-6677889900",
        "payment_rail": "SWIFT",
        "payment_type": "WIRE",
        "exception_type": "COMPLIANCE_HOLD",
        "amount": 5000000,
        "currency": "USD",
        "beneficiary_name": "Global Trading Ltd",
        "beneficiary_account": "GB29NWBK60161331926819",
    },
    {
        "payment_id": "PAY-005-NET",
        "client_id": "CLIENT-500",
        "account_id": "ACC-1122334455",
        "payment_rail": "ACH",
        "payment_type": "DOMESTIC",
        "exception_type": "NETWORK_FAILURE",
        "amount": 42000,
        "currency": "INR",
        "beneficiary_name": "Sunita Verma",
        "beneficiary_account": "4455667788",
        "beneficiary_ifsc": "ICIC0004567",
    },
    {
        "payment_id": "PAY-006-CUT",
        "client_id": "CLIENT-600",
        "account_id": "ACC-9988776655",
        "payment_rail": "NEFT",
        "payment_type": "DOMESTIC",
        "exception_type": "CUTOFF_MISS",
        "amount": 85000,
        "currency": "INR",
        "beneficiary_name": "Tech Solutions Pvt Ltd",
        "beneficiary_account": "3344556677",
        "beneficiary_ifsc": "AXIS0000123",
    },
    {
        "payment_id": "PAY-007-UNC",
        "client_id": "CLIENT-700",
        "account_id": "ACC-1234567890",
        "payment_rail": "UPI",
        "payment_type": "DOMESTIC",
        "exception_type": "UNCERTAIN_RETRY",
        "amount": 28000,
        "currency": "INR",
        "beneficiary_name": "Food Delivery Corp",
        "beneficiary_upi": "foodcorp@ybl",
    },
]


def _print_separator() -> None:
    print("\n" + "=" * 90)


def _print_outcome(outcome) -> None:
    if outcome is None:
        print("  [DEDUPLICATED — no action taken]")
        return

    case = outcome.case
    print(f"  Case ID:        {case.case_id}")
    print(f"  Payment:        {case.payment_id} | {case.payment_rail} | {case.currency} {case.amount}")
    print(f"  Exception:      {case.exception_type}")
    print(f"  Priority:       {case.priority}")
    print(f"  Action Taken:   {outcome.action_taken or 'NONE'}")
    print(f"  Final Status:   {case.status}")
    print(f"  Elapsed:        {outcome.elapsed_ms:.1f}ms")

    if outcome.execution_result:
        print(f"  Execution:      {outcome.execution_result.details.get('status', 'N/A')}")

    if case.decision_history:
        last_decision = case.decision_history[-1]
        print(f"  Confidence:     {last_decision.confidence}")
        print(f"  Risk Level:     {last_decision.risk_level}")
        print(f"  Justification:  {last_decision.justification[:100]}...")
        print(f"  Rules Applied:  {last_decision.rules_applied}")

    print(f"  Evidence Count: {len(case.evidence_bundle)}")
    print(f"  Audit Entries:  {len(case.audit_trail)}")

    print(f"\n  Pipeline Steps:")
    for i, step in enumerate(outcome.steps, 1):
        print(f"    {i}. {step}")


async def run_demo() -> None:
    """Run all 7 exception types through the complete pipeline."""
    print("\n" + "+" + "=" * 88 + "+")
    print("|" + " PAYMENT EXCEPTION RESOLUTION AGENT -- END-TO-END DEMO ".center(88) + "|")
    print("+" + "=" * 88 + "+")

    orchestrator = Orchestrator()

    results = []
    for event in SAMPLE_EVENTS:
        _print_separator()
        print(f"  PROCESSING: {event['exception_type']} | Payment {event['payment_id']}")
        print(f"  Amount: {event.get('currency', 'INR')} {event['amount']:,}")
        _print_separator()

        outcome = await orchestrator.process_event(event)
        _print_outcome(outcome)
        results.append(outcome)

    _print_separator()
    print("\n  DEDUPLICATION TEST: Resubmitting first event...")
    _print_separator()
    dup_outcome = await orchestrator.process_event(SAMPLE_EVENTS[0])
    _print_outcome(dup_outcome)

    _print_separator()
    print("\n" + "+" + "=" * 88 + "+")
    print("|" + " SUMMARY ".center(88) + "|")
    print("+" + "=" * 88 + "+")
    print(f"\n  Total events processed: {len(SAMPLE_EVENTS) + 1}")
    print(f"  Orchestrator stats:     {orchestrator.stats}")
    print(f"  Successful resolutions: {sum(1 for r in results if r and r.success)}")
    print(f"  Duplicates blocked:     {orchestrator.stats['ingress']['duplicates']}")

    actions = {}
    for r in results:
        if r and r.action_taken:
            actions[r.action_taken] = actions.get(r.action_taken, 0) + 1
    print(f"\n  Action Distribution:")
    for action, count in sorted(actions.items()):
        print(f"    {action}: {count}")

    avg_elapsed = sum(r.elapsed_ms for r in results if r) / max(len([r for r in results if r]), 1)
    print(f"\n  Average resolution time: {avg_elapsed:.1f}ms")
    print()


def main() -> None:
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()

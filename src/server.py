"""FastAPI server exposing the exception resolution pipeline for the demo UI."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .agents.orchestrator import Orchestrator, ResolutionOutcome
from .models.enums import ExceptionType, PaymentRail

app = FastAPI(title="TxResolve — Payment Exception Resolution Agent", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

orchestrator = Orchestrator()

EXPANDED_SAMPLE_EVENTS = [
    {
        "payment_id": "PAY-2026-00101",
        "client_id": "HDFC-CORP-001",
        "account_id": "ACC-9876543210",
        "payment_rail": "NEFT",
        "payment_type": "DOMESTIC",
        "exception_type": "INSUFFICIENT_FUNDS",
        "amount": 75000,
        "currency": "INR",
        "beneficiary_name": "Raj Kumar Industries",
        "beneficiary_account": "1234567890123456",
        "beneficiary_ifsc": "HDFC0001234",
        "beneficiary_bank": "HDFC Bank",
        "description": "Vendor payment for Q2 supplies",
    },
    {
        "payment_id": "PAY-2026-00102",
        "client_id": "AXIS-SME-042",
        "account_id": "ACC-1122334455",
        "payment_rail": "UPI",
        "payment_type": "DOMESTIC",
        "exception_type": "DUPLICATE",
        "amount": 15000,
        "currency": "INR",
        "beneficiary_name": "Priya Sharma",
        "beneficiary_upi": "priya.sharma@okaxis",
        "description": "Salary advance - submitted twice by payroll system",
    },
    {
        "payment_id": "PAY-2026-00103",
        "client_id": "ICICI-WEALTH-007",
        "account_id": "ACC-5566778899",
        "payment_rail": "NEFT",
        "payment_type": "DOMESTIC",
        "exception_type": "INCORRECT_BENEFICIARY",
        "amount": 250000,
        "currency": "INR",
        "beneficiary_name": "Amit Patel & Sons",
        "beneficiary_account": "9876543210987654",
        "beneficiary_ifsc": "SBIN00XXXXX",
        "beneficiary_bank": "State Bank of India",
        "description": "Investment payout with incorrect IFSC",
    },
    {
        "payment_id": "PAY-2026-00104",
        "client_id": "SBI-INTL-019",
        "account_id": "ACC-6677889900",
        "payment_rail": "SWIFT",
        "payment_type": "WIRE",
        "exception_type": "COMPLIANCE_HOLD",
        "amount": 5000000,
        "currency": "USD",
        "beneficiary_name": "Global Trading Partners Ltd",
        "beneficiary_account": "GB29NWBK60161331926819",
        "beneficiary_bank": "NatWest Bank",
        "description": "Cross-border trade settlement flagged by sanctions screening",
    },
    {
        "payment_id": "PAY-2026-00105",
        "client_id": "KOTAK-RETAIL-088",
        "account_id": "ACC-4455667788",
        "payment_rail": "ACH",
        "payment_type": "DOMESTIC",
        "exception_type": "NETWORK_FAILURE",
        "amount": 42000,
        "currency": "INR",
        "beneficiary_name": "Sunita Verma",
        "beneficiary_account": "4455667788990011",
        "beneficiary_ifsc": "ICIC0004567",
        "beneficiary_bank": "ICICI Bank",
        "description": "EMI payment failed due to clearing network outage",
    },
    {
        "payment_id": "PAY-2026-00106",
        "client_id": "BOB-CORP-033",
        "account_id": "ACC-9988776655",
        "payment_rail": "NEFT",
        "payment_type": "DOMESTIC",
        "exception_type": "CUTOFF_MISS",
        "amount": 850000,
        "currency": "INR",
        "beneficiary_name": "Tech Solutions Pvt Ltd",
        "beneficiary_account": "3344556677889900",
        "beneficiary_ifsc": "AXIS0000123",
        "beneficiary_bank": "Axis Bank",
        "description": "Payroll batch submitted at 17:35, NEFT cutoff was 17:00",
    },
    {
        "payment_id": "PAY-2026-00107",
        "client_id": "YES-DIGITAL-055",
        "account_id": "ACC-1234567890",
        "payment_rail": "UPI",
        "payment_type": "DOMESTIC",
        "exception_type": "UNCERTAIN_RETRY",
        "amount": 28000,
        "currency": "INR",
        "beneficiary_name": "QuickBite Food Corp",
        "beneficiary_upi": "quickbite.merchant@ybl",
        "description": "Merchant settlement with 2 prior failed retries, status unknown",
    },
    {
        "payment_id": "PAY-2026-00108",
        "client_id": "PNB-GOVT-002",
        "account_id": "ACC-7788990011",
        "payment_rail": "NEFT",
        "payment_type": "DISBURSEMENT",
        "exception_type": "INSUFFICIENT_FUNDS",
        "amount": 1200000,
        "currency": "INR",
        "beneficiary_name": "Ministry of Rural Development",
        "beneficiary_account": "0011223344556677",
        "beneficiary_ifsc": "PUNB0123456",
        "beneficiary_bank": "Punjab National Bank",
        "description": "Government subsidy disbursement - critical priority",
    },
    {
        "payment_id": "PAY-2026-00109",
        "client_id": "HDFC-FX-011",
        "account_id": "ACC-2233445566",
        "payment_rail": "SWIFT",
        "payment_type": "WIRE",
        "exception_type": "NETWORK_FAILURE",
        "amount": 890000,
        "currency": "EUR",
        "beneficiary_name": "Deutsche Maschinen GmbH",
        "beneficiary_account": "DE89370400440532013000",
        "beneficiary_bank": "Commerzbank AG",
        "description": "Machinery import payment - SWIFT network intermittent",
    },
    {
        "payment_id": "PAY-2026-00110",
        "client_id": "AXIS-PAYROLL-099",
        "account_id": "ACC-8899001122",
        "payment_rail": "UPI",
        "payment_type": "DOMESTIC",
        "exception_type": "DUPLICATE",
        "amount": 45000,
        "currency": "INR",
        "beneficiary_name": "Neha Gupta",
        "beneficiary_upi": "neha.gupta@paytm",
        "description": "Bonus payment triggered twice by HR system glitch",
    },
]


class ProcessRequest(BaseModel):
    event_index: int | None = None
    custom_event: dict | None = None


def _outcome_to_dict(outcome: ResolutionOutcome | None) -> dict | None:
    if outcome is None:
        return {"status": "DEDUPLICATED", "message": "Duplicate event blocked by idempotency check"}

    case = outcome.case
    decision = case.decision_history[-1] if case.decision_history else None

    return {
        "case_id": case.case_id,
        "payment_id": case.payment_id,
        "client_id": case.client_id,
        "payment_rail": case.payment_rail.value,
        "exception_type": case.exception_type.value,
        "amount": float(case.amount),
        "currency": case.currency,
        "priority": case.priority.value,
        "final_status": case.status.value,
        "action_taken": outcome.action_taken.value if outcome.action_taken else None,
        "elapsed_ms": round(outcome.elapsed_ms, 1),
        "success": outcome.success,
        "steps": outcome.steps,
        "evidence": [
            {
                "source": e.source_agent,
                "type": e.evidence_type.value,
                "confidence": e.confidence.value,
                "data": e.data,
            }
            for e in case.evidence_bundle
        ],
        "decision": {
            "action": decision.action.value,
            "confidence": decision.confidence.value,
            "justification": decision.justification,
            "risk_level": decision.risk_level.value,
            "rules_applied": decision.rules_applied,
            "requires_approval": decision.requires_approval,
        } if decision else None,
        "audit_trail": [
            {
                "timestamp": entry.timestamp.isoformat(),
                "agent": entry.agent,
                "action": entry.action,
            }
            for entry in case.audit_trail
        ],
    }


@app.get("/api/events")
async def list_events():
    """Return all available sample events."""
    return {
        "events": [
            {
                "index": i,
                "payment_id": e["payment_id"],
                "exception_type": e["exception_type"],
                "amount": e["amount"],
                "currency": e.get("currency", "INR"),
                "payment_rail": e["payment_rail"],
                "client_id": e["client_id"],
                "description": e.get("description", ""),
                "beneficiary_name": e.get("beneficiary_name", ""),
            }
            for i, e in enumerate(EXPANDED_SAMPLE_EVENTS)
        ]
    }


@app.post("/api/process")
async def process_event(req: ProcessRequest):
    """Process a single exception event through the full pipeline."""
    if req.custom_event:
        event = req.custom_event
    elif req.event_index is not None:
        if req.event_index < 0 or req.event_index >= len(EXPANDED_SAMPLE_EVENTS):
            raise HTTPException(400, "Invalid event index")
        event = EXPANDED_SAMPLE_EVENTS[req.event_index]
    else:
        raise HTTPException(400, "Provide event_index or custom_event")

    outcome = await orchestrator.process_event(event)
    return _outcome_to_dict(outcome)


@app.post("/api/process-all")
async def process_all():
    """Process all sample events and return results."""
    fresh_orchestrator = Orchestrator()
    results = []
    for event in EXPANDED_SAMPLE_EVENTS:
        outcome = await fresh_orchestrator.process_event(event)
        results.append(_outcome_to_dict(outcome))

    return {
        "results": results,
        "stats": fresh_orchestrator.stats,
        "total": len(results),
        "successful": sum(1 for r in results if r and r.get("success")),
    }


@app.get("/api/architecture")
async def get_architecture():
    """Return system architecture metadata for visualization."""
    return {
        "agents": [
            {"id": "ingress", "name": "Ingress Guardian", "type": "gateway", "uses_llm": False, "description": "Validates, normalizes, deduplicates exception events"},
            {"id": "orchestrator", "name": "The Conductor", "type": "orchestrator", "uses_llm": True, "model": "gpt-4o-mini", "description": "Sequences workflow, manages timeouts, coordinates agents"},
            {"id": "investigator_tx", "name": "Transaction Detective", "type": "investigator", "uses_llm": False, "description": "Queries transaction status from core banking"},
            {"id": "investigator_balance", "name": "Balance Detective", "type": "investigator", "uses_llm": False, "description": "Verifies account status and available funds"},
            {"id": "investigator_beneficiary", "name": "Beneficiary Detective", "type": "investigator", "uses_llm": False, "description": "Validates beneficiary details against directories"},
            {"id": "investigator_compliance", "name": "Compliance Detective", "type": "investigator", "uses_llm": False, "description": "Checks AML/sanctions screening status"},
            {"id": "investigator_network", "name": "Network Detective", "type": "investigator", "uses_llm": False, "description": "Checks payment network availability"},
            {"id": "investigator_retry", "name": "Retry Detective", "type": "investigator", "uses_llm": False, "description": "Retrieves prior retry attempts and outcomes"},
            {"id": "investigator_dup", "name": "Duplicate Detective", "type": "investigator", "uses_llm": False, "description": "Searches for matching payments"},
            {"id": "decision", "name": "The Judge", "type": "decision", "uses_llm": True, "model": "gpt-4o", "description": "Evaluates evidence, applies rules, determines action"},
            {"id": "guardrails", "name": "Safety Gate", "type": "guardrail", "uses_llm": False, "description": "Validates decisions against safety constraints"},
            {"id": "egress", "name": "The Operator", "type": "executor", "uses_llm": False, "description": "Executes decided actions idempotently"},
            {"id": "feedback", "name": "The Historian", "type": "feedback", "uses_llm": True, "model": "gpt-4o", "description": "Incorporates new events, replays decisions"},
        ],
        "pipeline_stages": ["ingress", "orchestration", "investigation", "decision", "guardrails", "egress", "feedback"],
        "exception_types": [e.value for e in ExceptionType],
        "payment_rails": [r.value for r in PaymentRail],
    }


static_dir = Path(__file__).parent.parent / "web"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def serve_frontend():
        return FileResponse(str(static_dir / "index.html"))

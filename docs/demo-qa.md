# Payment Exception Resolution Agent — Demo Q&A Document

## Anticipated Questions, Answers & Decision Rationale

This document covers every category of question likely to be asked during a demo, presentation, or evaluation of the system.

---

## 1. HIGH-LEVEL ARCHITECTURE

### Q: Why a multi-agent system instead of a single monolithic agent?

**A:** Payment exceptions involve fundamentally different capabilities — validation is different from investigation, which is different from decision-making. A single agent would need to be good at everything simultaneously, leading to:
- Bloated prompts that confuse the model
- No failure isolation (one bad step corrupts the entire flow)
- Impossible to scale components independently
- Cannot assign different LLM models to different tasks based on complexity

Multi-agent gives us: **specialization, failure isolation, independent scaling, and the ability to use cheap models for simple tasks and expensive models only where reasoning depth is needed.**

---

### Q: How does data flow through the system end-to-end?

**A:** 
```
Raw Exception Event
  → Ingress Gateway (validate, normalize, deduplicate)
  → Orchestrator (assign priority, select investigators, manage SLA timer)
  → Investigation Agents (fan-out in parallel, gather evidence from 3-7 systems)
  → Decision Engine (evaluate evidence, apply rules, determine action)
  → Guardrail Pipeline (validate decision safety before execution)
  → Egress Executor (execute action idempotently)
  → Async Post-Decision (notify, schedule retries, audit)
  → Feedback Loop (re-evaluate when new status events arrive)
```

Average end-to-end latency: **200-400ms** for auto-resolvable cases.

---

### Q: What happens if one agent fails?

**A:** Failure isolation is a core design principle:
- If an **investigator** times out → evidence marked `INCONCLUSIVE`, other investigators still contribute
- If the **Decision Engine** fails → case auto-escalates to human review (safe fallback)
- If **Egress** fails → case moves to HELD state (never leaves in corrupt state)
- If the **LLM provider** is down → system degrades to rule-only mode (still functional, just less intelligent)

**No single agent failure can cause an incorrect financial action.** The worst case is escalation to human review.

---

## 2. LLM MODEL DECISIONS

### Q: Why use LLMs at all? Can't rules handle everything?

**A:** Rules handle ~80% of cases perfectly. But 20% involve:
- **Conflicting evidence** (transaction system says "completed", network says "no ack") — requires reasoning about which source to trust
- **Novel exception patterns** that no rule covers
- **Justification generation** — regulators require human-readable explanations, not just action codes
- **Temporal reasoning** — "this retry failed 3 times at the same point, is it worth trying again?"

**We use LLMs for the 20% that needs reasoning, not the 80% that's algorithmic.**

---

### Q: Why GPT-4o for the Decision Engine and not a fine-tuned smaller model?

**A:** Three reasons:
1. **Generalization** — Fine-tuned models are brittle on novel exception types they weren't trained on. Payment exceptions are long-tail; new patterns emerge constantly.
2. **Reasoning depth** — Decision requires multi-step logical deduction across 3-7 pieces of evidence. Smaller models fail on this.
3. **Cost is negligible** — At ~$0.01-0.03 per decision, even processing 10,000 cases/day costs $100-300/month. The cost of ONE wrong payment action (duplicate $5M wire) dwarfs the entire LLM budget.

---

### Q: Why NO LLM for investigation agents?

**A:** Investigators retrieve **facts** from systems. Facts are not generated — they're looked up. Adding LLM would:
- Introduce hallucination risk at the evidence layer (catastrophic — bad evidence → bad decisions)
- Add 500ms-2000ms variable latency to what takes 50-200ms deterministically
- Provide zero value — the answer to "what's the account balance?" is a number from an API, not a guess

**If an API is down, the truthful answer is "INCONCLUSIVE", never an LLM-generated guess.**

---

### Q: What if both LLM providers (OpenAI + Anthropic) go down?

**A:** The system degrades gracefully through 3 levels:
1. **Primary fails** → Failover to secondary provider (seamless, <5s switchover)
2. **Both fail** → Degrade to rule-only decisions. Cases that rules can handle confidently proceed. Complex cases are flagged for human review within 1 hour.
3. **Extended outage** → All new cases HELD, operations team alerted. System never guesses.

**Key insight: the system NEVER stops processing. It just becomes less intelligent temporarily.**

---

### Q: How do you ensure determinism if LLMs are non-deterministic?

**A:** Five mechanisms:
1. **Temperature 0** on all decision calls
2. **Model version pinning** — we record which model version made each decision
3. **Evidence snapshotting** — evidence is frozen at decision time, never re-fetched for replay
4. **Seeded randomness** — any jitter uses `case_id` as seed
5. **Versioned rule sets** — each decision references which rule version was active

For audit replay, we can reconstruct the exact inputs that produced any historical decision.

---

## 3. GUARDRAILS & SAFETY

### Q: What prevents the LLM from hallucinating a dangerous action?

**A:** A 5-layer guardrail pipeline:
1. **Action Allowlist** — LLM can only output from 8 predefined actions. If it outputs "SEND_EMAIL" or "APPROVE_PAYMENT", it's immediately rejected.
2. **Confidence Floor** — If confidence is below threshold for the action's risk level, auto-escalate.
3. **Evidence Reference Check** — If the LLM claims evidence that doesn't exist in the bundle, it's hallucinating. Reject immediately.
4. **Amount Threshold Gate** — Transactions >$50K require human approval regardless of LLM confidence.
5. **Hallucination Markers** — Phrases like "I think", "probably", "might be" in justification → reject (decisions must be stated factually).

**In our demo, this is LIVE: the UNCERTAIN_RETRY case gets blocked by the confidence floor guardrail.**

---

### Q: How do you handle prompt injection?

**A:** Exception events contain external text (error messages, compliance notes) that could contain adversarial content. We defend with:
- **Sanitization** — All external-origin text stripped of control characters and suspicious patterns before prompt inclusion
- **Layered prompts** — System persona and safety instructions are in layers 1-2 (highest priority), external data is in layer 4 (lowest)
- **Output validation** — Even if prompt injection succeeds in generating weird text, the output must still pass JSON schema validation and action allowlist

---

### Q: What's your PII strategy with LLMs?

**A:** We mask BEFORE the LLM sees data:
- Account numbers → `XXXX-XXXX-4532` (last 4 only)
- Beneficiary names → `[MASKED]`
- Amounts → **NOT masked** (needed for decision-making)
- Routing codes (IFSC) → **NOT masked** (needed for validation)

The Egress Executor (which actually makes API calls) never uses the LLM — it uses real values from the case store. LLM never sees full PII, execution never uses LLM output for PII fields.

---

### Q: What's your cost per case?

**A:** 
- Simple cases (rule-only): **$0.00** (no LLM call)
- Standard cases (1 LLM call): **~$0.01-0.03**
- Complex cases (2-3 LLM calls): **~$0.03-0.05**
- Hard cap per case: **$0.05** (after 5 LLM calls, force escalate)
- Monthly budget circuit breaker prevents runaway costs

At 10,000 cases/day, monthly LLM cost: **$300-1,500** (negligible vs. operational cost of manual processing at ~$15-50 per case).

---

## 4. CONCURRENCY & PERFORMANCE

### Q: How many cases can you process concurrently?

**A:** Architecture supports **100-1,000 concurrent cases** per deployment:
- Kafka partitioned by `payment_id` → all events for same payment hit same worker (no distributed locks)
- Different payments fully parallel (zero contention)
- 7 investigators fan-out concurrently within each case
- LLM calls bounded by semaphore (max 20 concurrent)

---

### Q: Why partition by payment_id?

**A:** This eliminates the hardest concurrency problem — duplicate detection:
- Two events for the same payment ALWAYS hit the same partition → same worker
- No distributed lock needed for deduplication
- Retry history is always coherent (no split-brain)
- Trade-off: hot partition if one payment generates many events (rare, handled by per-partition rate limiting)

---

### Q: What's your P95 latency?

**A:** 
- Auto-resolvable cases (insufficient funds, duplicate, cutoff): **200-400ms**
- Cases needing LLM reasoning: **1-3 seconds**
- Cases requiring human approval: **instant classification** (human takes hours, but system responds in seconds)
- SLA budget: 30s for simple, 5min for complex (both well within)

---

### Q: What prevents a thundering herd on restart?

**A:** Gradual drain: on startup, workers process at 10% capacity, ramping to 100% over 60 seconds. This prevents investigation stampede (all pending cases fan-out simultaneously) which could overwhelm downstream systems.

---

## 5. IDEMPOTENCY & SAFETY

### Q: How do you prevent duplicate payments?

**A:** Three layers:
1. **Ingress deduplication** — Composite key (payment_id + exception_type + date) with SHA-256 hash. Same event twice → blocked.
2. **Egress idempotency keys** — Every execution carries a unique key (case_id + decision_id). Same action twice → no-op.
3. **Pre-execution safety check** — Before executing retry/debit, re-verify current state. If payment already succeeded → abort.

---

### Q: What if the system crashes mid-execution?

**A:** State machine with atomic transitions:
- Each state change is persisted atomically (PostgreSQL transaction in prod, version-locked in-memory for dev)
- If crash happens between DECIDING and ACTION_TAKEN → case stays in DECIDING, gets picked up on restart
- If crash happens during execution → idempotency key prevents re-execution on retry
- **The system can be killed and restarted at any point without data loss or duplicate actions.**

---

### Q: What does "optimistic locking" mean here?

**A:** Each case has a `version` counter. When updating:
1. Read case (version = 5)
2. Make changes
3. Write case WHERE version = 5, SET version = 6
4. If another worker already incremented to 6 → write fails → retry

This prevents two workers from simultaneously transitioning the same case to conflicting states.

---

## 6. DECISION ENGINE SPECIFICS

### Q: Walk me through how a decision is made for INSUFFICIENT_FUNDS.

**A:**
1. Investigators gather evidence: account balance = INR 48K, required = INR 75K, shortfall = INR 27K
2. Also check: pending credits = INR 32K (incoming transfer expected)
3. Rule engine evaluates: `if pending_credits >= shortfall → HOLD_PENDING_FUNDS`
4. Confidence = HIGH (balance data is reliable)
5. Risk = LOW (holding is safe — no money moves)
6. Guardrails pass (no issues)
7. Execute: mark payment as HELD, schedule check after funding window

**Justification generated:** "Shortfall of 27,000 covered by pending credits of 32,000. Holding for fund availability."

---

### Q: How does the compliance case work differently?

**A:** Compliance is a **mandatory escalation** — the system NEVER auto-resolves compliance holds:
1. Compliance Investigator confirms: hold_type = "SANCTIONS_MATCH", requires_human_review = true
2. Rule: `if compliance_hold AND requires_human_review → ESCALATE_COMPLIANCE` (always)
3. Even if LLM suggested clearing it, the rule overrides (compliance escalation is hard-coded)
4. High-value gate also triggers (USD 5M > threshold)
5. Case routed to compliance queue with full evidence package

**This is regulatory requirement — no AI system should auto-clear sanctions flags.**

---

### Q: What happens when the guardrail overrides a decision?

**A:** Demonstrated live in the UNCERTAIN_RETRY case:
1. Decision Engine recommends AUTO_RETRY (confidence: LOW, risk: MEDIUM)
2. Guardrail checks: `confidence_floor[MEDIUM_RISK] = MEDIUM`
3. LOW < MEDIUM → **BLOCKED**
4. Override applied: action changed to ESCALATE_OPERATIONS
5. Justification appended: "[GUARDRAIL OVERRIDE: Confidence LOW below minimum MEDIUM for risk level MEDIUM]"
6. Case escalated to human review instead of risky auto-retry

**The guardrail prevented a potentially unsafe retry when the system wasn't confident enough.**

---

## 7. EXCEPTION TYPE HANDLING

### Q: Which cases can be fully auto-resolved?

| Exception Type | Auto-Resolvable? | Typical Action |
|---|---|---|
| Insufficient Funds | Partially — HOLD is automatic | HOLD_PENDING_FUNDS |
| Duplicate | Yes — cancellation is safe | CANCEL_SAFELY |
| Incorrect Beneficiary | Yes — if auto-correction available | REPAIR_AND_RETRY |
| Compliance Hold | NEVER — always requires human | ESCALATE_COMPLIANCE |
| Network Failure | Yes — if transient and retriable | AUTO_RETRY |
| Cutoff Miss | Yes — deterministic requeue | DEFER_TO_NEXT_CYCLE |
| Uncertain Retry | Rarely — usually needs investigation | ESCALATE_OPERATIONS |

---

### Q: What's the expected auto-resolution rate?

**A:** Target: **60-70%** of cases auto-resolved without human involvement. Breakdown:
- Cutoff miss (100% auto)
- Duplicate (95% auto)
- Insufficient funds (80% auto-hold)
- Network failure (70% auto-retry)
- Incorrect beneficiary (50% auto if IFSC correctable)
- Uncertain retry (20% auto)
- Compliance (0% auto — always human)

---

## 8. AUDITABILITY & COMPLIANCE

### Q: Can you replay a historical decision?

**A:** Yes. Every decision stores:
- Evidence bundle (frozen at decision time)
- Rule set version that was active
- Model version used
- Temperature and all LLM parameters
- Full input prompt (with PII masked)

An auditor can: load frozen evidence → apply same rules → verify output matches recorded decision. If model version is deprecated, this is logged as a "reproducibility gap."

---

### Q: What audit trail is generated per case?

**A:** Every case carries an immutable audit trail:
```
[11:47:48] orchestrator: transition_to_VALIDATING
[11:47:48] orchestrator: transition_to_INVESTIGATING  
[11:47:48] TransactionStateInvestigator: evidence_collected (confidence: HIGH)
[11:47:48] AccountBalanceInvestigator: evidence_collected (confidence: HIGH)
[11:47:48] orchestrator: transition_to_DECIDING
[11:47:48] decision_engine: decision_rendered (HOLD_PENDING_FUNDS, confidence: HIGH)
[11:47:48] guardrails: validation_passed
[11:47:48] egress: action_executed (PAYMENT_HELD)
[11:47:48] orchestrator: resolution_complete (elapsed: 289ms)
```

Every entry has: who (agent), what (action), when (timestamp), and why (evidence/rules used).

---

### Q: How long do you retain audit data?

**A:** Configurable per regulatory requirement. Default: 7 years minimum (RBI compliance). Audit log is append-only and immutable — no agent can modify historical entries.

---

## 9. PRODUCTION READINESS

### Q: What's your deployment strategy?

**A:** Staged rollout:
1. **Shadow mode** — System runs alongside manual ops, decisions logged but not executed. Measure agreement rate.
2. **Pilot** — Auto-resolve LOW risk cases only (cutoff miss, clear duplicates). Everything else still escalates.
3. **Gradual expansion** — Enable more exception types and higher amounts as confidence builds.
4. **Full production** — All exception types, kill switches ready for immediate rollback.

---

### Q: What kill switches exist?

**A:**
- **Global kill switch** — Disable all auto-resolution instantly
- **Per-rail kill switch** — Disable for specific payment rail (e.g., disable UPI auto-retry during known outage)
- **Per-exception-type** — Disable for specific exception types
- **Amount threshold** — Lower the auto-resolve amount ceiling
- **LLM kill switch** — Force all cases to rule-only mode (no LLM reasoning)

All can be toggled in <1 minute via config store without deployment.

---

### Q: How do you monitor system health?

**A:** Three pillars:
1. **Metrics** — Case throughput, resolution time (P50/P95/P99), auto-resolution rate, LLM latency, guardrail violation rate
2. **Alerts** — SLA breach, confidence drop below baseline, error rate spike, LLM cost exceeding daily budget, queue depth growing
3. **Distributed tracing** — Every case has a trace spanning all agents (OpenTelemetry), viewable in Grafana

---

## 10. TRADE-OFFS & ASSUMPTIONS

### Q: What are the main trade-offs you made?

| Trade-off | Choice Made | Alternative | Why |
|---|---|---|---|
| LLM vs Rules | Hybrid (rules primary, LLM advisor) | Pure LLM or pure rules | Rules for auditability, LLM for intelligence on edge cases |
| Speed vs Safety | Safety wins (HOLD on doubt) | Faster auto-resolution | Wrong payment action costs orders of magnitude more than a 1-hour delay |
| Cost vs Intelligence | Frontier models for decisions | Fine-tuned cheap models | $0.03/decision is negligible; wrong decisions cost $1000s+ |
| Determinism vs Flexibility | Temperature 0 + model pinning | Higher temperature for creativity | Financial decisions must be reproducible for audit |
| Parallel vs Sequential | Parallel investigators | Sequential (cheaper) | 200ms parallel vs 1.5s sequential; SLA demands speed |

---

### Q: What assumptions does the system make?

1. Exception events arrive with at minimum: payment_id, client_id, account_id, payment_rail, exception_type, amount
2. External systems (core banking, compliance, network status) have APIs that respond within 5 seconds
3. No real payment rail integration is needed (stubbed for prototype)
4. A human review queue exists for escalated cases
5. LLM providers maintain published rate limits and latency SLAs
6. Payment amounts in the evidence are accurate (system trusts source-of-record systems)

---

### Q: What's NOT in scope?

- Building real payment rail integrations (SWIFT, NEFT, UPI connectors)
- A customer-facing portal or operations UI
- A full sanctions/compliance screening system
- A complete payment engine or ledger
- Solving every rail-specific format rule in operational detail

---

## 11. COMPETITIVE DIFFERENTIATION

### Q: How is this different from a simple retry mechanism?

**A:** A retry mechanism is ONE action. This system:
- **Diagnoses** root cause before acting (is it network? funds? duplicate?)
- **Chooses from 8 actions** (not just retry — also hold, cancel, repair, defer, escalate)
- **Validates safety** before executing (guardrails prevent unsafe retries)
- **Explains** why it took each action (audit justification)
- **Learns** from outcomes (feedback loop refines rules)
- **Handles duplicates** (retry mechanisms often CREATE duplicates; we DETECT them)

---

### Q: Why not just route everything to human review?

**A:** Scale and cost:
- Manual review: $15-50 per case, 10-30 minute SLA
- Our system: $0.01-0.05 per case, 200ms-3s SLA
- At 10,000 cases/day: **$150K-500K/year manual** vs. **$1K-5K/year automated**
- Plus: humans make errors too (especially at 3 AM), and they can't be audited as precisely as code

We still escalate the ~30% that genuinely needs human judgment. We eliminate the drudgery of the obvious 70%.

---

### Q: How does the confidence scoring work?

**A:** Evidence confidence propagates to decision confidence:
- All evidence HIGH → decision confidence HIGH
- Mixed evidence (some MEDIUM) → decision confidence MEDIUM
- Any evidence INCONCLUSIVE on critical path → decision confidence LOW
- Confidence below floor for risk level → guardrail blocks, case escalates

This ensures we only auto-act when we're genuinely confident, and we never pretend certainty we don't have.

---

## 12. TECHNICAL IMPLEMENTATION

### Q: What's your tech stack?

| Layer | Technology | Why |
|---|---|---|
| Language | Python 3.12+ | Async-native, rich AI ecosystem, fast prototyping |
| Framework | FastAPI | Async, typed, auto-docs, great for agent APIs |
| LLM Interface | LiteLLM | Unified multi-provider API, failover, cost tracking |
| State Machine | Custom (Pydantic + transitions) | Full control over valid state changes |
| Message Bus | Redis Streams (dev) / Kafka (prod) | Ordering + replay in prod, simplicity in dev |
| Database | PostgreSQL | ACID, JSONB for evidence, partitioned audit log |
| Observability | OpenTelemetry + Prometheus | Industry standard, vendor-neutral |

---

### Q: How do you test this system?

**A:** Four levels:
1. **Unit tests** — Each agent tested in isolation with mocked dependencies
2. **Property-based tests** (Hypothesis) — Decision rules verified: same evidence always produces same decision
3. **Integration tests** — Full pipeline with all agents, stubbed external systems
4. **Chaos tests** — Random agent failures, timeouts, partial data — verify graceful degradation

---

### Q: Can this run on a single machine for the demo?

**A:** Yes. The architecture has logical agent boundaries (Python modules), not physical ones (separate services). For demo:
- Single Python process runs all agents in-memory
- Redis Streams replaced with in-memory queues
- PostgreSQL replaced with in-memory dict with optimistic locking
- Scales to multi-service when needed (module boundaries = service boundaries)

---

## 13. FUTURE EXTENSIONS

### Q: How would you add ML-based decision scoring?

**A:** As a **scoring layer alongside rules**, not replacing them:
1. Train on historical decisions + outcomes (which decisions succeeded/failed)
2. ML model outputs a confidence score and suggested action
3. If ML agrees with rules → proceed with higher confidence
4. If ML disagrees with rules → escalate for human review (contradiction detected)
5. ML never overrides rules — it provides additional signal

---

### Q: How would you handle a new exception type?

**A:** 
1. Add new enum value to `ExceptionType`
2. Add a new investigator (if new evidence source needed)
3. Add rule set for the new type in Decision Engine
4. Configure SLA, priority rules, and escalation thresholds
5. Deploy in shadow mode first, measure decision quality
6. Gradual rollout after validation

No architectural changes needed — the system is designed for extensibility.

---

### Q: Can this work across multiple banks/institutions?

**A:** Yes, via configuration:
- Rail-specific rules are config-driven (not hard-coded)
- Client-tier policies configurable per institution
- Multi-tenant support: partition by `client_id` + `payment_rail`
- Each institution can have different thresholds, SLAs, and escalation policies
- Compliance rules vary by jurisdiction — also configuration-driven

---

## 14. EXPLAINABILITY

### Q: How does the system explain its decisions to humans?

**A:** Every decision generates a **multi-layer explanation** designed for different audiences:

1. **Justification text** — Human-readable sentence explaining WHY this action was chosen (for operations staff, auditors)
2. **Rules applied** — Exact rule identifiers that triggered (for engineers debugging)
3. **Evidence cited** — Which specific evidence items influenced the decision, with confidence levels
4. **Risk assessment** — Why this action has LOW/MEDIUM/HIGH risk
5. **Approval rationale** — If approval is required, why (amount threshold? low confidence? compliance flag?)

Example for an INSUFFICIENT_FUNDS case:
```
Justification: "Shortfall of 27,000 covered by pending credits of 32,000. 
               Holding for fund availability."
Rules Applied: ["RULE: shortfall_covered_by_pending → hold_pending_funds"]
Evidence Used: [AccountBalanceInvestigator (confidence: HIGH)]
Risk Level:   LOW (holding is safe — no money moves)
Approval:     Not required (amount < threshold, risk is LOW)
```

---

### Q: Can a non-technical person understand why a payment was held?

**A:** Yes. The justification layer is specifically designed for non-technical readers:
- Uses natural language, not codes
- States the CAUSE ("shortfall of 27,000"), the FINDING ("pending credits of 32,000 incoming"), and the ACTION ("holding until funds available")
- Avoids jargon — says "held for fund availability" not "state transition to HELD_PENDING_FUNDS"
- If escalated, explains what the human reviewer needs to verify

---

### Q: How does explainability differ from auditability?

**A:**
| Aspect | Explainability | Auditability |
|--------|---------------|-------------|
| **Audience** | Operations staff, clients, regulators | Compliance officers, forensic investigators |
| **Purpose** | Understand WHY this action was taken | Prove WHAT happened and WHEN |
| **Format** | Natural language justification | Structured audit log entries with timestamps |
| **Granularity** | Decision-level (one explanation per case) | Action-level (every state change, every agent call) |
| **Mutability** | Can be regenerated from evidence | Immutable, append-only, legally binding |

Both are implemented. Explainability is generated AT decision time. Auditability is recorded THROUGHOUT the entire case lifecycle.

---

### Q: What makes the explanations trustworthy (not just plausible-sounding)?

**A:** Three integrity guarantees:

1. **Evidence-backed** — Every claim in the justification MUST reference actual evidence. If the justification says "pending credits of 32,000" — that number came from the AccountBalanceInvestigator, not the LLM's imagination. The guardrail pipeline rejects justifications that reference non-existent evidence.

2. **Rule-traceable** — Each justification cites the exact rule that was applied. You can look up `RULE: shortfall_covered_by_pending → hold_pending_funds` in the rule configuration and verify the logic.

3. **Reproducible** — Given the same evidence bundle, the same explanation will be generated every time (temperature 0, deterministic rules). If you replay the case a year later, you get the same justification.

---

### Q: How do you explain guardrail overrides?

**A:** When a guardrail overrides a decision, the explanation explicitly states:
- What the Decision Engine originally recommended
- Which guardrail blocked it and why
- What the safe fallback action is

Example:
```
"Retry outcome uncertain. 3 retries remaining. Attempting cautious retry 
with extended timeout. [GUARDRAIL OVERRIDE: Confidence LOW is below minimum 
MEDIUM for risk level MEDIUM. Overridden to ESCALATE_OPERATIONS for human review.]"
```

The override is NEVER hidden. The original reasoning is preserved alongside the override explanation.

---

### Q: Can clients see why their payment was held?

**A:** The system generates **tiered explanations**:
- **Internal (full)**: All evidence, rules, confidence scores, agent traces
- **Operations (summary)**: Justification + action + what to check next
- **Client-facing (safe)**: Simplified reason without revealing system internals

Client-facing example: "Your payment of INR 75,000 is temporarily held pending fund availability. Expected resolution: within 4 hours."

This avoids exposing:
- Internal account details of other parties
- Compliance screening logic (regulatory requirement to not disclose)
- System architecture details

---

### Q: How does explainability work for compliance escalations?

**A:** Compliance cases get EXTRA explanation layers:
1. **What triggered the hold** — "Payment flagged by sanctions screening: PEP_FLAG"
2. **Why it cannot be auto-resolved** — "Regulatory requirement mandates human review for all sanctions matches"
3. **What the reviewer needs to verify** — "Confirm beneficiary identity against sanctions list. Check if name match is false positive."
4. **Similar cases context** — "85% of similar PEP_FLAG cases were cleared after manual verification"

This gives compliance officers maximum context to make their decision quickly.

---

### Q: Is explainability a requirement for production or a nice-to-have?

**A:** It's a **hard requirement** for three reasons:

1. **Regulatory** — RBI/banking regulations require institutions to explain why a payment was held/cancelled/delayed to the customer within defined timeframes.

2. **Operational** — When a human reviewer picks up an escalated case, they need to understand what the system already investigated and why it couldn't resolve automatically. Without explanation, they repeat all the work.

3. **Trust-building** — Operations teams will only trust (and not override) automated decisions if they can understand the reasoning. Opaque AI decisions get overridden reflexively, defeating the purpose of automation.

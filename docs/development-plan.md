# Payment Exception Resolution Agent — Development Plan

## Project Overview

**Goal**: Build a production-grade multi-agent system for diagnosing, routing, and resolving failed payment transactions end-to-end.

**Track**: Agentic AI / AI Engineering

**Timeline**: 4 phases across ~6-8 weeks (hackathon-adjusted: MVP in Phase 1-2)

---

## Phase 1: Foundation & Core Pipeline (Week 1-2)

### Milestone: A single exception can flow from ingress to decision with stubbed dependencies

### 1.1 Project Scaffolding
- [ ] Initialize Python project with Poetry/uv for dependency management
- [ ] Set up project structure:
  ```
  src/
    agents/           — Agent implementations
    models/           — Pydantic data models
    rules/            — Decision rules engine
    infrastructure/   — Message bus, state store, config
    api/              — REST API for operations
  tests/
    unit/
    integration/
    e2e/
  config/             — Rail-specific configs, thresholds
  docs/               — Architecture, traces, runbooks
  ```
- [ ] Configure linting (ruff), formatting (black), type checking (mypy)
- [ ] Set up Docker Compose for local development stack
- [ ] Initialize git repository with conventional commits

### 1.2 Data Models & Contracts
- [ ] Define `ExceptionCase` Pydantic model with all fields
- [ ] Define `Evidence` model with confidence scoring
- [ ] Define `Decision` model with action enum and justification
- [ ] Define `AuditEntry` model for immutable logging
- [ ] Define inter-agent message envelope schema
- [ ] Create JSON Schema exports for contract validation
- [ ] Write model serialization/deserialization tests

### 1.3 State Management
- [ ] Set up PostgreSQL schema for case storage
- [ ] Implement case repository with CRUD operations
- [ ] Implement case state machine with valid transitions
- [ ] Add optimistic locking for concurrent case updates
- [ ] Implement idempotency key storage (Redis)
- [ ] Write state transition tests

### 1.4 Ingress Gateway Agent
- [ ] Implement event receiver (REST endpoint + message consumer)
- [ ] Build schema validation pipeline
- [ ] Implement payload normalization (rail-specific → canonical)
- [ ] Build deduplication logic (composite key check)
- [ ] Implement dead-letter routing for invalid events
- [ ] Add rate limiting
- [ ] Write unit + integration tests

### 1.5 Orchestrator Agent (Basic)
- [ ] Implement case state machine driver
- [ ] Build sequential workflow: receive → investigate → decide
- [ ] Add timeout management (per-step budgets)
- [ ] Implement basic priority queue (FIFO with priority lanes)
- [ ] Write orchestration flow tests

---

## Phase 2: Investigation & Decision Engine (Week 2-3)

### Milestone: System can auto-resolve simple cases (insufficient funds, duplicate) and escalate complex ones

### 2.1 Investigation Agent Framework
- [ ] Define `BaseInvestigator` abstract class with standard interface
- [ ] Implement evidence collection timeout handling
- [ ] Build parallel investigation dispatcher
- [ ] Implement circuit breaker for external service calls
- [ ] Create `EvidenceBundle` aggregator

### 2.2 Implement Core Investigators
- [ ] **Transaction State Investigator** — query payment status (stubbed/mocked)
- [ ] **Account & Balance Investigator** — verify account state and funds
- [ ] **Beneficiary Validation Investigator** — validate routing details
- [ ] **Duplicate Detection Investigator** — find matching payments
- [ ] **Network Status Investigator** — check rail availability
- [ ] **Retry History Investigator** — retrieve prior attempts
- [ ] **Compliance Investigator** — check hold status
- [ ] Write per-investigator tests with mocked dependencies

### 2.3 Decision Engine
- [ ] Design rule-based decision framework (configurable rules)
- [ ] Implement exception-type-specific rule sets:
  - Insufficient funds → HOLD_PENDING_FUNDS
  - Duplicate confirmed → CANCEL_SAFELY
  - Beneficiary error + auto-correctable → REPAIR_AND_RETRY
  - Network outage + transient → AUTO_RETRY with backoff
  - Compliance hold → ESCALATE_COMPLIANCE
  - Cut-off miss → DEFER_TO_NEXT_CYCLE
  - Uncertain retry → investigate further or ESCALATE
- [ ] Implement confidence scoring based on evidence quality
- [ ] Add risk assessment (amount thresholds, client tier)
- [ ] Implement determinism guarantee (same input → same output)
- [ ] Build justification generator (human-readable explanations)
- [ ] Write decision rule tests with evidence fixtures

### 2.4 Egress Executor Agent
- [ ] Implement action executor with idempotency keys
- [ ] Build pre-execution safety checks
- [ ] Implement retry action (with duplicate guard)
- [ ] Implement hold action (update case status)
- [ ] Implement cancel action (safe reversal trigger)
- [ ] Implement escalation action (route to queue)
- [ ] Add rollback on partial failure
- [ ] Write execution tests

---

## Phase 3: Async Operations, Feedback & Observability (Week 3-5)

### Milestone: Full end-to-end flow with notifications, retry scheduling, replay, and monitoring

### 3.1 Async Post-Decision Agent
- [ ] Implement notification dispatcher (email/SMS stubs)
- [ ] Build retry scheduler (exponential backoff with jitter)
- [ ] Implement SLA timer management
- [ ] Add case status update broadcaster
- [ ] Implement metrics emission

### 3.2 Feedback & Replay Agent
- [ ] Implement status event correlation (match new events to open cases)
- [ ] Build decision replay engine (re-evaluate with new evidence)
- [ ] Handle human override incorporation
- [ ] Implement case re-opening logic
- [ ] Build outcome tracking (decision success/failure rates)
- [ ] Write replay scenario tests

### 3.3 Observability Stack
- [ ] Integrate OpenTelemetry for distributed tracing
- [ ] Add structured logging with correlation IDs to all agents
- [ ] Define and emit key metrics:
  - Case throughput (cases/minute)
  - Resolution time (P50, P95, P99)
  - Auto-resolution rate (% resolved without human)
  - Confidence distribution
  - Error rate by agent
- [ ] Create Grafana dashboards (or dashboard configs)
- [ ] Set up alerting rules (SLA breach, error spike, low confidence)

### 3.4 Audit Trail
- [ ] Implement immutable audit log writer
- [ ] Add audit entries at every decision point
- [ ] Build audit query API (by case, payment, time range)
- [ ] Implement audit trail replay viewer
- [ ] Write audit completeness tests

---

## Phase 4: Production Hardening & Deliverables (Week 5-8)

### Milestone: Production-ready system with full documentation and sample traces

### 4.1 Safety Controls
- [ ] Implement global kill switch (disable auto-resolution)
- [ ] Add per-rail and per-exception-type kill switches
- [ ] Implement degraded mode (all cases → human review)
- [ ] Add amount-based routing (high-value → manual review)
- [ ] Implement rate limits (max retries per payment per hour)
- [ ] Build circuit breaker dashboard

### 4.2 Configuration Management
- [ ] Externalize all thresholds and rules to config files
- [ ] Implement hot-reload for rule changes
- [ ] Add per-rail configuration profiles
- [ ] Build configuration validation on startup
- [ ] Document all configurable parameters

### 4.3 End-to-End Testing
- [ ] Build E2E test harness with simulated payment environment
- [ ] Create test scenarios for all 7 exception types
- [ ] Implement chaos testing (agent failures, timeouts, partial data)
- [ ] Performance test: measure P99 latency under load
- [ ] Idempotency test: replay same events, verify no duplicate actions

### 4.4 Sample End-to-End Traces
- [ ] **Trace 1**: Insufficient funds → auto-hold → funds arrive → auto-retry → resolved
- [ ] **Trace 2**: Duplicate payment → detected → cancelled safely → client notified
- [ ] **Trace 3**: Incorrect IFSC → auto-corrected → retry → success
- [ ] **Trace 4**: Compliance hold → escalated → human approves → released
- [ ] **Trace 5**: Network outage → retry with backoff → succeeds on 3rd attempt
- [ ] **Trace 6**: Cut-off miss → deferred → re-queued for next cycle → processed
- [ ] **Trace 7**: Uncertain retry → investigation → found duplicate risk → held → human review
- [ ] Document each trace with timing, decisions, and evidence used

### 4.5 Documentation Deliverables
- [ ] Architecture document (complete — see `docs/architecture.md`)
- [ ] Agent catalogue with contracts and boundaries
- [ ] Decision and orchestration workflow diagrams
- [ ] Threshold and escalation notes document
- [ ] Production readiness plan
- [ ] Assumptions and trade-offs document
- [ ] API documentation (OpenAPI spec)
- [ ] Operations runbook

---

## Technical Stack

| Layer | Technology | Justification |
|-------|-----------|---------------|
| Language | Python 3.12+ | Rich ecosystem for AI/agents, async-native, fast prototyping |
| Framework | FastAPI | Async, typed, auto-docs, excellent for agent APIs |
| Workflow | Temporal (or custom state machine) | Durable execution, visibility, retry built-in |
| Message Bus | Redis Streams (dev) / Kafka (prod) | Simplicity for prototype, scalability for prod |
| Database | PostgreSQL 16 | ACID, JSONB, partitioning for audit |
| Cache | Redis | Idempotency keys, distributed locks, semaphores |
| LLM SDK | LiteLLM (unified interface) | Multi-provider abstraction, failover, cost tracking |
| LLM Primary | OpenAI GPT-4o (decision) / GPT-4o-mini (routing) | Best structured output adherence, lowest hallucination rate |
| LLM Fallback | Anthropic Claude 3.5 Sonnet / Haiku | Failover provider, strong reasoning, different failure modes |
| Guardrails | Pydantic + custom validators | Schema enforcement on all LLM outputs |
| Observability | OpenTelemetry + Prometheus + Grafana | Standard stack, LLM call tracing included |
| Testing | pytest + hypothesis | Property-based testing for decision rules |
| Containers | Docker + Docker Compose | Local dev parity |
| CI/CD | GitHub Actions | Automated testing and linting |

---

## LLM Integration Plan

### Phase 1: No LLM — Pure Rule Engine
All decisions made by deterministic rules. This establishes the baseline:
- Measurable decision accuracy on test cases
- Latency baseline without LLM overhead
- Identifies which cases the rule engine cannot handle (these become LLM candidates)

### Phase 2: LLM as Advisor (Shadow Mode)
LLM runs in parallel with rule engine but its output is NOT used:
- Compare LLM recommendation vs. rule engine recommendation
- Measure agreement rate (should be >90% on simple cases)
- Identify cases where LLM adds value (complex evidence synthesis)
- Establish LLM latency and cost baselines

### Phase 3: LLM with Guardrails (Active)
LLM decisions are used for cases the rule engine cannot handle:
- Rule engine handles simple, clear-cut cases (80% of volume)
- LLM handles complex, multi-evidence cases (20% of volume)
- All LLM decisions pass through guardrail pipeline before execution
- Human review required for LLM decisions on high-value transactions

### Phase 4: LLM Optimization
- Fine-tune prompts based on Phase 3 decision outcomes
- Identify cases where LLM consistently outperforms rules → graduate to auto-resolve
- Identify cases where LLM consistently fails → add specific rules, remove from LLM path
- Cost optimization: can cheaper model handle specific case types?

---

## Guardrail Implementation Plan

### Sprint 1-2: Foundation Guardrails
- [ ] PII masking utility (mask before LLM, unmask for execution)
- [ ] Structured output validator (JSON Schema enforcement on LLM responses)
- [ ] Action allowlist validator (reject any action not in enum)
- [ ] Token budget enforcer (hard cap on input/output tokens per call)
- [ ] LLM call logger (request/response with masked PII for audit)

### Sprint 2-3: Safety Guardrails
- [ ] Confidence floor enforcement (low confidence → auto-escalate)
- [ ] Contradiction detector (LLM vs. rule engine disagreement → escalate)
- [ ] Hallucination detector (check if LLM references non-existent evidence IDs)
- [ ] Amount threshold gate (high-value → require human approval)
- [ ] Retry budget tracker (max N LLM calls per case)

### Sprint 3-4: Operational Guardrails
- [ ] LLM provider failover (OpenAI → Anthropic → rule-only degradation)
- [ ] Rate limiter with priority queue (critical cases get LLM slots first)
- [ ] Cost circuit breaker (monthly budget enforcement)
- [ ] Model version pinning for reproducibility
- [ ] A/B testing framework (compare model versions on live traffic)

---

## Concurrency Implementation Plan

### Sprint 1: Single-Threaded Foundation
- [ ] Synchronous processing: one case at a time
- [ ] Establish correctness before optimizing for throughput
- [ ] All state transitions are atomic and validated

### Sprint 2: Async I/O for Investigators
- [ ] Convert investigators to async (asyncio.gather for parallel fan-out)
- [ ] Add per-investigator timeouts (asyncio.wait_for)
- [ ] Implement evidence bundle aggregator (fan-in after fan-out)
- [ ] Test: verify parallel investigation does not corrupt shared state

### Sprint 3: Multi-Case Parallelism
- [ ] Kafka consumer with multiple partitions
- [ ] Worker pool processing cases in parallel
- [ ] Optimistic locking on case state updates
- [ ] Distributed lock (Redis) for idempotent execution
- [ ] Backpressure: if workers are saturated, stop consuming (Kafka consumer pause)

### Sprint 4: LLM Concurrency Controls
- [ ] Semaphore for max concurrent LLM calls (configurable, default 20)
- [ ] Token bucket rate limiter per provider
- [ ] Priority queue for LLM slots (CRITICAL cases first)
- [ ] Graceful degradation: overflow cases use rule-only path
- [ ] Monitor: LLM queue depth, wait time, degradation frequency

---

## Key Design Decisions

### D1: Temporal vs. Custom State Machine
**Decision**: Start with custom state machine for Phase 1-2, migrate to Temporal for Phase 3-4.
**Rationale**: Reduces initial complexity; Temporal adds significant value for retry, timeout, and visibility but has learning curve.

### D2: Rule-Based vs. LLM-Based Decision Engine
**Decision**: Hybrid — rule engine as primary, LLM as advisor for complex cases.
**Rationale**: Rules are auditable, deterministic, explainable. LLM handles edge cases and generates justifications. LLM never acts without guardrail validation. This gives us the best of both worlds: speed and safety for common cases, intelligence for rare ones.

### D3: Why GPT-4o / Claude Sonnet for Decision Engine
**Decision**: Use frontier models (not fine-tuned smaller models) for decision reasoning.
**Rationale**:
- Payment decisions require multi-step logical reasoning (evidence A contradicts evidence B → what does this imply?)
- Frontier models have lowest hallucination rate on structured reasoning tasks
- Cost per decision is ~$0.01-0.03 — negligible vs. cost of a wrong payment action
- Fine-tuned smaller models lack the generalization needed for novel exception types
- Temperature 0 + structured output mode gives sufficient determinism

### D4: Why GPT-4o-mini / Haiku for Orchestration
**Decision**: Use fast/cheap models for routing and summarization tasks.
**Rationale**:
- Orchestrator decisions are simple: "which investigators to activate" (choosing from a list)
- Latency matters more than reasoning depth here (orchestrator is on the critical path)
- 10-20x cheaper per token, P95 latency < 300ms vs. ~2s for frontier models
- If routing is wrong, investigators return INCONCLUSIVE — self-correcting

### D5: Why No LLM for Investigators
**Decision**: Investigators are pure deterministic code — no LLM.
**Rationale**:
- Investigators RETRIEVE facts. Facts are not generated, they're looked up.
- Adding LLM introduces hallucination risk at the evidence layer (catastrophic — bad evidence → bad decisions)
- API calls have predictable latency (50-200ms). LLM adds 500ms-2000ms.
- If an API is down, the truthful answer is "INCONCLUSIVE", never an LLM-generated guess

### D6: Sync vs. Async Agent Communication
**Decision**: Async message-passing for all inter-agent communication.
**Rationale**: Decoupling, failure isolation, natural retry semantics, audit trail.

### D7: Single Process vs. Distributed Agents
**Decision**: Single-process in development, distributed in production.
**Rationale**: Faster iteration; agent boundaries are logical (modules), not physical (services) until scaling demands it.

### D8: Real External Integrations vs. Stubs
**Decision**: All external systems stubbed/mocked with realistic behavior.
**Rationale**: Problem statement explicitly excludes production integrations to real rails.

### D9: Multi-Provider LLM Strategy
**Decision**: Primary (OpenAI) + Fallback (Anthropic) + Degradation (rule-only).
**Rationale**:
- No single LLM provider has 100% uptime
- Different providers have different failure modes (useful for redundancy)
- Rule-only degradation means system NEVER stops — just loses LLM intelligence temporarily
- Cost arbitrage: can route low-priority cases to cheaper provider

### D10: Concurrency by Payment ID Partitioning
**Decision**: Kafka partitioned by payment_id ensures all events for same payment hit same worker.
**Rationale**:
- Eliminates need for distributed locks on most operations
- Duplicate detection is guaranteed coherent (no split-brain)
- Different payments are fully independent — scales horizontally
- Trade-off: hot partitions if one payment generates many events (rare, handled by per-partition rate limiting)

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| LLM hallucinates an invalid action | Incorrect payment operation | Action allowlist guardrail + schema validation |
| LLM provider outage during peak | Cases pile up without decisions | Multi-provider failover + rule-only degradation path |
| LLM produces non-deterministic decisions | Audit replay fails | Temperature 0 + model version pinning + evidence snapshotting |
| Decision engine produces incorrect action | Duplicate payment / lost funds | Confidence thresholds + human approval for risky actions |
| Agent timeout cascade | Cases stuck indefinitely | SLA timers + automatic escalation on timeout |
| Duplicate event processing | Double-counting exceptions | Idempotency at ingress + egress |
| State corruption from concurrent updates | Inconsistent case state | Optimistic locking + state machine validation |
| Configuration error deploys bad rules | Widespread incorrect decisions | Config validation + gradual rollout + kill switch |
| LLM cost explosion | Budget overrun | Per-case cost cap + monthly budget circuit breaker |
| Prompt injection via error messages | Agent hijacking | Sanitize all external text before prompt inclusion |
| Investigation stampede after restart | System overload | Gradual drain startup (10% → 100% over 60s) |
| Kafka partition hotspot | One worker overwhelmed | Monitor partition lag; rebalance if needed |

---

## Success Criteria

1. **Functional**: System correctly handles all 7 exception types end-to-end
2. **Performance**: P95 auto-resolution time < 30 seconds for simple cases
3. **Safety**: Zero duplicate payments or incorrect fund movements in testing
4. **Auditability**: Every decision traceable with evidence and justification
5. **Determinism**: Replay any case with same evidence → same decision
6. **Resilience**: System degrades gracefully (escalates to human) on any component failure
7. **LLM Safety**: Zero hallucinated actions pass guardrails in testing
8. **Concurrency**: System handles 100+ concurrent cases without race conditions
9. **Cost Control**: Average LLM cost per case < $0.05
10. **Failover**: Seamless provider switch within 5s of primary failure detection

---

## Sprint Breakdown (if running 2-week sprints)

| Sprint | Focus | Key Deliverable |
|--------|-------|----------------|
| Sprint 1 | Models, State, Ingress, Basic Orchestration | Single case flows through pipeline |
| Sprint 2 | Investigators, Decision Engine, Egress | Auto-resolution of simple cases |
| Sprint 3 | Async ops, Feedback, Observability | Full loop with retry and replay |
| Sprint 4 | Safety, Config, E2E testing, Documentation | Production-ready deliverable |

---

## Immediate Next Steps

1. Initialize the project with directory structure and dependencies
2. Implement core data models (`ExceptionCase`, `Evidence`, `Decision`)
3. Build the case state machine
4. Implement Ingress Gateway with deduplication
5. Build a single happy-path flow: ingress → orchestrate → investigate (stubbed) → decide → egress

This gets a working skeleton end-to-end in the first sprint, which can then be deepened iteratively.

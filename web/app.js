(() => {
    'use strict';

    const API_BASE = '';
    let demoResults = [];
    let currentCaseIndex = 0;

    // --- Server Status Check ---
    async function checkServer() {
        const dot = document.querySelector('.status-dot');
        const text = document.querySelector('.status-text');
        try {
            const res = await fetch(`${API_BASE}/api/events`);
            if (res.ok) {
                dot.classList.add('online');
                dot.classList.remove('offline');
                text.textContent = 'Server Online';
            } else { throw new Error(); }
        } catch {
            dot.classList.add('offline');
            dot.classList.remove('online');
            text.textContent = 'Server Offline';
        }
    }
    checkServer();

    // --- Tab Navigation ---
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
            tab.classList.add('active');
            const view = document.getElementById(tab.dataset.tab);
            if (view) view.classList.add('active');
        });
    });

    // --- Agent Catalogue ---
    const AGENTS = [
        { name: 'Ingress Guardian', role: 'Gatekeeper & Normalizer', model: null, traits: ['Meticulous', 'Skeptical', 'Protective'], desc: 'Assumes all incoming data is potentially malformed. Rejects aggressively - false rejection safer than bad data flowing through. Never passes unvalidated data.' },
        { name: 'The Conductor', role: 'Workflow Orchestrator', model: 'GPT-4o-mini', traits: ['Calm', 'Decisive', 'Time-aware'], desc: 'Constantly monitors SLA timers. Parallelizes investigations aggressively. Escalates early rather than risking SLA breach. Timeout is a decision, not an error.' },
        { name: 'The Detectives (x7)', role: 'Evidence Gatherers', model: null, traits: ['Thorough', 'Factual', 'Read-only'], desc: 'Reports ONLY what they find. Returns INCONCLUSIVE when ambiguous - never guesses. Operates under strict 5s time budget. Never modifies state.' },
        { name: 'The Judge', role: 'Decision Engine', model: 'GPT-4o', traits: ['Analytical', 'Conservative', 'Principled'], desc: 'Weighs evidence by confidence. When uncertain, HOLD or ESCALATE. Same evidence always yields same decision. Generates explicit audit justification.' },
        { name: 'Safety Gate', role: 'Guardrail Pipeline', model: null, traits: ['Strict', 'Vigilant', 'Unyielding'], desc: 'Validates every decision against allowlist, confidence floor, amount threshold, and hallucination markers. Can override LLM decisions.' },
        { name: 'The Operator', role: 'Egress Executor', model: null, traits: ['Methodical', 'Cautious', 'Idempotent'], desc: 'Verifies pre-conditions before EVERY action. Uses idempotency keys on every external call. On any ambiguity: HOLD, never guess forward.' },
        { name: 'The Follow-Up', role: 'Async Coordinator', model: 'GPT-4o-mini', traits: ['Reliable', 'Non-blocking', 'Persistent'], desc: 'Handles notifications, retry scheduling, SLA timers. Never blocks the primary resolution path. Eventual consistency is acceptable here.' },
        { name: 'The Historian', role: 'Feedback Analyzer', model: 'GPT-4o', traits: ['Reflective', 'Pattern-seeking', 'Thorough'], desc: 'Correlates new events to historical cases. Identifies when new evidence contradicts prior decisions. Tracks outcome patterns for rule refinement.' },
    ];

    function renderAgents() {
        const grid = document.getElementById('agents-grid');
        grid.innerHTML = AGENTS.map(a => `
            <div class="agent-card">
                <div class="agent-card-top">
                    <span class="agent-name">${a.name}</span>
                    <span class="agent-model ${a.model ? 'has-llm' : 'no-llm'}">${a.model || 'No LLM'}</span>
                </div>
                <div class="agent-role">${a.role}</div>
                <div class="agent-desc">${a.desc}</div>
                <div class="agent-traits">${a.traits.map(t => `<span class="trait">${t}</span>`).join('')}</div>
            </div>
        `).join('');
    }
    renderAgents();

    // --- Demo ---
    function getStatusClass(status) {
        if (status === 'RESOLVED') return 'status-resolved';
        if (status === 'ESCALATED') return 'status-escalated';
        if (status === 'HELD') return 'status-held';
        if (status === 'MONITORING') return 'status-monitoring';
        return '';
    }

    function renderCard(r, idx) {
        if (!r || r.status === 'DEDUPLICATED') return '';
        const d = r.decision || {};
        const delay = idx * 60;
        return `
            <div class="case-card" style="animation-delay:${delay}ms" data-idx="${idx}">
                <div class="case-card-header">
                    <span class="case-type type-${r.exception_type}">${r.exception_type.replace(/_/g, ' ')}</span>
                    <span class="case-amount">${r.currency} ${Number(r.amount).toLocaleString()}</span>
                </div>
                <div class="case-body">
                    <div class="payment-id">${r.payment_id} &middot; ${r.payment_rail} &middot; ${r.client_id}</div>
                    <div class="justification">${d.justification ? d.justification.substring(0, 120) : ''}</div>
                </div>
                <div class="case-footer">
                    <span class="action-tag ${getStatusClass(r.final_status)}">${r.action_taken || 'PENDING'}</span>
                    <span class="case-meta">${r.elapsed_ms}ms &middot; ${r.evidence?.length || 0} ev &middot; ${d.confidence || '-'}</span>
                </div>
            </div>`;
    }

    function renderDemoResults() {
        const grid = document.getElementById('cases-grid');
        const cards = demoResults.map((r, i) => renderCard(r, i)).join('');
        grid.innerHTML = cards || '<div class="empty-state"><p>No results yet</p></div>';

        grid.querySelectorAll('.case-card').forEach(card => {
            card.addEventListener('click', () => {
                document.querySelector('.tab[data-tab="traces"]').click();
                setTimeout(() => {
                    const idx = parseInt(card.dataset.idx);
                    renderTraces(demoResults, idx);
                }, 100);
            });
        });
    }

    function updateStats(data) {
        const el = document.getElementById('demo-stats');
        const s = data.stats;
        el.innerHTML = `<strong>${data.successful}</strong>/${data.total} resolved &middot; <strong>${s.guardrail_violations}</strong> guardrail override(s) &middot; avg ${Math.round(demoResults.reduce((a,r) => a + (r?.elapsed_ms||0), 0) / demoResults.length)}ms`;
    }

    document.getElementById('run-all-btn').addEventListener('click', async () => {
        const btn = document.getElementById('run-all-btn');
        btn.disabled = true;
        btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin"><path d="M12 2v4m0 12v4m-7.07-3.93l2.83-2.83m8.48-8.48l2.83-2.83M2 12h4m12 0h4m-3.93 7.07l-2.83-2.83M7.76 7.76L4.93 4.93"/></svg> Processing...';
        document.getElementById('cases-grid').innerHTML = '<div class="empty-state"><p>Running 10 exceptions through the pipeline...</p></div>';

        try {
            const res = await fetch(`${API_BASE}/api/process-all`, { method: 'POST' });
            if (!res.ok) throw new Error(`Server error: ${res.status}`);
            const data = await res.json();
            demoResults = data.results;
            currentCaseIndex = demoResults.length;
            renderDemoResults();
            updateStats(data);
            renderExplainability(demoResults);
        } catch (err) {
            document.getElementById('cases-grid').innerHTML = `<div class="empty-state"><p style="color:var(--danger)">Error: ${err.message}</p><p class="empty-hint">Make sure the server is running: python -m uvicorn src.server:app --port 8000</p></div>`;
        }

        btn.disabled = false;
        btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> Process All 10 Exceptions';
    });

    document.getElementById('run-one-btn').addEventListener('click', async () => {
        if (currentCaseIndex >= 10) { currentCaseIndex = 0; demoResults = []; }
        try {
            const res = await fetch(`${API_BASE}/api/process`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ event_index: currentCaseIndex }) });
            if (!res.ok) throw new Error(`Server error: ${res.status}`);
            const data = await res.json();
            demoResults.push(data);
            currentCaseIndex++;
            renderDemoResults();
        } catch (err) {
            document.getElementById('cases-grid').innerHTML = `<div class="empty-state"><p style="color:var(--danger)">Error: ${err.message}</p></div>`;
        }
    });

    document.getElementById('reset-btn').addEventListener('click', () => {
        demoResults = [];
        currentCaseIndex = 0;
        document.getElementById('cases-grid').innerHTML = `<div class="empty-state"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.4"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg><p>Click "Process All 10 Exceptions" to run the demo</p><p class="empty-hint">The backend processes 10 payment exceptions across 7 types, 4 rails, and 3 currencies</p></div>`;
        document.getElementById('demo-stats').innerHTML = '';
        document.getElementById('trace-content').innerHTML = '<div class="empty-state"><p>Run the demo first, then select a case to inspect its full trace</p></div>';
        document.getElementById('explain-examples').innerHTML = '<div class="empty-state" style="min-height:200px"><p>Run the Live Demo first, then return here to see generated explanations</p></div>';
    });

    // --- Traces ---
    function renderTraces(results, activeIdx = 0) {
        const container = document.getElementById('trace-content');
        const valid = results.filter(r => r && r.status !== 'DEDUPLICATED');
        if (valid.length === 0) {
            container.innerHTML = '<div class="empty-state"><p>Run the demo first to generate traces</p></div>';
            return;
        }

        const listHtml = valid.map((r, i) => `
            <div class="trace-item ${i === activeIdx ? 'active' : ''}" data-idx="${i}">
                <div class="trace-item-type">${r.exception_type.replace(/_/g, ' ')}</div>
                <div class="trace-item-id">${r.payment_id}</div>
            </div>
        `).join('');

        container.innerHTML = `<div class="trace-panel"><div class="trace-list">${listHtml}</div><div class="trace-detail" id="trace-detail-inner"></div></div>`;

        container.querySelectorAll('.trace-item').forEach(item => {
            item.addEventListener('click', () => {
                container.querySelectorAll('.trace-item').forEach(x => x.classList.remove('active'));
                item.classList.add('active');
                renderSingleTrace(valid[parseInt(item.dataset.idx)]);
            });
        });

        renderSingleTrace(valid[activeIdx]);
    }

    function renderSingleTrace(r) {
        const el = document.getElementById('trace-detail-inner');
        if (!el || !r) return;
        const d = r.decision || {};
        const steps = r.steps || [];
        const evidence = r.evidence || [];

        let html = `<div class="trace-header"><h3>${r.exception_type.replace(/_/g, ' ')}</h3><p>${r.payment_id} &middot; ${r.currency} ${Number(r.amount).toLocaleString()} &middot; ${r.payment_rail} &middot; Priority: ${r.priority}</p></div>`;

        html += '<div class="trace-timeline">';
        steps.forEach(step => {
            let cls = 'trace-step';
            if (step.includes('ERROR') || step.includes('GUARDRAIL')) cls += ' s-error';
            else if (step.includes('EGRESS') || step.includes('RESOLVED')) cls += ' s-success';
            else if (step.includes('DECISION')) cls += ' s-info';
            else if (step.includes('INVESTIGATION')) cls += ' s-warning';
            html += `<div class="${cls}"><div class="trace-step-text">${step}</div></div>`;
        });
        html += '</div>';

        if (evidence.length) {
            html += `<h4 style="font-size:12px;margin-top:16px;margin-bottom:8px;color:var(--text-secondary)">Evidence Bundle (${evidence.length})</h4><div class="trace-evidence">`;
            evidence.forEach(e => {
                const cc = e.confidence === 'HIGH' ? 'conf-high' : e.confidence === 'MEDIUM' ? 'conf-medium' : 'conf-low';
                html += `<div class="trace-ev-item"><strong>${e.source.replace('Investigator','')}</strong><span class="conf ${cc}">${e.confidence}</span> &middot; ${e.type.replace(/_/g,' ')}</div>`;
            });
            html += '</div>';
        }

        if (d.justification) {
            html += `<div class="trace-decision-box"><h4>Decision: ${d.action}</h4><p>${d.justification}</p><div class="meta">confidence: ${d.confidence} | risk: ${d.risk_level} | approval: ${d.requires_approval} | rules: ${Array.isArray(d.rules_applied) ? d.rules_applied.join(', ') : d.rules_applied || 'N/A'}</div></div>`;
        }

        el.innerHTML = html;
    }

    // CSS for spinner
    const style = document.createElement('style');
    style.textContent = `@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}.spin{animation:spin 1s linear infinite}`;
    document.head.appendChild(style);

    // --- Explainability ---
    const CLIENT_MESSAGES = {
        'HOLD_PENDING_FUNDS': (r) => `Your payment of ${r.currency} ${Number(r.amount).toLocaleString()} is temporarily held pending fund availability. Expected resolution: within 4 hours.`,
        'CANCEL_SAFELY': (r) => `A duplicate payment of ${r.currency} ${Number(r.amount).toLocaleString()} was detected and safely cancelled. No funds were debited. No action required.`,
        'REPAIR_AND_RETRY': (r) => `Your payment of ${r.currency} ${Number(r.amount).toLocaleString()} encountered a routing issue. It has been automatically corrected and is being reprocessed.`,
        'ESCALATE_COMPLIANCE': (r) => `Your payment of ${r.currency} ${Number(r.amount).toLocaleString()} is under review per regulatory requirements. A compliance officer will process it within 24 hours.`,
        'ESCALATE_OPERATIONS': (r) => `Your payment of ${r.currency} ${Number(r.amount).toLocaleString()} requires additional review. Our operations team will resolve it within 2 hours.`,
        'AUTO_RETRY': (r) => `Your payment of ${r.currency} ${Number(r.amount).toLocaleString()} experienced a temporary network issue. It is being automatically retried.`,
        'HOLD_PENDING_INPUT': (r) => `Your payment of ${r.currency} ${Number(r.amount).toLocaleString()} is temporarily on hold. We will retry once the network issue is resolved.`,
        'DEFER_TO_NEXT_CYCLE': (r) => `Your payment of ${r.currency} ${Number(r.amount).toLocaleString()} was received after today's processing cutoff. It will be processed in the next business cycle.`,
    };

    function renderExplainability(results) {
        const container = document.getElementById('explain-examples');
        const valid = results.filter(r => r && r.status !== 'DEDUPLICATED' && r.decision);
        if (!valid.length) {
            container.innerHTML = '<div class="empty-state" style="min-height:200px"><p>No results to explain yet</p></div>';
            return;
        }

        container.innerHTML = valid.map(r => {
            const d = r.decision;
            const action = d.action || r.action_taken;
            const clientMsg = CLIENT_MESSAGES[action] ? CLIENT_MESSAGES[action](r) : `Your payment is being processed. Current status: ${r.final_status}.`;
            const rules = Array.isArray(d.rules_applied) ? d.rules_applied.join(', ') : (d.rules_applied || 'N/A');
            const evidenceSummary = (r.evidence || []).map(e => `${e.source.replace('Investigator','')} (${e.confidence})`).join(', ');

            return `
                <div class="explain-card">
                    <div class="explain-card-header">
                        <span class="explain-card-type case-type type-${r.exception_type}">${r.exception_type.replace(/_/g,' ')}</span>
                        <span class="explain-card-action">${action}</span>
                    </div>
                    <div class="explain-section">
                        <div class="explain-section-title">Internal Justification (Full)</div>
                        <div class="explain-justification">${d.justification}</div>
                    </div>
                    <div class="explain-section">
                        <div class="explain-section-title">Operations Summary</div>
                        <div class="explain-ops"><strong>${action}</strong> &mdash; ${d.justification.split('.')[0]}. Evidence: ${evidenceSummary}. Risk: ${d.risk_level}.</div>
                    </div>
                    <div class="explain-section">
                        <div class="explain-section-title">Client-Facing Message</div>
                        <div class="explain-client">${clientMsg}</div>
                    </div>
                    <div class="explain-meta">
                        <div class="explain-meta-item"><strong>Rules:</strong> ${rules}</div>
                        <div class="explain-meta-item"><strong>Confidence:</strong> ${d.confidence}</div>
                        <div class="explain-meta-item"><strong>Risk:</strong> ${d.risk_level}</div>
                        <div class="explain-meta-item"><strong>Approval:</strong> ${d.requires_approval ? 'Required' : 'Not required'}</div>
                        <div class="explain-meta-item"><strong>Elapsed:</strong> ${r.elapsed_ms}ms</div>
                    </div>
                </div>`;
        }).join('');
    }

})();

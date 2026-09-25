"""All eleven nodes, in one module, on purpose.

The obvious alternative -- ``app/nodes/ingest.py``, ``app/nodes/guard.py``, and so on --
is what produces a ``graph.py`` with eleven ``add_node`` calls referring to eleven names
nobody imported.  That is a ``NameError`` at import time, it is invisible until the graph
is built, and it is the single most common way this kind of project fails to start.  One
module makes the mistake unrepresentable and costs nothing in readability at this size.

The flow::

    ingest -> guard -> triage -> (fan out) investigate -> collect ┐
                         ^                                        │
                         └────────── more questions ──────────────┘
                                                                  │
                     match_runbooks -> resolve -> verify -> render -> approve -> execute
                                          ^          │
                                          └── redraft┘

``triage`` decides each round whether to fan out again or move on, so control returns to
the planner after every round.  That is what makes this an orchestration rather than a
one-shot fan-out with extra steps.
"""

import json
import os

from langgraph.types import Send, interrupt

from app.agent import run_agent
from app.evidence import audit_view, index, scan
from app.prompts import BY_AGENT
from app.state import IncidentState, surviving
from app.tools.impl import overlay

MAX_ROUNDS = int(os.environ.get("MAX_ROUNDS", "3"))
MAX_QUESTIONS = int(os.environ.get("MAX_QUESTIONS", "2"))

RISK_ORDER = {"read_only": 0, "reversible": 1, "confirm": 2, "human": 3}
VALID_RISK = set(RISK_ORDER)


def emit(event):
    """Push one frame to the SSE stream, if we are inside a run that is streaming.

    ``get_stream_writer`` raises outside a runnable context -- in a unit test, or at
    import time. Emitting is a nicety; failing to emit must never take a node down.
    """
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        if writer:
            writer(event)
    except Exception:
        pass


def _agent_summary(records, quarantined):
    """What the planner is shown. Never the full evidence -- it has no tools for a reason."""
    logs = [r for r in records if r["kind"] == "log"]
    metrics = [r for r in records if r["kind"] == "metric"]
    runbooks = [r for r in records if r["kind"] == "runbook"]
    lines = [
        f"{len(logs)} log lines, keys log:0 to log:{len(logs)-1}" if logs else "no logs",
        "metrics: " + ", ".join(m["name"] for m in metrics),
        "runbooks: " + ", ".join(f"{r['id']} ({r['title']})" for r in runbooks),
    ]
    if quarantined:
        keys = ", ".join(q["key"] for q in quarantined)
        lines.append(
            f"{len(quarantined)} log line(s) were quarantined as instruction-shaped "
            f"and redacted before you saw them: {keys}"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 1 ingest
# ─────────────────────────────────────────────────────────────────────────────

def ingest(state: IncidentState):
    incident = state.get("incident") or {}
    evidence = incident.get("evidence", [])
    emit(
        {
            "e": "incident",
            "incident_id": incident.get("incident_id", ""),
            "severity": incident.get("severity", ""),
            "service": incident.get("service", ""),
            "alert": incident.get("alert", ""),
            "counts": {
                "logs": sum(1 for r in evidence if r["kind"] == "log"),
                "metrics": sum(1 for r in evidence if r["kind"] == "metric"),
                "runbooks": sum(1 for r in evidence if r["kind"] == "runbook"),
            },
        }
    )
    return {"evidence": audit_view(evidence), "round": 0, "replans": 0}


# ─────────────────────────────────────────────────────────────────────────────
# 2 guard
# ─────────────────────────────────────────────────────────────────────────────

def guard(state: IncidentState):
    agent_records, quarantined = scan(state.get("evidence", []))
    emit({"e": "agent", "name": "guard", "status": "running"})
    for q in quarantined:
        emit({"e": "quarantine", "key": q["key"], "rules": q["rules"], "why": q["why"], "raw": q["raw"]})
    emit({"e": "agent", "name": "guard", "status": "done", "detail": f"{len(quarantined)} quarantined"})
    return {"agent_evidence": agent_records, "quarantined": quarantined}


# ─────────────────────────────────────────────────────────────────────────────
# 3 triage -- the planner. Runs every round.
# ─────────────────────────────────────────────────────────────────────────────

def triage(state: IncidentState):
    rnd = state.get("round", 0) + 1
    emit({"e": "agent", "name": "planner", "status": "running", "detail": f"round {rnd}"})

    found = surviving(state)
    known = (
        "\n".join(f"- [{c.get('kind')}] {c.get('text')}  cites={c.get('cites')}" for c in found)
        or "nothing established yet"
    )
    incident = state.get("incident", {})

    user = f"""ALERT
{incident.get('alert','')}

SERVICE {incident.get('service','')}   SEVERITY {incident.get('severity','')}

EVIDENCE AVAILABLE
{_agent_summary(state.get('agent_evidence', []), state.get('quarantined', []))}

ESTABLISHED SO FAR (round {rnd} of at most {MAX_ROUNDS})
{known}

Decide what to ask next, or return an empty questions list if the diagnosis is complete.
"""

    out = run_agent("planner", BY_AGENT["planner"], user, state.get("agent_evidence", []))
    parsed = out["json"] or {}
    questions = [q for q in parsed.get("questions", []) if q.get("agent") in ("log", "metric")][:MAX_QUESTIONS]

    for i, q in enumerate(questions):
        q.setdefault("id", f"r{rnd}q{i+1}")

    emit(
        {
            "e": "agent",
            "name": "planner",
            "status": "done",
            "detail": parsed.get("assessment", ""),
            "questions": [q.get("question", "") for q in questions],
        }
    )

    return {
        "open_questions": questions,
        "round": rnd,
        "trace": [{"node": "triage", "round": rnd, "assessment": parsed.get("assessment", ""),
                   "hypothesis": parsed.get("leading_hypothesis", ""), "asked": len(questions)}],
        "tokens_in": out["usage"]["in"],
        "tokens_out": out["usage"]["out"],
        "cache_read": out["usage"].get("cache_read", 0),
        "cache_write": out["usage"].get("cache_write", 0),
    }


def dispatch(state: IncidentState):
    """Fan out to one investigator per open question, or move on.

    The close conditions are checked before the questions, and they are not negotiable by
    the planner: a round cap it cannot argue with, and a supported cause with nothing
    outstanding.  A planner that could decide to keep going forever eventually does.
    """
    questions = state.get("open_questions") or []
    has_cause = any(c.get("kind") == "cause" for c in surviving(state))

    if state.get("round", 0) >= MAX_ROUNDS:
        emit({"e": "agent", "name": "planner", "status": "done", "detail": f"round cap {MAX_ROUNDS} reached"})
        return "match_runbooks"

    if not questions:
        if has_cause:
            return "match_runbooks"
        # No questions and no cause is the one state the graph cannot proceed from.
        # Raising here is deliberate: returning would let the run finish with an empty
        # brief and a blank screen, which looks like success and is not.
        raise RuntimeError(
            "the planner returned no questions and no cause was established -- "
            "the run cannot produce a grounded brief from here"
        )

    return [
        Send(
            "investigate",
            {
                "question": q,
                "agent_evidence": state.get("agent_evidence", []),
                "round": state.get("round", 0),
            },
        )
        for q in questions
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 4 investigate -- the fan-out target
# ─────────────────────────────────────────────────────────────────────────────

def investigate(payload: dict):
    """One specialist answering one question.

    The ``Send`` payload **becomes this node's entire input state** -- there is no
    surrounding graph state here.  Everything this node needs was put in the payload by
    ``dispatch``, and everything it returns is merged back through the reducers on
    ``claims``, ``trace`` and the token counters.
    """
    q = payload["question"]
    who = q.get("agent", "log")
    records = payload.get("agent_evidence", [])

    emit({"e": "agent", "name": who, "status": "running", "detail": q.get("question", "")})

    user = f"""QUESTION
{q.get('question','')}

WHY IT MATTERS
{q.get('why','')}

Investigate with your tools and answer in the required JSON shape."""

    out = run_agent(who, BY_AGENT[who], user, records, on_event=emit)
    parsed = out["json"] or {}

    claims = []
    for c in parsed.get("claims", []):
        if not isinstance(c, dict):
            continue
        claims.append(
            {
                "kind": c.get("kind", "context"),
                "text": str(c.get("text", "")).strip(),
                "cites": [str(k) for k in (c.get("cites") or [])],
                "confidence": c.get("confidence", "low"),
                "by": who,
            }
        )

    emit(
        {
            "e": "agent",
            "name": who,
            "status": "done",
            "detail": parsed.get("answer", "")[:200],
            "claims": len(claims),
        }
    )

    return {
        "claims": claims,
        "trace": [
            {
                "node": "investigate",
                "agent": who,
                "question": q.get("question", ""),
                "answer": parsed.get("answer", ""),
                "calls": [{"tool": c["tool"], "input": c["input"]} for c in out["calls"]],
            }
        ],
        "tokens_in": out["usage"]["in"],
        "tokens_out": out["usage"]["out"],
        "cache_read": out["usage"].get("cache_read", 0),
        "cache_write": out["usage"].get("cache_write", 0),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5 collect -- the fan-in. defer=True, so it waits for every branch.
# ─────────────────────────────────────────────────────────────────────────────

def collect(state: IncidentState):
    """Curate the round's claims into the ledger, and drop the ungrounded ones.

    This is the only writer of ``ledger``, which is why ``ledger`` has no reducer while
    ``claims`` does. Dropping happens here, once, where it can be counted and shown.
    """
    ledger = list(state.get("ledger", []))
    known = {(c["kind"], c["text"]) for c in ledger}
    resolvable = set(index(state.get("agent_evidence", [])))

    kept, dropped = [], []
    for c in state.get("claims", []):
        real = [k for k in c.get("cites", []) if k in resolvable]
        if not real:
            dropped.append({**c, "why": "no citation resolves to a real record"})
            continue
        if (c["kind"], c["text"]) in known:
            continue
        known.add((c["kind"], c["text"]))
        kept.append({**c, "cites": real})

    ledger.extend(kept)
    emit(
        {
            "e": "agent",
            "name": "collect",
            "status": "done",
            "detail": f"{len(kept)} kept, {len(dropped)} dropped, {len(ledger)} in ledger",
        }
    )

    return {
        "ledger": ledger,
        "open_questions": [],
        "trace": [{"node": "collect", "kept": len(kept), "dropped": len(dropped),
                   "dropped_detail": dropped}],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6 match_runbooks -- deterministic, no model
# ─────────────────────────────────────────────────────────────────────────────

def match_runbooks(state: IncidentState):
    """Shortlist runbooks by term overlap with what was actually established.

    No model call. Selecting which documents to read is a retrieval problem, and letting
    a model do it from titles alone adds a token cost and a hallucination surface to a
    step that a set intersection answers correctly.
    """
    found = surviving(state)
    text = " ".join(c["text"] for c in found).lower() + " " + str(state.get("incident", {}).get("alert", "")).lower()
    words = {w.strip(".,:;()'\"") for w in text.split() if len(w) > 3}

    candidates = []
    for rec in state.get("agent_evidence", []):
        if rec.get("kind") != "runbook":
            continue
        body = f"{rec.get('title','')} {rec.get('body','')}".lower()
        rb_words = {w.strip(".,:;()'\"") for w in body.split() if len(w) > 3}
        score = len(words & rb_words)
        candidates.append(
            {
                "id": rec["id"],
                "key": rec["key"],
                "title": rec.get("title", ""),
                "score": score,
                "automatable_mitigation": rec.get("automatable_mitigation", False),
                "risk": overlay().get(rec["id"], {}).get("risk", "destructive"),
            }
        )

    candidates.sort(key=lambda c: -c["score"])
    emit(
        {
            "e": "agent",
            "name": "match",
            "status": "done",
            "detail": ", ".join(f"{c['id']}({c['score']})" for c in candidates),
        }
    )
    return {"candidates": candidates, "trace": [{"node": "match_runbooks", "candidates": candidates}]}


# ─────────────────────────────────────────────────────────────────────────────
# 7 resolve
# ─────────────────────────────────────────────────────────────────────────────

def resolve(state: IncidentState):
    emit({"e": "agent", "name": "resolver", "status": "running"})

    found = surviving(state)
    established = "\n".join(
        f"- [{c['kind']}/{c.get('confidence','?')}] {c['text']}  cites={c['cites']}" for c in found
    ) or "nothing established"
    shortlist = "\n".join(
        f"- {c['id']}  {c['title']}  automatable_mitigation={c['automatable_mitigation']}"
        for c in state.get("candidates", [])
    )

    redraft = ""
    if state.get("verdict") and not state["verdict"].get("pass"):
        problems = "; ".join(p.get("what", "") for p in state["verdict"].get("problems", []))
        redraft = f"\n\nA VERIFIER REJECTED YOUR PREVIOUS PLAN: {problems}\nAddress this."

    user = f"""ALERT
{state.get('incident',{}).get('alert','')}

ESTABLISHED
{established}

CANDIDATE RUNBOOKS -- read each with get_runbook before proposing anything
{shortlist}{redraft}

Produce the plan in the required JSON shape."""

    out = run_agent("resolver", BY_AGENT["resolver"], user, state.get("agent_evidence", []))
    parsed = out["json"] or {}

    rows = []
    for i, row in enumerate(parsed.get("plan", [])):
        if not isinstance(row, dict):
            continue
        risk = row.get("risk", "human")
        rows.append(
            {
                "id": row.get("id") or f"row:{i+1}",
                "action": str(row.get("action", "")).strip(),
                "risk": risk if risk in VALID_RISK else "human",
                "rationale": str(row.get("rationale", "")).strip(),
                "cites": [str(k) for k in (row.get("cites") or [])],
                "runbook": str(row.get("id", "")).split(":")[0],
            }
        )
    rows.sort(key=lambda r: RISK_ORDER.get(r["risk"], 9))

    decision = parsed.get("decision", "insufficient_evidence")
    if decision not in ("automate", "escalate", "insufficient_evidence"):
        decision = "insufficient_evidence"

    emit({"e": "agent", "name": "resolver", "status": "done", "detail": decision, "rows": len(rows)})

    return {
        "plan": rows,
        "decision": decision,
        "trace": [
            {
                "node": "resolve",
                "decision": decision,
                "summary": parsed.get("summary", ""),
                "rejected": parsed.get("rejected", []),
                "escalate_because": parsed.get("escalate_because", ""),
                "calls": [{"tool": c["tool"], "input": c["input"]} for c in out["calls"]],
            }
        ],
        "tokens_in": out["usage"]["in"],
        "tokens_out": out["usage"]["out"],
        "cache_read": out["usage"].get("cache_read", 0),
        "cache_write": out["usage"].get("cache_write", 0),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 8 verify
# ─────────────────────────────────────────────────────────────────────────────

def verify(state: IncidentState):
    emit({"e": "agent", "name": "verifier", "status": "running"})

    found = surviving(state)
    claims = "\n".join(f"- [{c['kind']}] {c['text']}  cites={c['cites']}" for c in found)
    plan = "\n".join(
        f"- {r['id']} [{r['risk']}] {r['action']}  cites={r['cites']}" for r in state.get("plan", [])
    ) or "no actions proposed"

    user = f"""DECISION  {state.get('decision','')}

CLAIMS
{claims}

PLAN
{plan}

Check grounding, leaps, the plan and contradictions. Return the required JSON."""

    out = run_agent("verifier", BY_AGENT["verifier"], user, state.get("agent_evidence", []))
    parsed = out["json"] or {"pass": True, "fails": None, "problems": []}

    passed = bool(parsed.get("pass", True))
    fails = parsed.get("fails") if not passed else None
    if fails not in ("evidence", "plan", None):
        fails = "plan"

    verdict = {
        "pass": passed,
        "fails": fails,
        "problems": parsed.get("problems", []),
        "note": parsed.get("note", ""),
    }

    emit(
        {
            "e": "agent",
            "name": "verifier",
            "status": "done",
            "detail": "pass" if passed else f"fail: {fails}",
            "problems": len(verdict["problems"]),
        }
    )

    return {
        "verdict": verdict,
        "replans": state.get("replans", 0) + (0 if passed else 1),
        "trace": [{"node": "verify", "verdict": verdict}],
        "tokens_in": out["usage"]["in"],
        "tokens_out": out["usage"]["out"],
        "cache_read": out["usage"].get("cache_read", 0),
        "cache_write": out["usage"].get("cache_write", 0),
    }


def route_verdict(state: IncidentState):
    """Where a verdict sends the run.

    The order of these three tests is load-bearing. ``verify`` writes ``replans`` in the
    same superstep that produces the verdict, so a ``replans >= 1`` guard checked first
    fires on the very first failure and the redraft branch is unreachable -- the
    self-correction loop exists in the diagram and never runs. The redraft branches are
    tested first; the cap is the last word.
    """
    verdict = state.get("verdict") or {}
    if verdict.get("pass"):
        return "render"

    if state.get("replans", 0) <= 1:
        if verdict.get("fails") == "evidence":
            return "triage"
        if verdict.get("fails") == "plan":
            return "resolve"

    # Failed again after one redraft. Go to render and let the human see the problems.
    return "render"


# ─────────────────────────────────────────────────────────────────────────────
# 9 render
# ─────────────────────────────────────────────────────────────────────────────

def render(state: IncidentState):
    found = surviving(state)
    by_key = index(state.get("agent_evidence", []))
    raw_by_key = index(state.get("evidence", []))

    def resolve_cite(key):
        rec = by_key.get(key) or {}
        return {
            "key": key,
            "kind": rec.get("kind", "unknown"),
            "text": rec.get("text", "[unresolved citation]"),
            "source": rec.get("source") or rec.get("name") or rec.get("id", ""),
            "quarantined": bool(rec.get("quarantined")),
        }

    cited = sorted({k for c in found for k in c["cites"]} | {k for r in state.get("plan", []) for k in r["cites"]})
    trace = state.get("trace", [])
    resolve_trace = next((t for t in reversed(trace) if t.get("node") == "resolve"), {})

    brief = {
        "incident": state.get("incident", {}).get("incident_id", ""),
        "service": state.get("incident", {}).get("service", ""),
        "severity": state.get("incident", {}).get("severity", ""),
        "decision": state.get("decision", ""),
        "summary": resolve_trace.get("summary", ""),
        "escalate_because": resolve_trace.get("escalate_because", ""),
        "rejected": resolve_trace.get("rejected", []),
        "claims": found,
        "plan": state.get("plan", []),
        "verdict": state.get("verdict", {}),
        "citations": {k: resolve_cite(k) for k in cited},
        "quarantined": [
            {**q, "raw": raw_by_key.get(q["key"], {}).get("text", q.get("raw", ""))}
            for q in state.get("quarantined", [])
        ],
        "rounds": state.get("round", 0),
        "tokens": {
            "in": state.get("tokens_in", 0),
            "out": state.get("tokens_out", 0),
            "cache_read": state.get("cache_read", 0),
            "cache_write": state.get("cache_write", 0),
        },
    }

    emit({"e": "brief", "brief": brief})
    return {"brief": brief}


# ─────────────────────────────────────────────────────────────────────────────
# 10 approve -- the human gate
# ─────────────────────────────────────────────────────────────────────────────

def approve(state: IncidentState):
    """Stop the graph dead and wait for a person.

    ``interrupt()`` raises out of the run and the checkpointer keeps the state. Resuming
    with ``Command(resume=...)`` re-enters this node **from its first statement**, so
    nothing above the interrupt may have a side effect -- it will happen twice.
    """
    gated = [
        {"id": r["id"], "action": r["action"], "risk": r["risk"],
         "confirm_phrase": r["id"].split(":")[0] if r["risk"] == "confirm" else None}
        for r in state.get("plan", [])
        if r["risk"] != "human"
    ]

    emit({"e": "await", "decision": state.get("decision", ""), "rows": gated})

    answer = interrupt(
        {
            "question": "Approve which actions?",
            "decision": state.get("decision", ""),
            "rows": gated,
        }
    )

    approved = list((answer or {}).get("approved_ids", []))
    valid = {r["id"] for r in state.get("plan", []) if r["risk"] != "human"}
    return {"approved_ids": [i for i in approved if i in valid]}


# ─────────────────────────────────────────────────────────────────────────────
# 11 execute -- a receipt, and nothing else
# ─────────────────────────────────────────────────────────────────────────────

def execute(state: IncidentState):
    """Record what a human approved. Deliberately does not run anything.

    There is no tool in this system that changes the world, so there is nothing here to
    call. What this node produces is the audit record: which action, approved by a human,
    against which runbook, citing what. In a real deployment this is where a change ticket
    is opened -- still not where a command runs.
    """
    approved = set(state.get("approved_ids", []))
    receipts = []
    for row in state.get("plan", []):
        if row["id"] not in approved:
            continue
        receipts.append(
            {
                "id": row["id"],
                "action": row["action"],
                "risk": row["risk"],
                "runbook": row["runbook"],
                "cites": row["cites"],
                "status": "recorded",
                "note": "approved by a human operator; no command was executed by this system",
            }
        )

    skipped = [r["id"] for r in state.get("plan", []) if r["id"] not in approved]
    emit({"e": "agent", "name": "execute", "status": "done",
          "detail": f"{len(receipts)} recorded, {len(skipped)} not approved"})
    return {"receipts": receipts, "trace": [{"node": "execute", "recorded": len(receipts), "skipped": skipped}]}

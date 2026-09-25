"""The one state object every node reads and writes.

The only subtle thing here is which keys carry a reducer, and why.

``investigate`` is fanned out with ``Send``: several copies run **in the same
superstep**, in parallel, and each returns a partial state.  LangGraph merges those
partials, and for any key where two of them wrote a value it needs to be told how.
Without a reducer that is an ``InvalidUpdateError`` at runtime -- and it only fires when
the planner happens to ask more than one question, which is exactly the interesting case
and exactly the one a quick test misses.

So: a reducer on every key the fan-out writes, and no reducer on any key with a single
writer.  ``ledger`` deliberately has none -- only ``collect`` writes it, once, after the
fan-in -- and that asymmetry is the point.  It documents which parts of the graph are
concurrent by looking at the type alone.
"""

import operator
from typing import Annotated, Any, Literal, TypedDict


class Claim(TypedDict, total=False):
    """One thing an investigator believes, and what it is standing on.

    ``cites`` is a list of citation keys -- ``log:4``, ``metric:write_latency_p99``,
    ``rb:RB-01``.  A claim with an empty ``cites`` is dropped by ``collect`` before it
    reaches the resolver: an ungrounded claim is a guess wearing the costume of evidence.
    """

    kind: Literal["cause", "symptom", "ruled_out", "context"]
    text: str
    cites: list[str]
    confidence: Literal["low", "medium", "high"]
    by: str


class PlanRow(TypedDict, total=False):
    """One proposed action. The frontend renders these as the approval table."""

    id: str
    action: str
    risk: Literal["read_only", "reversible", "confirm", "human"]
    rationale: str
    cites: list[str]
    runbook: str


class IncidentState(TypedDict, total=False):
    # ---- set once by ingest, then read-only ----------------------------------------
    incident: dict[str, Any]
    evidence: list[dict[str, Any]]          # the audit view: raw, screen only
    agent_evidence: list[dict[str, Any]]    # the agent view: redacted, models see this
    quarantined: list[dict[str, Any]]

    # ---- written by the parallel fan-out: reducers required -------------------------
    claims: Annotated[list[Claim], operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]
    tokens_in: Annotated[int, operator.add]
    tokens_out: Annotated[int, operator.add]
    cache_read: Annotated[int, operator.add]
    cache_write: Annotated[int, operator.add]

    # ---- single writer each: no reducer, on purpose ---------------------------------
    ledger: list[Claim]                     # collect, once, after the fan-in
    open_questions: list[dict[str, Any]]    # triage proposes, collect clears
    round: int
    candidates: list[dict[str, Any]]
    plan: list[PlanRow]
    decision: str
    verdict: dict[str, Any]
    replans: int
    brief: dict[str, Any]
    approved_ids: list[str]
    receipts: list[dict[str, Any]]


def surviving(state: IncidentState) -> list[Claim]:
    """Claims that are still standing: grounded in at least one citation."""
    return [c for c in state.get("ledger", []) if c.get("cites")]

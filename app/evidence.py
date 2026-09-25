"""The guard: two views of the same evidence, and one of them is safe to show a model.

A log file is attacker-controlled input.  Anyone who can make your service write a log
line can put text in it, and if that text reaches a model inside the same block as your
instructions, it is indistinguishable from your instructions.  The bundled incident carries a
real example at ``log:9``.

The defence here is deliberately **not** "detect malicious intent".  That is a losing
game -- it is a natural-language classification problem with an adversary on the other
side, and the wrong answer is silent.  Instead this module asks a much narrower question
with a reliable answer:

    does this line have the *form* of an instruction, rather than the form of a log line?

Log lines report.  Instructions address a reader, claim authority, or delimit context.
Six shapes cover it, they are cheap to test, and each one is a structural property rather
than a topic.  A false positive costs one redacted line the investigator can still see
quarantined; a false negative lets an attacker's words reach the model.

The important consequence: ``agent_view()`` is the only thing any model is ever given,
and ``audit_view()`` -- the raw text, unredacted -- goes to the screen and nowhere else.
Both are returned from one call so they cannot drift apart.
"""

import re

REDACTED = "[REDACTED -- quarantined, see the audit view]"

# Each rule is (name, why it is instruction-shaped, compiled pattern).
# Every one of these matches on FORM. None of them look for a topic, a keyword list, or
# anything an attacker can avoid by rewording while keeping the same effect.
RULES = [
    (
        "role-address",
        "addresses a reader by conversational role -- log lines never do",
        re.compile(r"(?im)^\W*(system|assistant|user|human|ai)\s*[:\-]"),
    ),
    (
        "context-delimiter",
        "claims the surrounding context has ended",
        re.compile(
            r"(?i)(end\s+(of\s+)?(logs?|context|input|data)|"
            r"</?(system|instructions?|context|prompt)>|"
            r"```|\{\{|\}\}|\[/?INST\])"
        ),
    ),
    (
        "instruction-override",
        "tells the reader to disregard what it was told",
        re.compile(
            r"(?i)\b(ignore|disregard|forget|override|bypass|skip)\b[^.]{0,40}"
            r"\b(previous|prior|above|earlier|all|any|your)\b[^.]{0,20}"
            r"\b(instruction|prompt|rule|direction|context|message)"
        ),
    ),
    (
        "imperative-to-agent",
        "issues an operational command in the second person",
        re.compile(
            r"(?i)\b(you\s+(must|should|will|are\s+to)|"
            r"(please\s+)?(mark|set|treat|classify|report|declare)\s+"
            r"(this|the\s+incident|it)\s+(as\s+)?(resolved|benign|closed|safe|fixed))"
        ),
    ),
    (
        "authority-claim",
        "asserts a privilege level a log line cannot have",
        re.compile(
            r"(?i)\b(as\s+an?\s+(admin|administrator|operator|root)|"
            r"(admin|root|operator|elevated|system)\s+(override|instruction|directive|command)|"
            r"authoriz(ed|ation)\s+by\s+(system|admin))"
        ),
    ),
    (
        "embedded-action",
        "names an action to perform rather than an event that happened",
        re.compile(
            r"(?i)\b(run|execute|invoke|perform|trigger)\s+"
            r"(the\s+)?[a-z0-9_.\-]*\s*(scale-?down|shutdown|delete|drop|rm\b|prod\b)"
        ),
    ),
]


def classify(text):
    """Return the list of (rule name, reason) this text trips. Empty means it is clean."""
    return [(name, why) for name, why, pat in RULES if pat.search(text or "")]


def scan(records):
    """Split evidence into what a model may see and what it may not.

    Returns ``(agent_records, quarantined)``.  ``agent_records`` is the same list, same
    order, same keys, with the text of any tripped record replaced -- never dropped.  A
    missing record would tell the investigator nothing; a redacted one tells it that
    something was there and was withheld, which is the honest signal.
    """
    agent_records, quarantined = [], []

    for rec in records:
        hits = classify(rec.get("text", "")) if rec.get("kind") == "log" else []
        if hits:
            quarantined.append(
                {
                    "key": rec["key"],
                    "rules": [n for n, _ in hits],
                    "why": hits[0][1],
                    "raw": rec.get("text", ""),
                }
            )
            agent_records.append({**rec, "text": REDACTED, "quarantined": True})
        else:
            agent_records.append({**rec, "quarantined": False})

    return agent_records, quarantined


def agent_view(records):
    """The only evidence any model is ever shown."""
    return scan(records)[0]


def audit_view(records):
    """The raw evidence, unredacted, for the screen. Never passed to a model."""
    return list(records)


def index(records):
    """Citation key -> record, so a cited key can always be resolved back to its source."""
    return {r["key"]: r for r in records}


# ─────────────────────────────────────────────────────────────────────────────
# turning an incident file into records
# ─────────────────────────────────────────────────────────────────────────────

def to_records(source):
    """An incident file's three differently-shaped arrays -> one flat list of keyed records.

    Every citation anywhere in this system is one of these keys, so a brief that cites
    ``log:9`` can always be resolved back to the exact record a model was shown.  Both
    the CLI normaliser and the upload endpoint go through this one function, so a file
    dropped on the page gets exactly the same treatment as the one on disk.
    """
    out = []

    for line, log in enumerate(source.get("logs", [])):
        out.append(
            {
                "key": f"log:{line}",
                "kind": "log",
                "ts": log.get("ts", ""),
                "level": log.get("level", ""),
                "source": log.get("source", ""),
                "text": log.get("message", ""),
            }
        )

    for metric in source.get("metrics", []):
        note = metric.get("note", "")
        out.append(
            {
                "key": f"metric:{metric['name']}",
                "kind": "metric",
                "name": metric["name"],
                # Values are strings as captured -- "12.4s", "182 / 200", "<0.3%".
                # They stay strings. app/metrics.py is the only thing allowed to read them.
                "value": str(metric.get("value", "")),
                "baseline": str(metric.get("baseline", "")),
                "note": note,
                "text": f"{metric['name']} is {metric.get('value','')} against a baseline "
                f"of {metric.get('baseline','')}" + (f" ({note})" if note else ""),
            }
        )

    for rb in source.get("runbooks", []):
        body = rb.get("body", "")
        out.append(
            {
                "key": f"rb:{rb['id']}",
                "kind": "runbook",
                "id": rb["id"],
                "title": rb.get("title", ""),
                "body": body,
                "automatable_mitigation": bool(rb.get("automatable", False)),
                "text": f"{rb.get('title','')}. {body}",
            }
        )

    return out


def normalise(source):
    """A whole incident file -> the one shape the graph reads.

    Only the named fields are carried through. Anything else in the file is ignored
    rather than passed along, so the application's input is exactly what is listed here.
    """
    return {
        "incident_id": source.get("incident_id", "UNKNOWN"),
        "severity": source.get("severity", ""),
        "service": source.get("service", ""),
        # The alert is one sentence. The screen renders it and nothing parses it.
        "alert": source.get("alert", ""),
        "detected_at": source.get("detected_at", ""),
        "evidence": to_records(source),
    }

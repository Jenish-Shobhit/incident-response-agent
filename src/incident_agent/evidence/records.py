"""Turning an incident file into the one shape the graph reads.

An incident file has three differently-shaped arrays -- logs, metrics, runbooks. They
become one flat list of evidence records that all carry a ``key``, and every citation
anywhere in this system is one of those keys.  See ``scenarios/*/incident.json`` for the
input format.
"""


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
                # They stay strings. evidence/metrics.py is the only thing allowed to read them.
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

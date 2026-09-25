"""Turn an incident file into the only file the application reads.

The input's three differently-shaped arrays -- logs, metrics, runbooks -- become one flat
list of evidence records that all carry a ``key``.  Every citation anywhere in this
system is one of those keys, so a brief that cites ``log:9`` can always be resolved back
to the exact record a model was shown.

    python tools/normalise.py                        # the bundled example
    python tools/normalise.py path/to/incident.json  # your own

Writes ``data/incident.json``.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.evidence import normalise

SOURCE = sys.argv[1] if len(sys.argv) > 1 else "examples/incident-input.json"
OUT = "data/incident.json"


def main():
    with open(SOURCE) as f:
        incident = normalise(json.load(f))

    os.makedirs("data", exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(incident, f, indent=2)
        f.write("\n")

    counts = {}
    for rec in incident["evidence"]:
        counts[rec["kind"]] = counts.get(rec["kind"], 0) + 1
    print(f"wrote {OUT}  {len(incident['evidence'])} records  {counts}")


if __name__ == "__main__":
    main()

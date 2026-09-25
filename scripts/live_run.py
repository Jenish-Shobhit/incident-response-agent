"""Run one incident end to end in the terminal and record every frame.

    python scripts/live_run.py                     # the bundled scenario
    python scripts/live_run.py my-run path/to/incident.json

Uses whatever mode .env configures -- set MOCK=0 and a key for a live model run. The
run approves every read-only and reversible action, as a cautious operator would, and
writes runs/<name>.jsonl (every frame) and runs/<name>-brief.json. A run you did not
record is a run you have to pay for twice.
"""

import argparse
import json
import time
from pathlib import Path

from langgraph.types import Command

from incident_agent import config
from incident_agent.evidence import normalise
from incident_agent.graph import app_graph, run_config
from incident_agent.llm import describe, reset_mock


def show(frame):
    e = frame.get("e")
    if e == "agent":
        print(f"  [{frame.get('name'):9}] {frame.get('status'):8} {str(frame.get('detail', ''))[:88]}")
    elif e == "act":
        print(f"     -> {frame.get('agent')}: {frame.get('tool')}({json.dumps(frame.get('input'))[:70]})")
    elif e == "quarantine":
        print(f"  [guard    ] QUARANTINED {frame['key']} {frame['rules']}")


def stream(payload, cfg, frames):
    for mode, chunk in app_graph.stream(payload, cfg, stream_mode=["custom", "updates"]):
        if mode == "custom":
            frames.append(chunk)
            show(chunk)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("name", nargs="?", default="run1")
    parser.add_argument("incident", nargs="?", default=str(config.INCIDENT_PATH))
    args = parser.parse_args()

    problems = config.problems()
    if problems:
        raise SystemExit("\n".join(problems))

    with open(args.incident) as f:
        incident = normalise(json.load(f))

    reset_mock()
    cfg = run_config(f"live-{args.name}")
    frames, started = [], time.time()
    print(f"model: {describe()}\nincident: {args.incident}\n")

    stream({"incident": incident}, cfg, frames)

    values = app_graph.get_state(cfg).values
    tokens_in, tokens_out = values.get("tokens_in", 0), values.get("tokens_out", 0)
    print(f"\nDECISION  {values.get('decision')}   rounds={values.get('round')}   "
          f"ledger={len(values.get('ledger', []))}")
    print(f"TOKENS    in={tokens_in}  out={tokens_out}  "
          f"cache read={values.get('cache_read', 0)}  write={values.get('cache_write', 0)}")
    for row in values.get("plan", []):
        print(f"  {row['id']:10} [{row['risk']:10}] {row['action']}")

    approved = [r["id"] for r in values.get("plan", []) if r["risk"] in ("read_only", "reversible")]
    print(f"\napproving {approved}")
    stream(Command(resume={"approved_ids": approved}), cfg, frames)

    final = app_graph.get_state(cfg).values
    frames.append({"e": "receipt", "receipts": final.get("receipts", []),
                   "approved_ids": final.get("approved_ids", [])})

    out = config.ROOT / "runs"
    out.mkdir(exist_ok=True)
    Path(out / f"{args.name}.jsonl").write_text(
        "".join(json.dumps(fr, default=str) + "\n" for fr in frames)
    )
    Path(out / f"{args.name}-brief.json").write_text(
        json.dumps(final.get("brief", {}), indent=2, default=str)
    )
    print(f"\nreceipts: {[r['id'] for r in final.get('receipts', [])]}")
    print(f"elapsed {int(time.time() - started)}s  ->  runs/{args.name}.jsonl ({len(frames)} frames)")


if __name__ == "__main__":
    main()

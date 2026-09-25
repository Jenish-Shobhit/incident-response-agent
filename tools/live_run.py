"""One full run, recorded. Writes demo/<name>.jsonl -- every SSE frame, in order.

A run you did not record is a run you have to pay for twice.
"""
import json, os, sys, time
sys.path.insert(0, ".")

from langgraph.types import Command
from app.graph import app_graph, run_config
from app.llm import describe, reset_mock

name = sys.argv[1] if len(sys.argv) > 1 else "run1"
incident_path = sys.argv[2] if len(sys.argv) > 2 else "data/incident.json"

reset_mock()
incident = json.load(open(incident_path))
cfg = run_config(f"live-{name}")
frames, t0 = [], time.time()

def keep(f):
    frames.append(f)
    e = f.get("e")
    if e == "agent":
        print(f"  [{f.get('name'):9}] {f.get('status'):8} {str(f.get('detail',''))[:88]}")
    elif e == "act":
        print(f"     -> {f.get('agent')}: {f.get('tool')}({json.dumps(f.get('input'))[:70]})")
    elif e == "quarantine":
        print(f"  [guard    ] QUARANTINED {f['key']} {f['rules']}")

print(f"model: {describe()}\nincident: {incident_path}\n")
for mode, chunk in app_graph.stream({"incident": incident}, cfg, stream_mode=["custom", "updates"]):
    if mode == "custom":
        keep(chunk)

state = app_graph.get_state(cfg)
v = state.values
ti, to = v.get("tokens_in", 0), v.get("tokens_out", 0)
cr, cw = v.get("cache_read", 0), v.get("cache_write", 0)
print(f"\nDECISION  {v.get('decision')}   rounds={v.get('round')}   ledger={len(v.get('ledger',[]))}")
print(f"TOKENS    billed in={ti}  out={to}  ->  {ti+to} billed")
print(f"          cache read={cr}  write={cw}  ->  {ti+to+cr+cw} processed in total")
print(f"waiting at: {state.next}")
for r in v.get("plan", []):
    print(f"  {r['id']:10} [{r['risk']:10}] {r['action']}")

# Approve everything that is not destructive, exactly as a cautious operator would.
approved = [r["id"] for r in v.get("plan", []) if r["risk"] in ("read_only", "reversible")]
print(f"\napproving {approved}")
for mode, chunk in app_graph.stream(Command(resume={"approved_ids": approved}), cfg,
                                    stream_mode=["custom", "updates"]):
    if mode == "custom":
        keep(chunk)

final = app_graph.get_state(cfg)
frames.append({"e": "receipt", "receipts": final.values.get("receipts", []),
               "approved_ids": final.values.get("approved_ids", [])})

os.makedirs("demo", exist_ok=True)
with open(f"demo/{name}.jsonl", "w") as f:
    for fr in frames:
        f.write(json.dumps(fr, default=str) + "\n")

brief = final.values.get("brief", {})
with open(f"demo/{name}-brief.json", "w") as f:
    json.dump(brief, f, indent=2, default=str)

print(f"\nreceipts: {[r['id'] for r in final.values.get('receipts', [])]}")
print(f"elapsed {int(time.time()-t0)}s  ->  demo/{name}.jsonl ({len(frames)} frames)")

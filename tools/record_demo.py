"""Record one mock run as a flat list of SSE frames, for the offline demo.

`web/index.html?demo` replays this file with no backend, no model and no tokens. It is
the insurance policy: if Bedrock is unavailable at demo time, the whole interface still
demonstrates end to end from a file that costs nothing to produce.
"""
import json, os, sys
sys.path.insert(0, ".")
os.environ.setdefault("MOCK", "1")

from langgraph.types import Command
from app.graph import app_graph, run_config
from app.llm import reset_mock

reset_mock()
incident = json.load(open("data/incident.json"))
cfg = run_config("demo")
frames = [{"e": "start", "thread_id": "demo", "model": "recorded demo (0 tokens)"}]

for mode, chunk in app_graph.stream({"incident": incident}, cfg, stream_mode=["custom", "updates"]):
    if mode == "custom":
        frames.append(chunk)

state = app_graph.get_state(cfg)
frames.append({"e": "tokens", "in": state.values.get("tokens_in", 0), "out": state.values.get("tokens_out", 0)})
frames.append({"e": "done", "thread_id": "demo", "awaiting": True})

# The demo stops at the approval gate, exactly as a real run does. Approving is left to
# whoever is watching -- that click is the point of the whole screen.
os.makedirs("web/demo", exist_ok=True)
with open("web/demo/frames.json", "w") as f:
    json.dump(frames, f, indent=1)
print(f"wrote web/demo/frames.json  {len(frames)} frames")

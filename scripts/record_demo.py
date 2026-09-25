"""Record one mock run as the frames the static demo replays.

    python scripts/record_demo.py

Writes web/demo/frames.json. The page replays that file with no backend, no model and no
tokens -- it is what the public demo serves. Re-run it whenever the scenario, the
fixtures or the graph change, so the demo shows what the code actually does.
"""

import json
import os

os.environ["MOCK"] = "1"  # a recording is always the deterministic run, whatever .env says

from incident_agent import config  # noqa: E402  (must import after MOCK is pinned)
from incident_agent.evidence import normalise  # noqa: E402
from incident_agent.graph import app_graph, run_config  # noqa: E402
from incident_agent.llm import reset_mock  # noqa: E402


def main():
    with open(config.INCIDENT_PATH) as f:
        incident = normalise(json.load(f))

    reset_mock()
    cfg = run_config("demo")
    frames = [{"e": "start", "thread_id": "demo", "model": "recorded demo (0 tokens)"}]
    for mode, chunk in app_graph.stream({"incident": incident}, cfg, stream_mode=["custom", "updates"]):
        if mode == "custom":
            frames.append(chunk)

    values = app_graph.get_state(cfg).values
    frames.append({"e": "tokens", "in": values.get("tokens_in", 0), "out": values.get("tokens_out", 0)})
    # The demo stops at the approval gate, exactly as a real run does. Approving is left
    # to whoever is watching -- that click is the point of the whole screen.
    frames.append({"e": "done", "thread_id": "demo", "awaiting": True})

    out = config.WEB_DIR / "demo" / "frames.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(frames, indent=1) + "\n")
    print(f"wrote {out.relative_to(config.ROOT)}  {len(frames)} frames")


if __name__ == "__main__":
    main()

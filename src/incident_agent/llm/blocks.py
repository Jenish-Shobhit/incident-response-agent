"""The three content blocks every message in this system is built from."""

import json


def text_block(s):
    return {"type": "text", "text": s}


def tool_result_block(tool_use_id, payload):
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(payload, default=str),
    }

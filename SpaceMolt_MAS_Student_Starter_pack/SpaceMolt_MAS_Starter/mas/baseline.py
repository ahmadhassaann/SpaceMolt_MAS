"""Deterministic baseline used for an honest MAS comparison."""
from __future__ import annotations

import argparse
import json
from mas.mcp_client import MCPGameClient


def run(pilot: str, cycles: int = 1) -> dict:
    client = MCPGameClient(pilot)
    events = []
    for cycle in range(cycles):
        status = client.call("spacemolt", "get_status")
        events.append({"cycle": cycle + 1, "status": status})
    return {"baseline": "single-script-status-loop", "pilot": pilot, "events": events}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", required=True)
    parser.add_argument("--cycles", type=int, default=1)
    args = parser.parse_args()
    print(json.dumps(run(args.pilot, args.cycles), indent=2, default=str))

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import httpx

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest

from mas.mcp_client import MCPGameClient
from mas.state import MASState
from scripts.evidence import record


async def send_task(url: str, pilot: str, role: str, objective: str,
                    payload: dict[str, Any], task_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=650.0) as http:
        card = await A2ACardResolver(httpx_client=http, base_url=url).get_agent_card()
    client = await create_client(agent=card, client_config=ClientConfig(streaming=False))
    body = {"pilot": pilot, "objective": objective, **payload,
            "coordinator_task_id": task_id}
    message = new_text_message(json.dumps(body), role=Role.ROLE_USER)
    responses = []
    try:
        async for response in client.send_message(SendMessageRequest(message=message)):
            responses.append(str(response))
    finally:
        await client.close()
    return {"role": role, "pilot": pilot, "url": url, "response_count": len(responses),
            "response_preview": responses[-1][:3000] if responses else ""}


async def run(pilots: list[str], mining_url: str, trading_url: str,
              objective: str, confirm: bool, db_path: str) -> dict[str, Any]:
    state = MASState(db_path)
    results = []
    for pilot in pilots:
        mcp = MCPGameClient(pilot, db_path)
        status = mcp.call("spacemolt", "get_status", task_id="coordinator-observe")
        state.record_observation(pilot, "coordinator.mcp_status", status)
        record("coordinator.observed", agent="coordinator", data={"pilot": pilot, "status": status.get("text", "")[:500]})

        role = "mining" if objective in ("mine", "observe_mining") else "trading"
        url = mining_url if role == "mining" else trading_url
        task_id = state.create_task(role, pilot, objective,
                                    {"confirm_state_change": confirm})
        state.update_task(task_id, "working")
        try:
            result = await send_task(url, pilot, role, objective,
                                     {"confirm_state_change": confirm}, task_id)
            state.update_task(task_id, "completed", result)
            record("coordinator.task_completed", agent="coordinator", task_id=task_id,
                   data={"pilot": pilot, "role": role, "url": url})
        except Exception as exc:
            state.update_task(task_id, "failed", error=type(exc).__name__ + ": " + str(exc))
            record("coordinator.task_failed", agent="coordinator", task_id=task_id,
                   data={"pilot": pilot, "role": role, "error": str(exc)})
            result = {"role": role, "pilot": pilot, "error": str(exc)}
        results.append(result)
    state.close()
    return {"coordinator": "SpaceMolt MAS", "objective": objective, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilots", nargs="+", required=True)
    parser.add_argument("--mining-url", default="http://127.0.0.1:9999")
    parser.add_argument("--trading-url", default="http://127.0.0.1:9998")
    parser.add_argument("--objective", choices=("observe_mining", "mine", "assess", "buy", "sell"),
                        default="observe_mining")
    parser.add_argument("--confirm", action="store_true",
                        help="Explicitly permit a state-changing action")
    parser.add_argument("--db", default="logs/mas.sqlite3")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.pilots, args.mining_url, args.trading_url,
                                     args.objective, args.confirm, args.db)),
                     indent=2, default=str))


if __name__ == "__main__":
    main()

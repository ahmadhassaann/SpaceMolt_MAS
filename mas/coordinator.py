from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import httpx

from a2a.client import A2ACardResolver, ClientCallContext, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest

from mas.mcp_client import MCPGameClient
from mas.state import MASState
from scripts.evidence import record

RUN_MISSION_TIMEOUT_SECONDS = 3600.0


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
        async for response in client.send_message(
            SendMessageRequest(message=message),
            context=ClientCallContext(
                timeout=RUN_MISSION_TIMEOUT_SECONDS
                if objective == "run_mission" else 120.0
            ),
        ):
            responses.append(str(response))
    finally:
        await client.close()
    return {"role": role, "pilot": pilot, "url": url, "response_count": len(responses),
            "response_preview": responses[-1][:3000] if responses else ""}


async def run(pilots: list[str], mining_url: str, trading_url: str,
              objective: str, confirm: bool, db_path: str,
              mission_id: str | None = None) -> dict[str, Any]:
    state = MASState(db_path)
    results = []
    for pilot in pilots:
        if objective not in ("accept_mission", "run_mission"):
            mcp = MCPGameClient(pilot, db_path)
            status = await mcp.call_async(
                "spacemolt", "get_status", task_id="coordinator-observe"
            )
            state.record_observation(pilot, "coordinator.mcp_status", status)
            record("coordinator.observed", agent="coordinator",
                   data={"pilot": pilot, "status": status.get("text", "")[:500]})

        role = "mining" if objective in (
            "mine", "observe_mining", "accept_mission", "run_mission"
        ) else "trading"
        url = mining_url if role == "mining" else trading_url
        task_payload: dict[str, Any] = {"confirm_state_change": confirm}
        if mission_id:
            task_payload["mission_id"] = mission_id
        task_id = state.create_task(role, pilot, objective, task_payload)
        state.update_task(task_id, "working")
        try:
            result = await send_task(url, pilot, role, objective,
                                     task_payload, task_id)
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
    parser.add_argument("--objective", choices=("observe_mining", "mine", "accept_mission",
                                                "run_mission",
                                                "assess", "buy", "sell"),
                        default="observe_mining")
    parser.add_argument("--mission-id",
                        help="Template ID for accept_mission; active mission ID for run_mission")
    parser.add_argument("--confirm", action="store_true",
                        help="Explicitly permit a state-changing action")
    parser.add_argument("--db", default="logs/mas.sqlite3")
    args = parser.parse_args()
    if args.objective == "accept_mission" and not args.mission_id:
        parser.error("--mission-id is required for accept_mission")
    if args.objective == "run_mission" and not args.mission_id:
        parser.error("--mission-id is required for run_mission")
    print(json.dumps(asyncio.run(run(args.pilots, args.mining_url, args.trading_url,
                                     args.objective, args.confirm, args.db,
                                     args.mission_id)),
                     indent=2, default=str))


if __name__ == "__main__":
    main()

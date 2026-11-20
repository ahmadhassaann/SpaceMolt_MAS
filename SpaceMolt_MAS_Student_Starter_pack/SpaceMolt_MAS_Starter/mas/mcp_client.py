from __future__ import annotations

import asyncio
import json
from typing import Any

import keyring
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from scripts.evidence import record


VAULT = "spacemolt-course-test"
MCP_ENDPOINT = "https://game.spacemolt.com/mcp/v2"


def text_from_result(result: Any) -> str:
    if hasattr(result, "content"):
        parts = []
        for item in result.content:
            if hasattr(item, "text"):
                parts.append(item.text)
        if parts:
            return "\n".join(parts)
    return str(result)


class MCPGameClient:
    def __init__(self, pilot: str, db_path: str = "logs/mas.sqlite3"):
        self.pilot = pilot
        self.db_path = db_path
        self.session_id: str | None = None
        self.schemas: dict[str, dict[str, Any]] = {}

    def _password(self) -> str:
        password = keyring.get_password(VAULT, self.pilot)
        if not password:
            raise RuntimeError(
                f"No pilot password found in Windows Credential Manager for {self.pilot}. "
                "Run pilot_setup.py or store it securely."
            )
        return password

    async def connect(self) -> None:
        async with streamable_http_client(MCP_ENDPOINT) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                self.schemas = {tool.name: tool.input_schema for tool in tools.tools}
                await session.call_tool(
                    "spacemolt_auth",
                    arguments={"action": "login", "username": self.pilot,
                               "password": self._password()},
                )

    def call(self, tool: str, action: str, payload: dict[str, Any] | None = None,
             task_id: str | None = None) -> dict[str, Any]:
        return asyncio.run(self._call(tool, action, payload or {}, task_id))

    async def _call(self, tool: str, action: str, payload: dict[str, Any],
                    task_id: str | None = None) -> dict[str, Any]:
        if tool not in self.schemas:
            await self._discover()
        schema = self.schemas.get(tool, {})
        arguments = self._schema_valid_arguments(schema, {"action": action, **payload})

        # Re-login for expired sessions is handled by a fresh login before every operation.
        async with streamable_http_client(MCP_ENDPOINT) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                login = await session.call_tool(
                    "spacemolt_auth",
                    arguments={"action": "login", "username": self.pilot,
                               "password": self._password()},
                )
                record("mcp.authenticated", agent=f"mcp:{self.pilot}", task_id=task_id,
                       data={"pilot": self.pilot, "tool": "spacemolt_auth", "action": "login",
                             "confirmation": text_from_result(login)[:500]})
                result = await session.call_tool(tool, arguments=arguments)
                text = text_from_result(result)
                return {"pilot": self.pilot, "tool": tool, "action": action,
                        "arguments": arguments, "text": text, "raw": str(result)[:4000]}

    async def _discover(self) -> None:
        async with streamable_http_client(MCP_ENDPOINT) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                self.schemas = {tool.name: tool.input_schema for tool in tools.tools}

    def _schema_valid_arguments(self, schema: dict[str, Any],
                                candidate: dict[str, Any]) -> dict[str, Any]:
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        allowed = set(properties)
        if not allowed:
            return candidate
        rejected = set(candidate) - allowed
        if rejected:
            record("mcp.argument_rejected", agent=f"mcp:{self.pilot}",
                   data={"rejected": sorted(rejected)})
        return {key: value for key, value in candidate.items() if key in allowed}

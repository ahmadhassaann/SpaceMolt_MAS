from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

import keyring
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

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


class MCPGameSession:
    def __init__(self, client: MCPGameClient, session: ClientSession,
                 task_id: str | None):
        self.client = client
        self.session = session
        self.task_id = task_id

    async def call(self, tool: str, action: str,
                   payload: dict[str, Any] | None = None) -> dict[str, Any]:
        schema = self.client.schemas.get(tool, {})
        arguments = self.client._schema_valid_arguments(
            schema, {"action": action, **(payload or {})}
        )
        try:
            result = await self.session.call_tool(tool, arguments=arguments)
        except MCPError as exc:
            record("mcp.call_failed", agent=f"mcp:{self.client.pilot}",
                   task_id=self.task_id,
                   data={"pilot": self.client.pilot, "tool": tool,
                         "action": action, "code": exc.code,
                         "message": exc.message, "data": exc.data})
            raise RuntimeError(
                f"MCP tool {tool}.{action} failed "
                f"(code {exc.code}): {exc.message}"
            ) from exc
        text = text_from_result(result)
        if getattr(result, "isError", False):
            raise RuntimeError(
                f"MCP tool {tool}.{action} failed: {text[:1000]}"
            )
        return {
            "pilot": self.client.pilot, "tool": tool, "action": action,
            "arguments": arguments, "text": text, "raw": str(result)[:4000],
        }


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
        return asyncio.run(self.call_many_async(
            [(tool, action, payload)], task_id
        ))[0]

    async def call_async(self, tool: str, action: str,
                         payload: dict[str, Any] | None = None,
                         task_id: str | None = None) -> dict[str, Any]:
        return (await self.call_many_async(
            [(tool, action, payload)], task_id
        ))[0]

    def call_many(self, calls: list[tuple[str, str, dict[str, Any] | None]],
                  task_id: str | None = None) -> list[dict[str, Any]]:
        return asyncio.run(self.call_many_async(calls, task_id))

    async def call_many_async(
        self, calls: list[tuple[str, str, dict[str, Any] | None]],
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self.open_session(task_id) as session:
            return [
                await session.call(tool, action, payload)
                for tool, action, payload in calls
            ]

    @asynccontextmanager
    async def open_session(
        self, task_id: str | None = None
    ) -> AsyncGenerator[MCPGameSession, None]:
        async with streamable_http_client(MCP_ENDPOINT) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                if not self.schemas:
                    tools = await session.list_tools()
                    self.schemas = {
                        tool.name: tool.input_schema for tool in tools.tools
                    }
                login = await session.call_tool(
                    "spacemolt_auth",
                    arguments={"action": "login", "username": self.pilot,
                               "password": self._password()},
                )
                if getattr(login, "isError", False):
                    raise RuntimeError(
                        f"MCP login failed: {text_from_result(login)[:1000]}"
                    )
                record("mcp.authenticated", agent=f"mcp:{self.pilot}",
                       task_id=task_id,
                       data={"pilot": self.pilot, "tool": "spacemolt_auth",
                             "action": "login", "authenticated": True})
                yield MCPGameSession(self, session, task_id)

    async def _call(self, tool: str, action: str, payload: dict[str, Any],
                    task_id: str | None = None) -> dict[str, Any]:
        return (await self.call_many_async(
            [(tool, action, payload)], task_id
        ))[0]

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

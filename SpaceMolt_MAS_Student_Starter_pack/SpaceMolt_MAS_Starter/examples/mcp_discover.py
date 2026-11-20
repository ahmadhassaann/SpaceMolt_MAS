"""Discover SpaceMolt MCP v2 tool names and schemas (no credentials or mutations)."""
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with streamable_http_client('https://game.spacemolt.com/mcp/v2') as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            items=await session.list_tools()
            for tool in items.tools:
                print('\nTOOL:',tool.name)
                print('DESCRIPTION:',(tool.description or '')[:180])
                print('SCHEMA:',str(tool.input_schema)[:650])
    print('\nDiscovery succeeded. This script did not call gameplay actions.')
if __name__=='__main__':asyncio.run(main())

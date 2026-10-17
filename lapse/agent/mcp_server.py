from __future__ import annotations

import argparse
import json
import os

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, Tool

from lapse.agent.tools import REGISTRY, dispatch
from lapse.config import settings
from lapse.trace import current_turn


class LapseMCP(FastMCP):
    async def list_tools(self):
        return [
            Tool(name=tool.name, description=tool.description, inputSchema=tool.schema)
            for tool in REGISTRY.values()
        ]

    async def call_tool(self, name, arguments):
        context = self.get_context()
        try:
            meta = context.request_context.meta
        except ValueError:
            meta = None
        metadata = meta.model_dump() if meta else {}
        uid = metadata.get("lapse/uid", settings().uid)
        turn_id = metadata.get("lapse/turn_id")
        if not isinstance(uid, str) or not uid or (turn_id is not None and not isinstance(turn_id, str)):
            raise ValueError("Invalid Lapse request metadata")
        token = current_turn.set(turn_id)
        try:
            result = dispatch(uid, name, arguments)
        finally:
            current_turn.reset(token)
        return [TextContent(type="text", text=json.dumps(result))]


def create_server():
    return LapseMCP(
        "Lapse",
        host=os.getenv("FASTMCP_HOST", "127.0.0.1"),
        port=int(os.getenv("FASTMCP_PORT", os.getenv("MCP_PORT", "8766"))),
    )


def run():
    parser = argparse.ArgumentParser(description="Lapse fixed graph tools")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    args = parser.parse_args()
    if args.list:
        print("\n".join(REGISTRY))
    else:
        create_server().run(transport=args.transport)


if __name__ == "__main__":
    run()

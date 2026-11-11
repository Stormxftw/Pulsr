"""Local stdio MCP fixture. Never points at configured user services."""
from pathlib import Path
import sys
from typing import Any
from pydantic import BaseModel
from mcp.server.mcpserver import MCPServer, Context
from mcp.types import ToolAnnotations

app = MCPServer('pulse-integration')
marker = Path(sys.argv[1])


@app.tool(annotations=ToolAnnotations(readOnlyHint=True), structured_output=True)
def read_metrics(offset: int = 0) -> dict[str, Any]:
    """Read deterministic fixture counters."""
    return {'count': 42 + offset, 'nested': {'score': 87.5}, 'private': 'MCP_RESULT_CANARY'}


@app.tool(structured_output=True)
def bump_counter() -> dict[str, Any]:
    """Write a marker: must NEVER be called by Pulsr."""
    marker.write_text('write tool ran', encoding='utf-8')
    return {'count': 1}


class Consent(BaseModel):
    confirmed: bool


@app.tool(annotations=ToolAnnotations(readOnlyHint=True), structured_output=True)
async def ask_consent(ctx: Context) -> dict[str, Any]:
    """Read-only but asks consent to prove the background scope declines."""
    result = await ctx.elicit('Fixture asks consent', Consent)
    return {'accepted': 1 if result.action == 'accept' else 0}


if __name__ == '__main__':
    app.run('stdio')

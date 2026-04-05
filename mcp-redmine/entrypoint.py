"""Wrapper pro mcp-redmine — vypne DNS rebinding protection a spustí SSE server."""
import mcp.server.transport_security as _ts
from mcp.server.transport_security import TransportSecuritySettings, TransportSecurityMiddleware

# Monkey-patch: validate_request vždy vrátí None (žádná validace)
async def _no_validate(self, request, is_post=False):
    return None

TransportSecurityMiddleware.validate_request = _no_validate

# Spustí mcp-redmine normálně přes CLI
import sys
sys.argv = ["mcp-redmine", "--transport", "sse", "--host", "0.0.0.0", "--port", "8000"]
from mcp_redmine.server import main
main()

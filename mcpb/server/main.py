"""MCPB entry point -- launches the toolkit's MCP stdio server.

Configuration comes entirely from environment variables Claude Desktop
injects from the manifest's user_config fields (see ../manifest.json) --
no connections.yaml, no terminal setup. See
nspb_rest_toolkit.config.load_config_from_env for the exact env var names
and runtime.get_config for the fallback order (a real connections.yaml, if
one is ever placed alongside this, still takes priority).
"""

from nspb_rest_toolkit.mcp_server import main

if __name__ == "__main__":
    main()

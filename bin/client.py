#!/usr/bin/env python3
"""Stdio MCP client for the Eclipse Muster MCP server (Muse connector).

Spawns the Muster server over stdio, runs one JSON-RPC session
(initialize -> notifications/initialized -> one request), and prints
the result as JSON. Python >= 3.10, standard library only. No
credentials exist for this server and none are accepted or passed
to the child.

Server resolution, in order:
  1. ECLIPSE_MUSTER_CMD   full command line, split like a shell line
  2. an `eclipse-muster` entry point on PATH (the installed
     `eclipse-muster` PyPI package's console script)
  3. `python -m eclipse_muster`, when an importable module of that
     name exists (the current package ships only the console script,
     so this route is dormant until a module entry ships)
  4. ECLIPSE_MUSTER_HOME  a source checkout holding server.py

State resolution, in order:
  1. --state <path> on the command line (one invocation)
  2. MUSTER_CONNECTOR_STATE environment variable
  3. a per-user data dir for this connector:
       Windows  %LOCALAPPDATA%\\EclipseMuster\\state.json
       macOS    ~/Library/Application Support/EclipseMuster/state.json
       other    $XDG_DATA_HOME/eclipse-muster/state.json
                (or ~/.local/share/eclipse-muster/state.json)
The server default state (inside its own install) is never used:
the client always passes ECLIPSE_MUSTER_STATE to the child.

Commands:
  list-tools [--cursor <cursor>]
  call-tool <tool> [--args <json-object>] [--arguments-file <path>]
  policy-show
  receipt-list [--limit <n>]
  record-search [--kind <kind>] [--query <text>] [--surface <surface>]
  record-read --record-id <id> [--surface <owner|analytic>]
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

PROTOCOLS = {"2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"}

# Exact tool names returned by the server's tools/list (verified
# against eclipse-muster 0.1.1). A tool the server adds later stays
# blocked until reviewed and added here.
ALLOWED_TOOLS: set[str] = {
    "record_ingest",
    "record_read",
    "record_search",
    "merge_propose",
    "merge_execute",
    "merge_unmerge",
    "reply_draft",
    "policy_show",
    "receipt_list",
    "retention_sweep",
}


class McpError(RuntimeError):
    """Transport, protocol, or configuration failure. No replay."""


def resolve_server_command(env=None, which=None, find_spec=None):
    """Return the argv list that starts the Muster server.

    The lookup helpers are injectable for tests. Raises McpError with
    install guidance when no route resolves.
    """
    env = os.environ if env is None else env
    which = shutil.which if which is None else which
    find_spec = importlib.util.find_spec if find_spec is None else find_spec

    override = env.get("ECLIPSE_MUSTER_CMD", "").strip()
    if override:
        argv = shlex.split(override)
        if argv:
            return argv
        raise McpError("ECLIPSE_MUSTER_CMD is set but empty after parsing")

    entry = which("eclipse-muster")
    if entry:
        return [entry]

    try:
        spec = find_spec("eclipse_muster")
    except (ImportError, ValueError):
        spec = None
    if spec is not None:
        return [sys.executable, "-m", "eclipse_muster"]

    home = env.get("ECLIPSE_MUSTER_HOME", "").strip()
    if home:
        server_py = Path(home).expanduser() / "server.py"
        if server_py.is_file():
            return [sys.executable, str(server_py)]
        raise McpError(
            f"ECLIPSE_MUSTER_HOME={home} does not contain a server.py")

    raise McpError(
        "no Eclipse Muster server found. Install it with "
        "`pip install eclipse-muster` (once published), or set "
        "ECLIPSE_MUSTER_HOME to a source checkout, or set "
        "ECLIPSE_MUSTER_CMD to the full server command.")


def default_state_path(env=None, platform=None, home=None):
    """Per-user state file for this connector (never the server's)."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else Path(home)
    if platform.startswith("win"):
        base = env.get("LOCALAPPDATA")
        root = Path(base) if base else home / "AppData" / "Local"
        return root / "EclipseMuster" / "state.json"
    if platform == "darwin":
        return (home / "Library" / "Application Support"
                / "EclipseMuster" / "state.json")
    base = env.get("XDG_DATA_HOME")
    root = Path(base) if base else home / ".local" / "share"
    return root / "eclipse-muster" / "state.json"


def resolve_state_path(cli_state=None, env=None, platform=None, home=None):
    """--state wins, then MUSTER_CONNECTOR_STATE, then the default."""
    env = os.environ if env is None else env
    if cli_state is not None:
        return Path(cli_state)
    override = env.get("MUSTER_CONNECTOR_STATE", "").strip()
    if override:
        return Path(override).expanduser()
    return default_state_path(env=env, platform=platform, home=home)


class StdioClient:
    def __init__(self, state=None, env=None):
        env = os.environ if env is None else env
        self.command = resolve_server_command(env=env)
        child_env = dict(env)
        child_env["ECLIPSE_MUSTER_STATE"] = str(
            resolve_state_path(cli_state=state, env=env))
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=child_env,
        )
        self.sequence = 0
        self.protocol = "2025-03-26"

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass

    def send(self, method, params, *, notification=False):
        self.sequence += 1
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            body["id"] = self.sequence
        self.proc.stdin.write(json.dumps(body) + "\n")
        self.proc.stdin.flush()
        if notification:
            return None
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise McpError("MCP server closed the stream before replying")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != self.sequence:
                continue  # server notification; keep reading
            if "error" in message:
                raise McpError(
                    f"MCP returned a JSON-RPC error: {message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise McpError("MCP returned no result object")
            return result

    def initialize(self):
        result = self.send("initialize", {
            "protocolVersion": self.protocol,
            "capabilities": {},
            "clientInfo": {"name": "muse-muster-connector-client",
                           "version": "0.1.0"},
        })
        protocol = result.get("protocolVersion")
        if protocol in PROTOCOLS:
            self.protocol = protocol
        self.send("notifications/initialized", {}, notification=True)
        return result

    def call_tool(self, name, arguments):
        if name not in ALLOWED_TOOLS:
            raise McpError(
                f"tool {name!r} not in ALLOWED_TOOLS; inspect its schema "
                "and add its exact name first")
        return self.send("tools/call", {"name": name, "arguments": arguments})


def build_tool_call(args):
    """Map parsed CLI args to (tool name, arguments) for wrapper calls.

    Returns None for list-tools, which is not a tool call.
    """
    if args.command == "call-tool":
        if args.args and args.arguments_file:
            raise McpError("pass --args or --arguments-file, not both")
        if args.arguments_file:
            arguments = json.loads(args.arguments_file.read_bytes())
        elif args.args:
            arguments = json.loads(args.args)
        else:
            arguments = {}
        if not isinstance(arguments, dict):
            raise McpError("tool arguments must be a JSON object")
        return args.tool, arguments
    if args.command == "policy-show":
        return "policy_show", {}
    if args.command == "receipt-list":
        arguments = {}
        if args.limit is not None:
            arguments["limit"] = args.limit
        return "receipt_list", arguments
    if args.command == "record-search":
        arguments = {}
        if args.kind:
            arguments["kind"] = args.kind
        if args.query:
            arguments["query"] = args.query
        if args.surface:
            arguments["surface"] = args.surface
        return "record_search", arguments
    if args.command == "record-read":
        arguments = {"record_id": args.record_id}
        if args.surface:
            arguments["surface"] = args.surface
        return "record_read", arguments
    return None


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state", type=Path,
        help="run this invocation against this state file instead of "
             "the connector's default state")
    subparsers = parser.add_subparsers(dest="command", required=True)

    listing = subparsers.add_parser("list-tools")
    listing.add_argument("--cursor")

    calling = subparsers.add_parser("call-tool")
    calling.add_argument("tool")
    calling.add_argument("--args", help="tool arguments as one JSON object")
    calling.add_argument("--arguments-file", type=Path,
                         help="read tool arguments from a JSON file")

    subparsers.add_parser("policy-show")

    receipts = subparsers.add_parser("receipt-list")
    receipts.add_argument("--limit", type=int)

    search = subparsers.add_parser("record-search")
    search.add_argument("--kind")
    search.add_argument("--query")
    search.add_argument("--surface")

    read = subparsers.add_parser("record-read")
    read.add_argument("--record-id", required=True)
    read.add_argument("--surface")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        tool_call = build_tool_call(args)
    except (McpError, ValueError) as error:
        parser.error(str(error))
    client = StdioClient(state=args.state)
    try:
        client.initialize()
        if args.command == "list-tools":
            result = client.send(
                "tools/list", {"cursor": args.cursor} if args.cursor else {})
        else:
            result = client.call_tool(*tool_call)
    finally:
        client.close()
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get("isError") else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (McpError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)

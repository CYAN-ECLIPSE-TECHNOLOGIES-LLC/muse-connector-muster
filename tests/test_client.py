"""Unit tests for the connector helper (bin/client.py).

Hermetic: no server is spawned, no network, no credentials. The
server-resolution helpers are injected so every route is exercised
deterministically on every platform.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import client  # noqa: E402


def no_which(name):
    return None


def no_spec(name):
    return None


class ServerResolutionTests(unittest.TestCase):
    def test_cmd_override_wins_over_everything(self):
        argv = client.resolve_server_command(
            env={"ECLIPSE_MUSTER_CMD": "python3 /opt/muster/server.py --flag",
                 "ECLIPSE_MUSTER_HOME": "/nonexistent"},
            which=lambda name: "/usr/bin/eclipse-muster",
            find_spec=lambda name: object())
        self.assertEqual(argv, ["python3", "/opt/muster/server.py", "--flag"])

    def test_path_entry_point_beats_module_and_home(self):
        argv = client.resolve_server_command(
            env={"ECLIPSE_MUSTER_HOME": "/nonexistent"},
            which=lambda name: "/usr/bin/eclipse-muster",
            find_spec=lambda name: object())
        self.assertEqual(argv, ["/usr/bin/eclipse-muster"])

    def test_module_route_when_importable(self):
        argv = client.resolve_server_command(
            env={}, which=no_which, find_spec=lambda name: object())
        self.assertEqual(argv, [sys.executable, "-m", "eclipse_muster"])

    def test_home_route_runs_checkout_server(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "server.py").write_text("# fixture\n")
            argv = client.resolve_server_command(
                env={"ECLIPSE_MUSTER_HOME": tmp},
                which=no_which, find_spec=no_spec)
            self.assertEqual(argv, [sys.executable, str(Path(tmp) / "server.py")])

    def test_home_without_server_py_is_a_named_error(self):
        with self.assertRaises(client.McpError):
            client.resolve_server_command(
                env={"ECLIPSE_MUSTER_HOME": "/nonexistent"},
                which=no_which, find_spec=no_spec)

    def test_nothing_found_is_a_named_error(self):
        with self.assertRaises(client.McpError):
            client.resolve_server_command(
                env={}, which=no_which, find_spec=no_spec)


class StatePathTests(unittest.TestCase):
    HOME = Path("/home/tester")

    def test_cli_state_wins(self):
        path = client.resolve_state_path(
            cli_state="/tmp/one-off.json",
            env={"MUSTER_CONNECTOR_STATE": "/tmp/env.json"})
        self.assertEqual(path, Path("/tmp/one-off.json"))

    def test_env_override_beats_default(self):
        path = client.resolve_state_path(
            env={"MUSTER_CONNECTOR_STATE": "/tmp/env.json"},
            platform="linux", home=self.HOME)
        self.assertEqual(path, Path("/tmp/env.json"))

    def test_linux_xdg(self):
        path = client.resolve_state_path(
            env={"XDG_DATA_HOME": "/xdg"}, platform="linux", home=self.HOME)
        self.assertEqual(path, Path("/xdg/eclipse-muster/state.json"))

    def test_linux_fallback(self):
        path = client.resolve_state_path(
            env={}, platform="linux", home=self.HOME)
        self.assertEqual(
            path, self.HOME / ".local/share/eclipse-muster/state.json")

    def test_macos(self):
        path = client.resolve_state_path(
            env={}, platform="darwin", home=self.HOME)
        self.assertEqual(path, self.HOME / "Library/Application Support"
                         / "EclipseMuster/state.json")

    def test_windows_localappdata(self):
        path = client.resolve_state_path(
            env={"LOCALAPPDATA": "C:/Users/tester/AppData/Local"},
            platform="win32", home=self.HOME)
        self.assertEqual(
            path, Path("C:/Users/tester/AppData/Local/EclipseMuster/state.json"))


class ArgumentParsingTests(unittest.TestCase):
    def parse(self, argv):
        return client.build_parser().parse_args(argv)

    def test_record_search_flags(self):
        args = self.parse(["record-search", "--kind", "person",
                           "--query", "alpha", "--surface", "analytic"])
        self.assertEqual(client.build_tool_call(args),
                         ("record_search", {"kind": "person",
                                            "query": "alpha",
                                            "surface": "analytic"}))

    def test_receipt_list_limit(self):
        args = self.parse(["receipt-list", "--limit", "5"])
        self.assertEqual(client.build_tool_call(args),
                         ("receipt_list", {"limit": 5}))

    def test_record_read_requires_id(self):
        args = self.parse(["record-read", "--record-id", "person-1"])
        self.assertEqual(client.build_tool_call(args),
                         ("record_read", {"record_id": "person-1"}))

    def test_call_tool_args_json(self):
        args = self.parse(["call-tool", "policy_show", "--args", "{}"])
        self.assertEqual(client.build_tool_call(args), ("policy_show", {}))

    def test_call_tool_default_arguments(self):
        args = self.parse(["call-tool", "policy_show"])
        self.assertEqual(client.build_tool_call(args), ("policy_show", {}))

    def test_policy_show_wrapper(self):
        args = self.parse(["policy-show"])
        self.assertEqual(client.build_tool_call(args), ("policy_show", {}))

    def test_list_tools_is_not_a_tool_call(self):
        args = self.parse(["list-tools"])
        self.assertIsNone(client.build_tool_call(args))

    def test_allowlist_is_exactly_the_nine_tools(self):
        self.assertEqual(client.ALLOWED_TOOLS, {
            "record_ingest", "record_read", "record_search",
            "merge_propose", "merge_execute", "merge_unmerge",
            "reply_draft", "policy_show", "receipt_list"})
        for forbidden in ("record_delete", "platform_merge", "reply_send",
                          "email_send", "bulk_update"):
            self.assertNotIn(forbidden, client.ALLOWED_TOOLS)


if __name__ == "__main__":
    unittest.main()

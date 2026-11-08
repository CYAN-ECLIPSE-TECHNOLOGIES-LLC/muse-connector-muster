"""Integration smoke for the connector helper against the real server.

Every test spawns the actual Eclipse Muster server through
bin/client.py against a TEMP state file in a temp dir. Hermetic:
no network, no credentials, no state outside the temp dir.

The server under test resolves exactly as it does for a user:
ECLIPSE_MUSTER_CMD, else the installed `eclipse-muster` entry point,
else ECLIPSE_MUSTER_HOME pointing at a source checkout (CI installs
the server from source; a local dev run can set ECLIPSE_MUSTER_HOME).
When no server resolves, the whole class skips with the reason.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLIENT = HERE.parent / "bin" / "client.py"
sys.path.insert(0, str(HERE.parent / "bin"))
sys.path.insert(0, str(HERE))

import client as client_module  # noqa: E402
import fixtures  # noqa: E402

EXPECTED_TOOLS = [
    "record_ingest", "record_read", "record_search", "merge_propose",
    "merge_execute", "merge_unmerge", "reply_draft", "policy_show",
    "receipt_list",
]


def server_available():
    try:
        client_module.resolve_server_command()
        return True
    except client_module.McpError:
        return False


@unittest.skipUnless(server_available(),
                     "no Eclipse Muster server resolvable "
                     "(install it or set ECLIPSE_MUSTER_HOME)")
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        proc = subprocess.run(
            [sys.executable, str(CLIENT), "--state", str(self.state), *argv],
            capture_output=True, text=True, timeout=60)
        return proc

    def call(self, tool, arguments):
        proc = self.run_cli("call-tool", tool, "--args", json.dumps(arguments))
        self.assertEqual(proc.returncode, 0,
                         f"{tool} failed: {proc.stdout} {proc.stderr}")
        result = json.loads(proc.stdout)
        self.assertNotEqual(result.get("isError"), True, result)
        return json.loads(result["content"][0]["text"])

    def ingest_fixtures(self):
        for record in (fixtures.person_a(), fixtures.person_b(),
                       fixtures.ticket()):
            out = self.call("record_ingest", record)
            self.assertIn("record_id", out)

    def test_list_tools_is_exactly_the_nine(self):
        proc = self.run_cli("list-tools")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        names = [t["name"] for t in json.loads(proc.stdout)["tools"]]
        self.assertEqual(sorted(names), sorted(EXPECTED_TOOLS))

    def test_policy_show_returns_tier_floors(self):
        proc = self.run_cli("policy-show")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(json.loads(proc.stdout)["content"][0]["text"])
        self.assertEqual(payload["tier_floors"]["read"], 0)
        self.assertEqual(payload["tier_floors"]["graph_merge_execute"], 2)
        self.assertEqual(payload["tier_floors"]["platform_merge"], 3)
        self.assertIn("masking", payload)

    def test_receipt_list_verifies_empty_chain(self):
        payload = self.call("receipt_list", {})
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["chain_valid"], True)

    def test_ingest_then_search_is_masked_on_analytic_surface(self):
        self.ingest_fixtures()
        payload = self.call("record_search", {
            "kind": "person", "query": "alpha", "surface": "analytic"})
        self.assertEqual(payload["count"], 2)
        blob = json.dumps(payload)
        # Raw PII never crosses the analytic surface.
        self.assertNotIn("alpha.tester@test.example", blob)
        self.assertNotIn("555-010-9876", blob)
        self.assertNotIn("123-45-6789", blob)
        hit = next(h for h in payload["hits"]
                   if h["record_id"] == "person-test-a")
        self.assertEqual(hit["fields"]["emails"], ["***@test.example"])
        self.assertEqual(hit["fields"]["phone"], "***76")
        self.assertIsNone(hit["fields"]["ssn"])

    def test_merge_propose_gives_evidence_and_executes_nothing(self):
        self.ingest_fixtures()
        payload = self.call("merge_propose", {
            "record_a": "person-test-a", "record_b": "person-test-b"})
        proposal = payload["proposal"]
        self.assertIn("proposal_id", proposal)
        self.assertIn("proposal_hash", proposal)
        self.assertIn("confidence", proposal["evidence"])
        # Both nodes still exist as themselves: proposing changed nothing.
        search = self.call("record_search", {"kind": "person",
                                             "query": "tester"})
        self.assertEqual(search["count"], 2)

    def test_merge_execute_with_wrong_token_is_refused(self):
        self.ingest_fixtures()
        proposal = self.call("merge_propose", {
            "record_a": "person-test-a",
            "record_b": "person-test-b"})["proposal"]
        wrong = f"confirm-merge-{proposal['proposal_id']}-{'0' * 12}"
        proc = self.run_cli("call-tool", "merge_execute", "--args",
                            json.dumps({"proposal_id": proposal["proposal_id"],
                                        "confirm_token": wrong}))
        self.assertNotEqual(proc.returncode, 0,
                            "a wrong confirm token must not execute a merge")
        search = self.call("record_search", {"kind": "person",
                                             "query": "tester"})
        self.assertEqual(search["count"], 2)

    def test_merge_execute_with_server_token_then_unmerge(self):
        self.ingest_fixtures()
        proposal = self.call("merge_propose", {
            "record_a": "person-test-a",
            "record_b": "person-test-b"})["proposal"]
        token = (f"confirm-merge-{proposal['proposal_id']}-"
                 f"{proposal['proposal_hash'][:12]}")
        merged = self.call("merge_execute", {
            "proposal_id": proposal["proposal_id"], "confirm_token": token})
        self.assertIn("merged_record_id", merged)
        restored = self.call("merge_unmerge", {
            "merge_id": merged["merge_id"],
            "confirm_token": f"confirm-unmerge-{merged['merge_id']}"})
        self.assertEqual(sorted(restored["restored_record_ids"]),
                         ["person-test-a", "person-test-b"])
        receipts = self.call("receipt_list", {})
        self.assertEqual(receipts["chain_valid"], True)
        self.assertGreater(receipts["count"], 0)

    def test_reply_draft_cites_facts_or_marks_them_missing(self):
        self.ingest_fixtures()
        payload = self.call("reply_draft", {"ticket_id": "ticket-test-1",
                                            "person_id": "person-test-a"})
        draft = payload["draft"]
        self.assertEqual(draft["status"], "draft")
        body = draft["body"]
        # The ticket carries no resolution: the draft must cite record
        # facts and mark the gap, never assert an invented outcome.
        self.assertTrue(draft["citations"], "draft carries no citations")
        self.assertIn("MISSING_FACT", body)
        self.assertIn("resolution", draft["missing_facts"])


if __name__ == "__main__":
    unittest.main()

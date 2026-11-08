# Muse Connector for Eclipse Muster

A [Muse](https://muse.ai) custom connector for **Eclipse Muster**, the
Customer Graph MCP server by
[Cyan Eclipse Technologies LLC](https://cetech.ai). It lets Muse work a
canonical customer graph — Person, Company, Deal, Ticket, Conversation,
and Activity records — under governance: field-level masking on every
read, propose-only identity merges that execute only under an
owner-confirm token, reply drafts built strictly from record facts, and
an append-only, hash-chained receipt ledger that proves what happened
without copying the data it describes.

The connector is a thin, standard-library-only Python client. It spawns
the Muster server over stdio, runs one JSON-RPC session per command,
and prints results as JSON. No credential exists for this connector:
the server is a local process, and at this phase it contacts no
platform.

## Status — honest labels

- **Connector v0.1.** Server v0.1.0, phase **C0**: synthetic fixtures
  only, no platform adapters yet.
- **Bench pending — NOT certified.** Nothing here has passed an
  independent certification bench.
- **The server package is not on PyPI yet** (its Trusted Publisher
  setup is pending). Install the server from source for now; the
  instructions below mark the one step that changes when the package
  is published.

## Requirements

- Python 3.10 or later. Nothing else — the connector, the server, and
  the test suite are all Python standard library.
- The Eclipse Muster server, installed as below.

## Install

### 1. The Muster server

From source (today's route):

```bash
git clone https://github.com/CYAN-ECLIPSE-TECHNOLOGIES-LLC/eclipse-muster-mcp
python3 -m pip install ./eclipse-muster-mcp
```

This puts an `eclipse-muster` command on your PATH. When the package
is published to PyPI, this step becomes
`python3 -m pip install eclipse-muster` and nothing else changes.

### 2. The connector

Copy this repo's tree into your Muse custom connectors folder so
`connector.yaml`, `CONNECTOR.md`, and `bin/` land together:

```bash
cp -r muse-connector-muster ~/workspace/custom-connectors/custom.muster
```

### 3. Prove it

```bash
python3 ~/workspace/custom-connectors/custom.muster/bin/client.py policy-show
python3 ~/workspace/custom-connectors/custom.muster/bin/client.py list-tools
```

The first prints the tier floors and masking rules in force. The
second lists exactly nine tools.

## Usage

```bash
CLIENT=~/workspace/custom-connectors/custom.muster/bin/client.py

python3 $CLIENT record-search --kind person --query acme --surface analytic
python3 $CLIENT record-read --record-id person-123 --surface owner
python3 $CLIENT receipt-list --limit 20
python3 $CLIENT call-tool reply_draft --args '{"ticket_id": "ticket-123"}'
```

State lives in a per-user data directory for your platform
(`%LOCALAPPDATA%\EclipseMuster\state.json` on Windows,
`~/Library/Application Support/EclipseMuster/state.json` on macOS,
`$XDG_DATA_HOME/eclipse-muster/state.json` or
`~/.local/share/eclipse-muster/state.json` on Linux). Override it with
the `MUSTER_CONNECTOR_STATE` environment variable, or per invocation
with `--state <path>` — a temp file is the right choice for
experiments.

The full operating doc, including how the helper resolves the server
(`ECLIPSE_MUSTER_CMD`, the PATH entry point, a module entry, then
`ECLIPSE_MUSTER_HOME`), all nine tools with their tiers, and error
recovery, is in [CONNECTOR.md](CONNECTOR.md).

## Safety posture

- **Masking before the boundary.** On the analytic surface, emails
  show domain only, names show initials, phones show their last two
  digits, and government ID, payment, and health-adjacent fields
  return null.
- **Propose-only merges.** `merge_propose` returns evidence and
  changes nothing. `merge_execute` runs only with an owner-confirm
  token bound to the proposal hash, merges graph nodes only (never
  records inside a platform), and every merge can be undone exactly
  from its receipt snapshot.
- **Records-only drafts.** A reply draft cites the record fields it
  used. A fact with no record behind it becomes a `MISSING_FACT`
  marker — no outcome is ever invented. Drafts never send.
- **A hard denylist.** No delete, no platform merge, no send, no bulk
  update, no macro or trigger edits, no session or scraping route —
  at any tier. The client enforces its own nine-tool allowlist on
  top of the server's.
- **Customer text is data.** Instruction-shaped content in customer
  messages is quarantined at ingest, reported at draft time, and
  never obeyed or used as a fact source.
- **Receipts without content.** Every read of a Person or Ticket
  record and every write attempt appends to a hash-chained ledger of
  IDs, hashes, tiers, and verdicts — never the underlying content.

## Tests

Standard-library `unittest` (chosen to keep the dependency count at
zero), in two layers:

- **Unit** — server-command resolution order including env overrides,
  per-platform state-path resolution, argument parsing, and the
  allowlist's exact contents.
- **Integration** — the real server spawned through the helper against
  a temp state: the nine tools by name, tier floors, an empty-ledger
  chain check, a masked ingest-and-search round trip, propose-only
  merge semantics, a wrong-token merge refusal, a token-bound merge
  and unmerge, and a records-only draft check. All hermetic: temp
  dirs, no network, no credentials.

```bash
python3 -m unittest discover -s tests -v
```

The integration layer needs a resolvable server: install it as above,
or point `ECLIPSE_MUSTER_HOME` at a source checkout. Without one, the
integration tests skip with the reason named. GitHub Actions runs the
full suite on Ubuntu, macOS, and Windows across Python 3.10 and 3.12
(see [.github/workflows/tests.yml](.github/workflows/tests.yml)).

## Layout

```
connector.yaml          Muse custom-connector descriptor (custom.muster)
CONNECTOR.md            operating doc Muse reads for this connector
bin/client.py           the helper CLI (stdlib only)
tests/                  unit + integration suite and its fixtures
.github/workflows/      CI: the same suite on 3 OSes x 2 Pythons
```

## License

MIT — see [LICENSE](LICENSE). The Eclipse Muster server is a separate
project under its own repo and license.

---

*Eclipse Muster is a Cyan Eclipse Technologies product. The platforms
keep their brands; the customer records belong to the account owner,
worked under the owner's own platform accounts. Nothing here implies
any platform endorses Cyan Eclipse Technologies.*

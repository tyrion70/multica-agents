#!/usr/bin/env python3
"""Regression tests for scripts/sync.py agent identity stability (CHA-144).

These run fully offline: the `multica` CLI is replaced with an in-memory fake
backend, so the tests assert the sync's create-vs-upsert *logic* without touching
a real Multica instance.

The headline invariant (AC1) is the one that broke production: running the sync
twice back-to-back must not mint fresh UUIDs on the second run.

Run with:  python3 -m pytest scripts/test_sync.py   (or: python3 scripts/test_sync.py)
"""

import json
import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import sync  # noqa: E402

WS_NAME = "Chainlayer"
WS_ID = "00000000-0000-0000-0000-000000000001"


class FakeMulticaBackend:
    """Minimal in-memory stand-in for the `multica` CLI used by sync.py.

    Mints a fresh UUID on every `agent create` (exactly like the real backend —
    this is what makes a name-lookup miss dangerous) and resolves `agent update
    <id>` by explicit id.
    """

    def __init__(self):
        self.agents = {}  # id -> agent dict
        self._seq = 0
        self.created_calls = 0
        self.updated_calls = 0
        # Set of agent ids to hide from `agent list` (simulates a mis-scoped or
        # transient list that omits an existing agent — the AC5 trigger).
        self.hidden_ids = set()

    @staticmethod
    def _load_mcp(flags):
        """Read the pushed mcp config from --mcp-config-file, as the real backend
        would persist it. Lets tests assert what value actually landed live."""
        path = flags.get("--mcp-config-file")
        if isinstance(path, str):
            with open(path) as fh:
                return json.load(fh)
        return None

    def _mint(self):
        self._seq += 1
        return f"agent-uuid-{self._seq:04d}"

    @staticmethod
    def _parse_flags(tokens):
        out = {}
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t.startswith("--"):
                if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                    out[t] = tokens[i + 1]
                    i += 2
                else:
                    out[t] = True
                    i += 1
            else:
                i += 1
        return out

    def __call__(self, args, dry_run=False, mutating=False):
        # Mirror sync._multica's dry-run short-circuit for mutating calls.
        agent_mutating = (
            args[0] == "agent" and len(args) >= 2 and args[1] in {"create", "update", "skills"}
        )
        if dry_run and (mutating or agent_mutating):
            return None

        if args[:2] == ["agent", "list"]:
            return [a for aid, a in self.agents.items() if aid not in self.hidden_ids]

        if args[:2] == ["agent", "create"]:
            self.created_calls += 1
            flags = self._parse_flags(args[2:])
            aid = self._mint()
            agent = {"id": aid, "workspace_id": WS_ID}
            for flag, field in (("--name", "name"), ("--description", "description"),
                                ("--instructions", "instructions"), ("--runtime-id", "runtime_id"),
                                ("--model", "model"), ("--visibility", "visibility")):
                if flag in flags:
                    agent[field] = flags[flag]
            mcp = self._load_mcp(flags)
            if mcp is not None:
                agent["mcp_config"] = mcp
            self.agents[aid] = agent
            return agent

        if args[:2] == ["agent", "update"]:
            self.updated_calls += 1
            aid = args[2]
            flags = self._parse_flags(args[3:])
            agent = self.agents[aid]
            for flag, field in (("--name", "name"), ("--description", "description"),
                                ("--instructions", "instructions"), ("--runtime-id", "runtime_id"),
                                ("--model", "model"), ("--visibility", "visibility")):
                if flag in flags:
                    agent[field] = flags[flag]
            mcp = self._load_mcp(flags)
            if mcp is not None:
                agent["mcp_config"] = mcp
            return agent

        if args[:3] == ["agent", "env", "set"]:
            return {}

        if args[:3] == ["agent", "skills", "set"]:
            return {}

        if args[:2] == ["skill", "list"]:
            return []

        raise AssertionError(f"unexpected multica call: {args}")


class SyncIdentityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(__import__("tempfile").mkdtemp())
        self.ws = self.tmp / WS_NAME
        (self.ws / "squad-a" / "coder").mkdir(parents=True)
        self._write_agent("squad-a/coder", {
            "name": "Test Coder",
            "runtime_id": "rt-1",
            "description": "codes things",
        })
        self.state_path = self.tmp / ".sync-state.json"
        self.backend = FakeMulticaBackend()

        self._patches = [
            mock.patch.object(sync, "REPO_ROOT", self.tmp),
            mock.patch.object(sync, "DEFAULT_STATE_PATH", self.state_path),
            mock.patch.object(sync, "WORKSPACE_IDS", {WS_NAME: WS_ID}),
            mock.patch.object(sync, "_multica", self.backend),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        __import__("shutil").rmtree(self.tmp, ignore_errors=True)

    def _write_agent(self, rel, data):
        path = self.ws / rel / "agent.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def _id_map(self):
        p = self.ws / sync.AGENT_IDS_FILENAME
        return json.loads(p.read_text()) if p.is_file() else {}

    def _run(self, *extra):
        argv = ["sync.py", "--type", "agents", "--workspace", WS_NAME,
                "--sync-state", str(self.state_path)] + list(extra)
        code = 0
        with mock.patch.object(sys, "argv", argv):
            try:
                sync.main()
            except SystemExit as e:
                code = e.code or 0
        return code

    def test_ac1_double_run_no_new_uuid(self):
        """Two back-to-back runs: the second mints nothing and UUIDs are stable."""
        self._run("--allow-create")
        self.assertEqual(self.backend.created_calls, 1)
        uuids_after_first = set(self.backend.agents)
        id_map_first = self._id_map()
        self.assertEqual(len(id_map_first), 1)

        # Second run, WITHOUT --allow-create — must not create anything.
        self._run()
        self.assertEqual(self.backend.created_calls, 1, "second run minted a UUID")
        self.assertEqual(set(self.backend.agents), uuids_after_first, "UUID set changed")
        self.assertEqual(self._id_map(), id_map_first, "id map drifted")

    def test_ac4_rename_survives(self):
        """Renaming an agent's display name upserts the same UUID (no create)."""
        self._run("--allow-create")
        anchored_id = next(iter(self.backend.agents))

        self._write_agent("squad-a/coder", {
            "name": "Renamed Coder",
            "runtime_id": "rt-1",
            "description": "codes things",
        })
        code = self._run()  # no --allow-create: a rename must NOT need it
        self.assertEqual(code, 0)
        self.assertEqual(self.backend.created_calls, 1, "rename minted a new UUID")
        self.assertEqual(set(self.backend.agents), {anchored_id})
        self.assertEqual(self.backend.agents[anchored_id]["name"], "Renamed Coder")

    def test_ac5_no_silent_create_without_flag(self):
        """A brand-new agent with no anchor is refused (not minted) without --allow-create."""
        code = self._run()  # first run, no --allow-create
        self.assertEqual(self.backend.created_calls, 0, "minted without --allow-create")
        self.assertEqual(code, 1, "missing-create should exit non-zero")

    def test_ac5_omitted_agent_not_recreated(self):
        """If the live list omits an existing (anchored) agent, sync must not re-mint it.

        This is the exact production failure: a transient / mis-scoped `agent
        list` drops an agent, the old code read that as "agent gone" and minted a
        fresh UUID. The safety invariant is simply: never re-mint on a miss.
        """
        self._run("--allow-create")
        anchored_id = next(iter(self.backend.agents))
        # Simulate a mis-scoped / transient list that drops the agent.
        self.backend.hidden_ids.add(anchored_id)
        self._run()  # no --allow-create
        self.assertEqual(self.backend.created_calls, 1, "re-minted an omitted agent")
        self.assertEqual(set(self.backend.agents), {anchored_id}, "UUID set changed")

    # --- Fail-closed secret resolution + --force re-resolve (CHA-792) ---

    _MCP_PLACEHOLDER = {"mcpServers": {"svc": {"command": "run", "env": {"TOKEN": "#Some Item#"}}}}

    def test_failclosed_unresolved_placeholder_not_created(self):
        """An unresolvable #…# placeholder must never be pushed: the agent is
        skipped (not created) and the run exits non-zero."""
        self._write_agent("squad-a/coder", {
            "name": "Test Coder", "runtime_id": "rt-1", "description": "d",
            "mcp_config": self._MCP_PLACEHOLDER,
        })
        with mock.patch.object(sync, "_bw_get_secret", return_value=None):
            code = self._run("--allow-create")
        self.assertEqual(self.backend.created_calls, 0, "pushed a placeholder over a live agent")
        self.assertEqual(self.backend.agents, {}, "an agent was created with an unresolved secret")
        self.assertEqual(code, 1, "fail-closed skip should exit non-zero")

    def test_failclosed_update_does_not_wipe_live_secret(self):
        """If a secret stops resolving, a later sync must NOT overwrite the live
        agent's real key with a placeholder — it skips and leaves the key intact.
        This is the exact CHA-790 key-wipe."""
        self._write_agent("squad-a/coder", {
            "name": "Test Coder", "runtime_id": "rt-1", "description": "d",
            "mcp_config": self._MCP_PLACEHOLDER,
        })
        # First run: secret resolves, real key lands live.
        with mock.patch.object(sync, "_bw_get_secret", return_value="REALKEY"):
            self._run("--allow-create")
        aid = next(iter(self.backend.agents))
        self.assertEqual(
            self.backend.agents[aid]["mcp_config"]["mcpServers"]["svc"]["env"]["TOKEN"],
            "REALKEY",
        )

        # Second run: secret no longer resolves — must skip, not wipe.
        with mock.patch.object(sync, "_bw_get_secret", return_value=None):
            code = self._run()
        self.assertEqual(self.backend.updated_calls, 0, "issued an update with an unresolved secret")
        self.assertEqual(
            self.backend.agents[aid]["mcp_config"]["mcpServers"]["svc"]["env"]["TOKEN"],
            "REALKEY",
            "live secret was wiped with a placeholder",
        )
        self.assertEqual(code, 1, "fail-closed skip should exit non-zero")

    def test_force_repushes_unchanged_mcp_agent(self):
        """--force re-pushes mcp_config even when change detection says the agent
        is unchanged (the redacted-diff blind spot)."""
        self._write_agent("squad-a/coder", {
            "name": "Test Coder", "runtime_id": "rt-1", "description": "d",
            "mcp_config": {"mcpServers": {"svc": {"command": "run", "env": {"TOKEN": "literal"}}}},
        })
        self._run("--allow-create")
        self.assertEqual(self.backend.created_calls, 1)

        # A plain second run is a no-op (unchanged) — no update issued.
        code = self._run()
        self.assertEqual(code, 0)
        self.assertEqual(self.backend.updated_calls, 0, "unchanged agent should not be re-pushed")

        # --force bypasses the diff and re-pushes mcp_config.
        code = self._run("--force")
        self.assertEqual(code, 0)
        self.assertEqual(self.backend.updated_calls, 1, "--force did not re-push an unchanged agent")

    def test_max_creates_threshold_aborts(self):
        """With --allow-create, creates beyond the threshold abort the run."""
        for i in range(5):
            self._write_agent(f"squad-a/extra{i}", {
                "name": f"Extra {i}", "runtime_id": "rt-1",
            })
        code = self._run("--allow-create", "--max-creates", "2")
        self.assertEqual(code, 1, "should abort over threshold")
        # Hard cap respected: never mints more than the threshold.
        self.assertLessEqual(self.backend.created_calls, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Regression tests for scripts/sync.py agent identity stability (CHA-144).

These run fully offline: the `multica` CLI is replaced with an in-memory fake
backend, so the tests assert the sync's create-vs-upsert *logic* without touching
a real Multica instance.

The headline invariant (AC1) is the one that broke production: running the sync
twice back-to-back must not mint fresh UUIDs on the second run.

Run with:  python3 -m pytest scripts/test_sync.py   (or: python3 scripts/test_sync.py)
"""

import contextlib
import io
import json
import os
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


class FakeBw:
    """Models the `bw` CLI session lifecycle at the subprocess boundary (CHA-873).

    A session token encodes its data-dir: ``ISO:n`` for this run's *isolated*
    data-dir, ``DEF:n`` for the shared *default* dir. ``bw get item --session
    TOK`` succeeds only while TOK is the *current* token for its data-dir; a
    ``bw unlock`` in a dir mints a new token and invalidates the prior one FOR
    THAT DIR ONLY. That is precisely why sync.sh's isolated data-dir survives a
    concurrent unlock that re-keys the default dir, and why a shared session does
    not. The first `bw get` triggers a simulated concurrent unlock of the default
    dir, modelling a second `bw unlock` landing mid-run.
    """

    def __init__(self):
        self.current = {"ISO": "ISO:1", "DEF": "DEF:1"}
        self._concurrent_unlock_done = False

    def __call__(self, cmd, *args, **kwargs):
        assert cmd[:4] == ["bw", "list", "items", "--search"], f"unexpected bw call: {cmd}"
        # Fail-loud contract: sync.py must always pass --nointeraction so a stale
        # session errors out instead of hanging on a master-password prompt.
        assert "--nointeraction" in cmd, "bw call must pass --nointeraction"
        if not self._concurrent_unlock_done:
            self._concurrent_unlock_done = True
            self.current["DEF"] = "DEF:2"  # another host process re-keys default
        tok = cmd[cmd.index("--session") + 1]
        dir_key = tok.split(":", 1)[0]
        search = cmd[cmd.index("--search") + 1]
        if self.current.get(dir_key) == tok:
            # `list items --search` returns an array; the item's name matches the
            # search term so the exact-name match in _bw_get_secret picks it.
            item = {"name": search, "fields": [{"name": "API", "value": "REALKEY", "type": 1}]}
            return mock.Mock(returncode=0, stdout=json.dumps([item]), stderr="")
        # Stale session under --nointeraction: non-zero, locked, empty stdout.
        return mock.Mock(returncode=1, stdout="", stderr="Vault is locked.")


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

    # --- Session isolation vs concurrent `bw unlock` (CHA-873) ---

    def test_isolated_session_survives_concurrent_unlock(self):
        """AC: with sync.sh's per-run isolated data-dir, a second `bw unlock`
        landing mid-run does NOT invalidate this run's session, so every
        placeholder resolves and there are 0 fail-closed skips."""
        self._write_agent("squad-a/coder", {
            "name": "Test Coder", "runtime_id": "rt-1", "description": "d",
            "mcp_config": self._MCP_PLACEHOLDER,
        })
        fake = FakeBw()
        with mock.patch.dict(os.environ, {"BW_SESSION": "ISO:1"}), \
             mock.patch.object(sync.subprocess, "run", side_effect=fake):
            code = self._run("--allow-create")
        self.assertEqual(code, 0, "isolated session should survive the concurrent unlock")
        self.assertEqual(self.backend.created_calls, 1)
        aid = next(iter(self.backend.agents))
        self.assertEqual(
            self.backend.agents[aid]["mcp_config"]["mcpServers"]["svc"]["env"]["TOKEN"],
            "REALKEY", "secret did not resolve to the live value",
        )

    def test_shared_session_concurrent_unlock_aborts_loud(self):
        """Regression teeth: a NON-isolated (default-dir) session IS invalidated
        by a concurrent unlock — the exact CHA-873 failure. It must now abort
        LOUDLY (BitwardenAuthError → non-zero exit), never silently skip every
        agent as 'item not found', and never push a placeholder."""
        self._write_agent("squad-a/coder", {
            "name": "Test Coder", "runtime_id": "rt-1", "description": "d",
            "mcp_config": self._MCP_PLACEHOLDER,
        })
        fake = FakeBw()
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"BW_SESSION": "DEF:1"}), \
             mock.patch.object(sync.subprocess, "run", side_effect=fake), \
             contextlib.redirect_stderr(err):
            code = self._run("--allow-create")
        self.assertEqual(code, 1, "a stale session must fail the run")
        self.assertEqual(self.backend.created_calls, 0, "pushed with an unusable session")
        # Teeth: it must ABORT loudly as an auth failure, NOT take the silent
        # fail-closed skip path (which the old return-None behavior did, hiding
        # the real cause behind a "could not resolve placeholder" skip).
        log = err.getvalue()
        self.assertIn("ABORTED (Bitwarden session)", log)
        self.assertNotIn("SKIPPING push (fail-closed)", log)


class BwSecretResolutionTest(unittest.TestCase):
    """Fail-loud secret resolution (CHA-873): _bw_get_secret distinguishes an
    auth/session failure (raise BitwardenAuthError) from a genuine missing item
    (return None), and never silently returns None on a stale session."""

    def _get(self, item, *, returncode=0, stdout="", stderr="", session="S1"):
        cp = mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)
        environ = dict(os.environ)
        environ.pop("BW_SESSION", None)
        if session is not None:
            environ["BW_SESSION"] = session
        with mock.patch.dict(os.environ, environ, clear=True), \
             mock.patch.object(sync.subprocess, "run", return_value=cp) as run:
            return sync._bw_get_secret(item), run

    def test_stale_session_empty_stdout_raises(self):
        """rc=0 + empty stdout is the stale-session silent-prompt signature."""
        with self.assertRaises(sync.BitwardenAuthError):
            self._get("Some Item", returncode=0, stdout="")

    def test_locked_session_raises(self):
        with self.assertRaises(sync.BitwardenAuthError):
            self._get("Some Item", returncode=1, stderr="Vault is locked.")

    def test_not_logged_in_raises(self):
        with self.assertRaises(sync.BitwardenAuthError):
            self._get("Some Item", returncode=1, stderr="You are not logged in.")

    def test_non_json_stdout_raises(self):
        with self.assertRaises(sync.BitwardenAuthError):
            self._get("Some Item", returncode=0, stdout="? Master password:")

    def test_genuine_not_found_returns_none(self):
        """A real no-match from `list items --search` is a well-formed `[]`."""
        val, _ = self._get("Ghost Item", returncode=0, stdout="[]")
        self.assertIsNone(val)

    def test_missing_field_returns_none(self):
        body = json.dumps([{"name": "Item", "fields": [{"name": "Other", "value": "x", "type": 1}]}])
        val, _ = self._get("Item:Absent", returncode=0, stdout=body)
        self.assertIsNone(val)

    def test_hidden_field_resolves(self):
        body = json.dumps([{"name": "Item", "fields": [{"name": "n", "value": "SEKRET", "type": 1}]}])
        val, _ = self._get("Item", returncode=0, stdout=body)
        self.assertEqual(val, "SEKRET")

    def test_named_field_resolves(self):
        body = json.dumps([{"name": "Item", "fields": [{"name": "API", "value": "V", "type": 0}]}])
        val, _ = self._get("Item:API", returncode=0, stdout=body)
        self.assertEqual(val, "V")

    def test_exact_name_match_beats_substring_collision(self):
        """The substring-collision fix (folded from PR #79): when the search
        returns several items, the exact-name match wins — not the first hit."""
        body = json.dumps([
            {"name": "InfluxDB prod — mqtt bucket token (grafana.252h.org)",
             "fields": [{"name": "n", "value": "WRONG", "type": 1}]},
            {"name": "Grafana",
             "fields": [{"name": "n", "value": "RIGHT", "type": 1}]},
        ])
        val, run = self._get("Grafana", returncode=0, stdout=body)
        self.assertEqual(val, "RIGHT")
        # And it went through list+search, not `bw get item`.
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:4], ["bw", "list", "items", "--search"])

    def test_single_candidate_fallback_resolves(self):
        """One unambiguous hit resolves even without an exact-name match."""
        body = json.dumps([{"name": "Item (renamed)", "fields": [{"name": "n", "value": "V", "type": 1}]}])
        val, _ = self._get("Item", returncode=0, stdout=body)
        self.assertEqual(val, "V")

    def test_multiple_no_exact_match_returns_none(self):
        """Ambiguous (>1 hit, none exact) is a genuine miss — never guess."""
        body = json.dumps([
            {"name": "Item A", "fields": [{"name": "n", "value": "a", "type": 1}]},
            {"name": "Item B", "fields": [{"name": "n", "value": "b", "type": 1}]},
        ])
        val, _ = self._get("Item", returncode=0, stdout=body)
        self.assertIsNone(val)

    def test_passes_nointeraction_and_uses_list_search(self):
        body = json.dumps([{"name": "Item", "fields": [{"name": "n", "value": "x", "type": 1}]}])
        _, run = self._get("Item", returncode=0, stdout=body)
        cmd = run.call_args[0][0]
        self.assertIn("--nointeraction", cmd)
        self.assertEqual(cmd[:4], ["bw", "list", "items", "--search"])

    def test_no_session_returns_none(self):
        """Missing BW_SESSION keeps the historical fail-closed skip (already
        reported loudly by sync.sh) — not an exception."""
        val, _ = self._get("Item", session=None)
        self.assertIsNone(val)


if __name__ == "__main__":
    unittest.main(verbosity=2)

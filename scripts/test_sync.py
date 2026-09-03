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
        # CHA-987: the session key must reach `bw` via the child env, never argv.
        assert "--session" not in cmd, "session key must not appear in bw argv"
        env = kwargs.get("env") or {}
        tok = env.get("BW_SESSION")
        assert tok, "bw call must pass the session key via env[BW_SESSION]"
        if not self._concurrent_unlock_done:
            self._concurrent_unlock_done = True
            self.current["DEF"] = "DEF:2"  # another host process re-keys default
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

        # Second run: a repo edit triggers a genuine update, but the secret no
        # longer resolves — must skip, not wipe. (An unedited agent would now
        # correctly read as "unchanged" — see test_mcp_agent_unchanged_second_run_no_repush.)
        self._write_agent("squad-a/coder", {
            "name": "Test Coder", "runtime_id": "rt-1", "description": "edited",
            "mcp_config": self._MCP_PLACEHOLDER,
        })
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

    # --- Change detection normalizes MCP/custom_env like the baseline (CHA-1092) ---

    def test_mcp_agent_unchanged_second_run_no_repush(self):
        """CHA-1092 regression: _decide_action compared the full mcp_config
        block (placeholder tokens in the repo, resolved secrets live) against the
        sanitized server-name set stored in the baseline, so repo_changed was
        structurally always-true for any MCP-bearing agent. A no-op second run
        must read as unchanged — no update, no reconcile."""
        self._write_agent("squad-a/coder", {
            "name": "Test Coder", "runtime_id": "rt-1", "description": "d",
            "mcp_config": self._MCP_PLACEHOLDER,
        })
        with mock.patch.object(sync, "_bw_get_secret", return_value="REALKEY"):
            code = self._run("--allow-create")
        self.assertEqual(code, 0)
        self.assertEqual(self.backend.created_calls, 1)
        self.assertEqual(self.backend.updated_calls, 0)

        # Second, non-force run: nothing changed — must be a no-op (no update,
        # no repo write, no conflict), not a self-reconcile of the MCP diff.
        with mock.patch.object(sync, "_bw_get_secret", return_value="REALKEY"):
            code = self._run()
        self.assertEqual(code, 0)
        self.assertEqual(self.backend.updated_calls, 0,
                         "unchanged MCP agent was re-pushed (false change-detection)")

    def test_mcp_agent_single_field_edit_pushes_not_conflicts(self):
        """CHA-1092 regression: editing one field of an MCP-bearing agent must
        surface as a repo-side push, never a both-sides conflict (the falsifiable
        repro from the issue: a single-field edit used to flag a conflict)."""
        self._write_agent("squad-a/coder", {
            "name": "Test Coder", "runtime_id": "rt-1", "description": "d",
            "mcp_config": self._MCP_PLACEHOLDER,
        })
        with mock.patch.object(sync, "_bw_get_secret", return_value="REALKEY"):
            code = self._run("--allow-create")
        self.assertEqual(code, 0)
        self.assertEqual(self.backend.created_calls, 1)

        self._write_agent("squad-a/coder", {
            "name": "Test Coder", "runtime_id": "rt-1", "description": "edited",
            "mcp_config": self._MCP_PLACEHOLDER,
        })
        with mock.patch.object(sync, "_bw_get_secret", return_value="REALKEY"):
            code = self._run()
        self.assertEqual(code, 0, "single-field edit must not become a conflict")
        self.assertEqual(self.backend.updated_calls, 1,
                         "single-field edit was swallowed instead of pushed")
        self.assertEqual(
            self.backend.agents[next(iter(self.backend.agents))]["description"],
            "edited",
            "the edited field did not reach Multica",
        )

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
        sync._bw_cache_clear()  # each case must hit the (mocked) backend fresh
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

    def test_resolution_is_memoised_within_a_run(self):
        """The same placeholder resolves via a single `bw` call; a full sync
        reuses ~8 vault items across ~44 agents, so repeats must not re-hit bw."""
        sync._bw_cache_clear()
        body = json.dumps([{"name": "Item", "fields": [{"name": "API", "value": "REALKEY", "type": 1}]}])
        cp = mock.Mock(returncode=0, stdout=body, stderr="")
        with mock.patch.dict(os.environ, {"BW_SESSION": "S1"}), \
             mock.patch.object(sync.subprocess, "run", return_value=cp) as run:
            self.assertEqual(sync._bw_get_secret("Item:API"), "REALKEY")
            self.assertEqual(sync._bw_get_secret("Item:API"), "REALKEY")
            self.assertEqual(sync._bw_get_secret("Item:API"), "REALKEY")
        self.assertEqual(run.call_count, 1, "memoised lookup re-hit bw")

    def test_auth_error_is_not_memoised(self):
        """A BitwardenAuthError must never be cached — a later placeholder must
        still fail loud on the same stale session, not read a poisoned cache."""
        sync._bw_cache_clear()
        cp = mock.Mock(returncode=1, stdout="", stderr="Vault is locked.")
        with mock.patch.dict(os.environ, {"BW_SESSION": "S1"}), \
             mock.patch.object(sync.subprocess, "run", return_value=cp):
            with self.assertRaises(sync.BitwardenAuthError):
                sync._bw_get_secret("Item")
            with self.assertRaises(sync.BitwardenAuthError):
                sync._bw_get_secret("Item")

    # --- 1Password op:// resolution ---

    def _op_get(self, uri, *, returncode=0, stdout="", stderr="", token="op-token"):
        sync._bw_cache_clear()
        cp = mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)
        # Fake $HOME so the resolver's ~/.config/op/service-account-token path
        # is a mock (its is_file/read_text are patchable, unlike a real PosixPath).
        token_file = mock.MagicMock()
        token_file.is_file.return_value = True
        token_file.read_text.return_value = token
        fake_home = mock.MagicMock()
        fake_home.__truediv__.return_value = token_file
        token_file.__truediv__.return_value = token_file  # chained / stays on the fake
        with mock.patch.object(pathlib.Path, "home", return_value=fake_home), \
             mock.patch.object(sync.subprocess, "run", return_value=cp) as run:
            return sync._op_get_secret(uri), run

    def test_op_placeholder_resolves(self):
        val, run = self._op_get("op://Agent Peter/gitlab/password", stdout="glpat-value")
        self.assertEqual(val, "glpat-value")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[0], "op")
        self.assertIn("--no-newline", cmd)
        # The service-account token reaches op via env, never argv.
        self.assertNotIn("OP_SERVICE_ACCOUNT_TOKEN", cmd)
        self.assertEqual(
            run.call_args.kwargs["env"]["OP_SERVICE_ACCOUNT_TOKEN"], "op-token",
        )

    def test_op_genuine_miss_returns_none(self):
        val, _ = self._op_get(
            "op://Agent Peter/nope/password",
            returncode=1,
            stderr='could not read secret ...: "nope" isn\'t an item in the "Agent Peter" vault.',
        )
        self.assertIsNone(val)

    def test_op_missing_token_raises(self):
        sync._bw_cache_clear()
        token_file = mock.MagicMock()
        token_file.is_file.return_value = False
        fake_home = mock.MagicMock()
        fake_home.__truediv__.return_value = token_file
        token_file.__truediv__.return_value = token_file
        with mock.patch.object(pathlib.Path, "home", return_value=fake_home):
            with self.assertRaises(sync.OpAuthError):
                sync._op_get_secret("op://Agent Peter/gitlab/password")

    def test_op_auth_failure_raises(self):
        with self.assertRaises(sync.OpAuthError):
            self._op_get("op://Agent Peter/gitlab/password", returncode=1,
                         stderr="failed to parseToken, format is invalid")

    def test_op_resolution_is_memoised(self):
        sync._bw_cache_clear()
        cp = mock.Mock(returncode=0, stdout="glpat-value", stderr="")
        token_file = mock.MagicMock()
        token_file.is_file.return_value = True
        token_file.read_text.return_value = "op-token"
        fake_home = mock.MagicMock()
        fake_home.__truediv__.return_value = token_file
        token_file.__truediv__.return_value = token_file
        with mock.patch.object(pathlib.Path, "home", return_value=fake_home), \
             mock.patch.object(sync.subprocess, "run", return_value=cp) as run:
            self.assertEqual(sync._bw_get_secret("op://Agent Peter/gitlab/password"), "glpat-value")
            self.assertEqual(sync._bw_get_secret("op://Agent Peter/gitlab/password"), "glpat-value")
        self.assertEqual(run.call_count, 1, "memoised op lookup re-hit `op read`")


class RepoSecretLeakGuardTest(unittest.TestCase):
    """A resolved secret must never be written back into a repo agent.json
    (CHA-85). The leak was the live→repo pull dumping resolved `custom_env`
    values (raw NetBox token + Postgres DSN) into the repo via 15868d7. Repo
    files hold #Item:Field# placeholders only; secrets resolve on push."""

    def setUp(self):
        self.tmp = pathlib.Path(__import__("tempfile").mkdtemp())

    def tearDown(self):
        __import__("shutil").rmtree(self.tmp, ignore_errors=True)

    def test_pull_keeps_repo_placeholder_over_resolved_live_value(self):
        """The core leak: a live agent carrying a *resolved* custom_env must not
        overwrite the repo's #Item:Field# placeholder on live→repo."""
        existing = {"custom_env": {"NETBOX_API_TOKEN": "#readonly chainlayer credentials:NETBOX_TOKEN#"}}
        live = {
            "name": "Maintainer", "runtime_id": "rt-1", "description": "d",
            # what `agent env get` returns — the RESOLVED secret:
            "custom_env": {"NETBOX_API_TOKEN": "vhEatZgTpsKYbcQJdEdHHT1a3NNbuH5ZT8HTW6lh"},
        }
        result = sync.multica_to_agent_json(live, existing)
        self.assertEqual(
            result["custom_env"],
            {"NETBOX_API_TOKEN": "#readonly chainlayer credentials:NETBOX_TOKEN#"},
            "resolved live custom_env overwrote the repo placeholder",
        )

    def test_write_agent_json_rejects_resolved_value(self):
        """write_agent_json must fail closed if a resolved (non-placeholder)
        custom_env value would land in a repo file — e.g. a raw value left in the
        repo file is preserved on pull and would otherwise be re-committed."""
        path = self.tmp / "agent.json"
        path.write_text(json.dumps({
            "name": "A", "runtime_id": "rt-1",
            "custom_env": {"DATAFEEDS_HEALTH_DSN": "postgresql://u:p@host/db"},
        }), encoding="utf-8")
        live = {"name": "A", "runtime_id": "rt-1"}
        with self.assertRaises(sync.RepoSecretLeakError):
            sync.write_agent_json(path, live, dry_run=False)

    def test_write_agent_json_rejects_malformed_nested_custom_env(self):
        """The malformed {"agent_id": …, "custom_env": {…}} shape (also the
        CHA-876 schema error) is rejected — its values are not placeholders."""
        path = self.tmp / "agent.json"
        # Pre-seed a repo file in the malformed shape; a plain pull re-writes it.
        path.write_text(json.dumps({
            "name": "A", "runtime_id": "rt-1",
            "custom_env": {"agent_id": "x", "custom_env": {"K": "#Item:F#"}},
        }), encoding="utf-8")
        live = {"name": "A", "runtime_id": "rt-1"}
        with self.assertRaises(sync.RepoSecretLeakError):
            sync.write_agent_json(path, live, dry_run=False)

    def test_write_agent_json_allows_placeholder(self):
        """A well-formed flat placeholder map is accepted and written."""
        path = self.tmp / "agent.json"
        path.write_text(json.dumps({
            "name": "A", "runtime_id": "rt-1",
            "custom_env": {"DATAFEEDS_HEALTH_DSN": "#DATAFEEDS_HEALTH_DSN:DATAFEEDS_HEALTH_DSN#"},
        }), encoding="utf-8")
        live = {"name": "A", "runtime_id": "rt-1"}
        sync.write_agent_json(path, live, dry_run=False)
        written = json.loads(path.read_text())
        self.assertEqual(
            written["custom_env"],
            {"DATAFEEDS_HEALTH_DSN": "#DATAFEEDS_HEALTH_DSN:DATAFEEDS_HEALTH_DSN#"},
        )


class SkillContentGuardTest(unittest.TestCase):
    """The 2026-09-03 skill deletion and the guards that make it impossible (CHA-1211).

    `multica skill get` made SKILL.md bodies opt-in behind --with-content. The sync
    kept reading `live.get("content", "")`, so every body came back "", the change
    detector called that a workspace edit, and 22 SKILL.md files were rewritten as
    frontmatter only. Two invariants are asserted here: the read asks for the body,
    and no read outcome can ever empty a repo file.
    """

    SKILL = "bitwarden"
    BODY = "# Bitwarden\n\nReal content, several lines.\n"
    FILE_REL = "scripts/detect-access.sh"
    FILE_BODY = "#!/usr/bin/env bash\necho detect\n"

    def setUp(self):
        self.tmp = pathlib.Path(__import__("tempfile").mkdtemp())
        self.ws = self.tmp / WS_NAME
        self.ws.mkdir(parents=True)
        (self.ws / "skills.json").write_text(json.dumps([self.SKILL]), encoding="utf-8")

        self.skills_dir = self.tmp / "skills"
        self.skill_md = self.skills_dir / self.SKILL / "SKILL.md"
        self.support = self.skills_dir / self.SKILL / self.FILE_REL
        sync.write_skill_md(self.skill_md, self.SKILL, "does bitwarden things", self.BODY)
        self.support.parent.mkdir(parents=True, exist_ok=True)
        self.support.write_text(self.FILE_BODY, encoding="utf-8")

        self.state_path = self.tmp / ".sync-state.json"
        # `content` is a live-shape flag, not a value: False reproduces the post-change
        # CLI response (content_hash/content_size, no `content` key at all).
        self.serve_content = True
        self.live_body = self.BODY
        self.live_files = {self.FILE_REL: self.FILE_BODY}
        self.calls = []

        self._patches = [
            mock.patch.object(sync, "REPO_ROOT", self.tmp),
            mock.patch.object(sync, "SKILLS_DIR", self.skills_dir),
            mock.patch.object(sync, "DEFAULT_STATE_PATH", self.state_path),
            mock.patch.object(sync, "WORKSPACE_IDS", {WS_NAME: WS_ID}),
            mock.patch.object(sync, "_multica", self._backend),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        __import__("shutil").rmtree(self.tmp, ignore_errors=True)

    # -- fake CLI ---------------------------------------------------------

    def _backend(self, args, dry_run=False, mutating=False):
        self.calls.append(list(args))
        if args[:2] == ["skill", "list"]:
            return [{"id": "skill-1", "name": self.SKILL, "description": "does bitwarden things"}]
        if args[:2] == ["skill", "get"]:
            return self._skill_detail(with_content="--with-content" in args)
        if args[:2] == ["skill", "update"] or args[:3] == ["skill", "files", "upsert"]:
            return {}
        raise AssertionError(f"unexpected multica call: {args}")

    def _skill_detail(self, with_content):
        detail = {"id": "skill-1", "name": self.SKILL, "description": "does bitwarden things"}
        if with_content and self.serve_content:
            detail["content"] = self.live_body
            detail["files"] = [
                {"path": rel, "content": body} for rel, body in self.live_files.items()
            ]
        else:
            detail["content_hash"] = "deadbeef"
            detail["content_size"] = len(self.live_body)
            detail["files"] = [
                {"path": rel, "content_hash": "cafe", "size": len(body)}
                for rel, body in self.live_files.items()
            ]
        return detail

    def _run(self):
        argv = ["sync.py", "--type", "skills", "--workspace", WS_NAME,
                "--sync-state", str(self.state_path)]
        code = 0
        with mock.patch.object(sys, "argv", argv):
            try:
                sync.main()
            except SystemExit as e:
                code = e.code or 0
        return code

    def _baseline(self, body, files=None):
        """Seed the baseline so both sides read as unchanged for that content."""
        snapshot = {
            "name": self.SKILL,
            "description": "does bitwarden things",
            "body": body,
            "files": dict(files if files is not None else {self.FILE_REL: self.FILE_BODY}),
        }
        self.state_path.write_text(json.dumps({
            "version": 1, "agents": {},
            "skills": {WS_NAME: {self.SKILL: {"repo_state": snapshot,
                                              "multica_state": dict(snapshot)}}},
        }), encoding="utf-8")

    # -- the read ---------------------------------------------------------

    def test_skill_get_asks_for_the_body(self):
        """fetch_skill_detail passes --with-content — without it there is no body."""
        detail = sync.fetch_skill_detail("skill-1")
        self.assertIn(["skill", "get", "skill-1", "--with-content"], self.calls)
        self.assertEqual(detail["content"], self.BODY)

    def test_missing_content_key_is_a_hard_error(self):
        """The eb50a85 response shape raises instead of normalizing to ""."""
        with self.assertRaises(sync.SkillContentUnavailable) as cm:
            sync.normalize_skill_multica(self._skill_detail(with_content=False))
        self.assertIn("--with-content", str(cm.exception))

    def test_missing_files_key_is_a_hard_error(self):
        """The same contract change one level down (CHA-1211 F2).

        A skill with no supporting files returns `files: []` — verified against
        all 32 live skills — so an absent key is always a read failure, and
        recording it as files={} on both baseline sides is the oscillation setup.
        """
        detail = self._skill_detail(with_content=True)
        del detail["files"]
        with self.assertRaises(sync.SkillContentUnavailable) as cm:
            sync.normalize_skill_multica(detail)
        self.assertIn("'files'", str(cm.exception))

    def test_empty_files_list_is_fine(self):
        """files=[] is a legitimate answer and must not be confused with absence."""
        detail = self._skill_detail(with_content=True)
        detail["files"] = []
        self.assertEqual(sync.normalize_skill_multica(detail)["files"], {})

    def test_files_free_response_cannot_gut_the_baseline(self):
        """End to end: a files-free read fails the run and writes no baseline."""
        self.live_files = {}
        self._baseline(self.BODY, files={})
        before = json.loads(self.state_path.read_text())

        original = sync.fetch_skill_detail

        def no_files(skill_id):
            d = original(skill_id)
            d.pop("files", None)
            return d

        with mock.patch.object(sync, "fetch_skill_detail", no_files):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code = self._run()

        self.assertEqual(code, 1)
        self.assertIn("no 'files' key", err.getvalue())
        self.assertEqual(json.loads(self.state_path.read_text()), before,
                         "baseline was rewritten from a files-free read")

    def test_missing_file_content_key_is_a_hard_error(self):
        """Same defaulting on the files array — the 0-byte-script half of the bug."""
        detail = self._skill_detail(with_content=True)
        detail["files"] = [{"path": self.FILE_REL, "content_hash": "cafe", "size": 42}]
        with self.assertRaises(sync.SkillContentUnavailable) as cm:
            sync.normalize_skill_multica(detail)
        self.assertIn(self.FILE_REL, str(cm.exception))

    # -- the write --------------------------------------------------------

    def test_pull_refuses_an_empty_body(self):
        """A pull that would empty SKILL.md raises and leaves the file alone."""
        before = self.skill_md.read_text(encoding="utf-8")
        with self.assertRaises(sync.SkillContentUnavailable):
            sync._pull_skill_to_repo(self.SKILL, {
                "name": self.SKILL, "description": "d", "body": "", "files": {},
            }, dry_run=False)
        self.assertEqual(self.skill_md.read_text(encoding="utf-8"), before)

    def test_pull_refuses_a_zero_byte_supporting_file(self):
        before = self.support.read_text(encoding="utf-8")
        with self.assertRaises(sync.SkillContentUnavailable):
            sync._pull_skill_to_repo(self.SKILL, {
                "name": self.SKILL, "description": "d", "body": self.BODY,
                "files": {self.FILE_REL: ""},
            }, dry_run=False)
        self.assertEqual(self.support.read_text(encoding="utf-8"), before)

    def test_dry_run_pull_refuses_too(self):
        """--dry-run reports the refusal rather than "would write"."""
        with self.assertRaises(sync.SkillContentUnavailable):
            sync._pull_skill_to_repo(self.SKILL, {
                "name": self.SKILL, "description": "d", "body": "", "files": {},
            }, dry_run=True)

    def test_push_refuses_an_emptied_repo_copy(self):
        """The other direction: a gutted repo file never overwrites a live skill.

        This is the tail risk the 02:38 commit left on main — the 22 emptied files
        would have been pushed over the intact workspace copies on the next run.
        """
        sync.write_skill_md(self.skill_md, self.SKILL, "does bitwarden things", "")
        self._baseline(self.BODY)

        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = self._run()

        self.assertEqual(code, 1, "pushing an emptied body must fail the run")
        self.assertIn("PUSH REFUSED", err.getvalue())
        self.assertNotIn(["skill", "update", "skill-1"], [c[:3] for c in self.calls])
        # Baseline untouched: the emptying must not read as synced next run.
        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["skills"][WS_NAME][self.SKILL]["repo_state"]["body"], self.BODY)

    # -- end to end -------------------------------------------------------

    def test_bodyless_response_cannot_gut_the_repo(self):
        """The exact eb50a85 scenario: a body-free read fails the run, changes nothing."""
        self.serve_content = False  # CLI serves no body even when asked
        self._baseline(self.BODY)
        before_md = self.skill_md.read_text(encoding="utf-8")
        before_sh = self.support.read_text(encoding="utf-8")

        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = self._run()

        self.assertEqual(code, 1, "a body-free read must fail the run")
        self.assertIn("fail-closed", err.getvalue())
        self.assertEqual(self.skill_md.read_text(encoding="utf-8"), before_md)
        self.assertEqual(self.support.read_text(encoding="utf-8"), before_sh)
        # And the baseline must not record the empty read as synced.
        state = json.loads(self.state_path.read_text())
        self.assertEqual(
            state["skills"][WS_NAME][self.SKILL]["multica_state"]["body"], self.BODY,
            "baseline was re-written from an incomplete read",
        )

    def test_a_real_workspace_edit_still_pulls(self):
        """The guard blocks emptying, not pulling: a genuine edit lands as before."""
        self._baseline(self.BODY)
        self.live_body = self.BODY + "\nEdited in the workspace UI.\n"

        with contextlib.redirect_stderr(io.StringIO()):
            code = self._run()

        self.assertEqual(code, 0)
        self.assertIn("Edited in the workspace UI.", self.skill_md.read_text(encoding="utf-8"))


class CustomEnvOscillationTest(unittest.TestCase):
    """The nightly `.sync-state.json` flip-flop (CHA-1211 item 12).

    `agent list` never returns `custom_env` — the values are secrets, so it
    returns `has_custom_env` / `custom_env_key_count` instead. `normalize_agent`
    turned that absence into None, `_decide_action` read None as "the live env
    was emptied", and the baseline alternated key-list → null → key-list on
    consecutive runs. The fake below reproduces the real response shape exactly,
    so three consecutive runs are enough to catch it.
    """

    ENV = {"DATAFEEDS_HEALTH_DSN": "#Datafeeds Health DSN:dsn#"}

    class Backend:
        """`agent list` shaped like the real one: no `custom_env`, ever."""

        def __init__(self):
            self.agents = {}
            self.env = {}
            self._seq = 0
            self.pulls_forced = 0
            self.env_readable = False
            self.env_get_calls = 0
            # The contract change this issue is about, applied to `agent list`:
            # the field starts coming back, values and all.
            self.list_returns_env = False

        @staticmethod
        def _flags(tokens):
            out, i = {}, 0
            while i < len(tokens):
                if tokens[i].startswith("--"):
                    if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                        out[tokens[i]] = tokens[i + 1]
                        i += 2
                        continue
                    out[tokens[i]] = True
                i += 1
            return out

        def _listing(self, aid):
            a = dict(self.agents[aid])
            keys = self.env.get(aid) or {}
            a["has_custom_env"] = bool(keys)
            a["custom_env_key_count"] = len(keys)
            if self.list_returns_env:
                a["custom_env"] = dict(keys)
            else:
                a.pop("custom_env", None)  # today's contract: never returned
            return a

        def __call__(self, args, dry_run=False, mutating=False):
            if args[:2] == ["agent", "list"]:
                return [self._listing(aid) for aid in self.agents]
            if args[:2] == ["skill", "list"]:
                return []
            if args[:2] == ["squad", "list"]:
                return []
            if args[:2] == ["agent", "create"]:
                self._seq += 1
                aid = f"agent-uuid-{self._seq:04d}"
                f = self._flags(args[2:])
                if "--custom-env-file" in f:
                    with open(f["--custom-env-file"]) as fh:
                        self.env[aid] = json.load(fh)
                self.agents[aid] = {
                    "id": aid, "workspace_id": WS_ID,
                    "name": f.get("--name"), "description": f.get("--description"),
                    "instructions": f.get("--instructions"),
                    "runtime_id": f.get("--runtime-id"),
                    "model": f.get("--model"), "thinking_level": f.get("--thinking-level"),
                    "visibility": f.get("--visibility"), "custom_args": None,
                    "runtime_config": None, "max_concurrent_tasks": None,
                    "skills": [], "mcp_config": None,
                }
                return self.agents[aid]
            if args[:2] == ["agent", "update"]:
                aid = args[2]
                f = self._flags(args[3:])
                for flag, field in (("--name", "name"), ("--description", "description"),
                                    ("--instructions", "instructions"),
                                    ("--model", "model"), ("--visibility", "visibility")):
                    if flag in f:
                        self.agents[aid][field] = f[flag]
                return self.agents[aid]
            if args[:3] == ["agent", "env", "set"]:
                f = self._flags(args[4:])
                with open(f["--custom-env-file"]) as fh:
                    self.env[args[3]] = json.load(fh)
                return {}
            if args[:3] == ["agent", "env", "get"]:
                # Permission-gated in reality: readable for the agent's owner or
                # a workspace owner/admin, denied for anyone else.
                self.env_get_calls += 1
                if self.env_readable:
                    return dict(self.env.get(args[3]) or {})
                raise RuntimeError("You do not have permission to access this resource.")
            if args[:3] == ["agent", "skills", "set"]:
                return {}
            raise AssertionError(f"unexpected multica call: {args}")

    def setUp(self):
        self.tmp = pathlib.Path(__import__("tempfile").mkdtemp())
        self.ws = self.tmp / WS_NAME
        self.agent_json = self.ws / "squad-a" / "monitor" / "agent.json"
        self.agent_json.parent.mkdir(parents=True)
        self.agent_json.write_text(json.dumps({
            "name": "Datafeeds Health Monitor",
            "runtime_id": "rt-1",
            "description": "watches feeds",
            "custom_env": dict(self.ENV),
        }), encoding="utf-8")

        self.state_path = self.tmp / ".sync-state.json"
        self.backend = self.Backend()
        self._patches = [
            mock.patch.object(sync, "REPO_ROOT", self.tmp),
            mock.patch.object(sync, "DEFAULT_STATE_PATH", self.state_path),
            mock.patch.object(sync, "WORKSPACE_IDS", {WS_NAME: WS_ID}),
            mock.patch.object(sync, "_multica", self.backend),
            mock.patch.object(sync, "_bw_get_secret", return_value="resolved-dsn"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        __import__("shutil").rmtree(self.tmp, ignore_errors=True)

    def _run(self, *extra):
        argv = ["sync.py", "--type", "agents", "--workspace", WS_NAME,
                "--sync-state", str(self.state_path)] + list(extra)
        with mock.patch.object(sys, "argv", argv):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                try:
                    sync.main()
                except SystemExit as e:
                    return (e.code or 0), err.getvalue()
        return 0, err.getvalue()

    def _baseline_env(self):
        state = json.loads(self.state_path.read_text())
        entry = state["agents"][f"{WS_NAME}~Datafeeds Health Monitor"]
        return (entry["repo_state"]["custom_env"], entry["multica_state"]["custom_env"])

    def test_baseline_custom_env_is_stable_across_runs(self):
        """Three consecutive runs: the key list is recorded once and never flips."""
        self._run("--allow-create")
        first = self._baseline_env()
        self.assertEqual(first, (["DATAFEEDS_HEALTH_DSN"], ["DATAFEEDS_HEALTH_DSN"]))

        for run in (2, 3):
            self._run()
            self.assertEqual(
                self._baseline_env(), first,
                f"run {run} flipped the baseline: {self._baseline_env()} != {first}",
            )

    def test_second_run_is_unchanged_not_a_pull(self):
        """The absent field must not read as an edit — no pull, no agent.json rewrite."""
        self._run("--allow-create")
        before = self.agent_json.read_text(encoding="utf-8")

        code, err = self._run()
        self.assertEqual(code, 0)
        self.assertIn("unchanged", err)
        self.assertNotIn("writing repo", err)
        self.assertEqual(self.agent_json.read_text(encoding="utf-8"), before)

    def test_live_env_the_repo_does_not_declare_is_reported_not_guessed(self):
        """has_custom_env with an unaccountable key count: warn, never fabricate."""
        self._run("--allow-create")
        aid = next(iter(self.backend.agents))
        self.backend.env[aid] = {"DATAFEEDS_HEALTH_DSN": "resolved-dsn", "EXTRA_KEY": "y"}

        code, err = self._run()
        self.assertIn("cannot name", err)
        self.assertIn("carrying the baseline forward", err)
        # Baseline keeps what it knew; the count mismatch is not invented into keys.
        self.assertEqual(self._baseline_env()[1], ["DATAFEEDS_HEALTH_DSN"])

    def test_env_get_failure_is_not_an_empty_env(self):
        """_fetch_agent_custom_env raises on a denied read instead of returning None."""
        with self.assertRaises(sync.CustomEnvUnreadable) as cm:
            sync._fetch_agent_custom_env("agent-uuid-0001")
        self.assertIn("permission", str(cm.exception))

    def _entry(self):
        state = json.loads(self.state_path.read_text())
        return state["agents"][f"{WS_NAME}~Datafeeds Health Monitor"]

    def test_pull_baselines_the_file_it_actually_wrote(self):
        """G1: the seventh agent. `repo_state` must describe the file on disk.

        `write_agent_json` deliberately keeps the repo's custom_env/mcp_config
        (they are placeholders; live holds resolved secrets), so a baseline taken
        from the live read claims a file that was never written — and the next
        run reads the repo as "changed back", forever. Setup is the real drift:
        a live env the repo does not declare, with `agent env get` readable.
        """
        self.agent_json.write_text(json.dumps({
            "name": "Datafeeds Health Monitor",
            "runtime_id": "rt-1",
            "description": "watches feeds",
        }), encoding="utf-8")  # no custom_env at all — the actual repo state
        self._run("--allow-create")
        aid = next(iter(self.backend.agents))
        self.backend.env[aid] = {"DATAFEEDS_HEALTH_DSN": "resolved-dsn"}
        self.backend.env_readable = True
        # A live-side edit, so the run pulls.
        self.backend.agents[aid]["description"] = "watches feeds, live edit"

        self._run()
        on_disk = json.loads(self.agent_json.read_text()).get("custom_env")
        self.assertIsNone(on_disk, "the written file should still declare no custom_env")
        self.assertIsNone(
            self._entry()["repo_state"]["custom_env"],
            "baseline claims a custom_env the written file does not have",
        )

        # And therefore it settles instead of alternating.
        for run in (3, 4, 5):
            code, err = self._run()
            self.assertEqual(code, 0, err)
            self.assertIn("unchanged", err, f"run {run} did not settle")
            self.assertNotIn("writing repo", err)

    def test_conflict_payload_is_sanitized(self):
        """G2: the payload is printed to stdout and filed into an issue.

        Step 5 of both sync autopilots parses it, so a resolved secret in it is
        a published secret. Modelled with the contract change this whole issue is
        about: an `agent list` that starts returning custom_env values.
        """
        self._run("--allow-create")
        aid = next(iter(self.backend.agents))
        secret = "postgres://user:sup3rs3cr3t@db.internal/feeds"
        # Both sides move, irreconcilably (description), and the live read now
        # carries the resolved value.
        self.backend.agents[aid]["description"] = "live description"
        self.backend.env[aid] = {"DATAFEEDS_HEALTH_DSN": secret}
        self.backend.list_returns_env = True
        data = json.loads(self.agent_json.read_text())
        data["description"] = "repo description"
        self.agent_json.write_text(json.dumps(data), encoding="utf-8")

        argv = ["sync.py", "--type", "agents", "--workspace", WS_NAME,
                "--sync-state", str(self.state_path)]
        with mock.patch.object(sys, "argv", argv):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with contextlib.redirect_stderr(io.StringIO()):
                    try:
                        sync.main()
                    except SystemExit:
                        pass
        payload = out.getvalue()
        self.assertIn("conflicts", payload, "expected a conflict payload on stdout")
        self.assertNotIn("sup3rs3cr3t", payload, "resolved secret in the conflict payload")
        conflict = json.loads(payload)["conflicts"][0]
        self.assertEqual(conflict["multica_state"]["custom_env"], ["DATAFEEDS_HEALTH_DSN"])

    def test_count_is_not_trusted_when_baseline_and_repo_disagree(self):
        """The count rung: 1 == 1 is not identity (CHA-1211 item 17).

        Every agent with an env has exactly one key, so a count match proves
        nothing on its own. When the two readable sides disagree, one of them is
        wrong about live and the count cannot say which — so pay for the read.
        """
        live = {"id": "a1", "has_custom_env": True, "custom_env_key_count": 1}
        self.backend.env["a1"] = {"LIVE_KEY": "v"}
        self.backend.env_readable = True
        repo_norm = {"custom_env": json.dumps({"REPO_KEY": "#x:y#"})}
        last = {"multica_state": {"custom_env": ["BASELINE_KEY"]}}

        value, note = sync._live_custom_env_for_state(live, repo_norm, last)

        self.assertEqual(sorted(value), ["LIVE_KEY"],
                         "resolved to a key set that was never live")
        self.assertIsNone(note)
        self.assertEqual(self.backend.env_get_calls, 1)

    def test_count_is_trusted_when_both_sides_agree(self):
        """The steady state stays free — no audited call for the settled case."""
        live = {"id": "a1", "has_custom_env": True, "custom_env_key_count": 1}
        self.backend.env_readable = True
        repo_norm = {"custom_env": json.dumps({"DATAFEEDS_HEALTH_DSN": "#x:y#"})}
        last = {"multica_state": {"custom_env": ["DATAFEEDS_HEALTH_DSN"]}}

        value, note = sync._live_custom_env_for_state(live, repo_norm, last)

        self.assertEqual(sorted(value), ["DATAFEEDS_HEALTH_DSN"])
        self.assertIsNone(note)
        self.assertEqual(self.backend.env_get_calls, 0, "steady state must cost no CLI call")

    def test_known_residual_a_rename_both_sides_missed_is_invisible(self):
        """Documented limitation, asserted so it cannot be mistaken for a fix.

        If the baseline and the repo agree AND the count is unchanged, the
        response carries no signal that live moved, so rung 3 reuses a set that
        is no longer live. Closing this needs a re-read trigger (the agent's
        `updated_at` in the baseline) — a state-format change, not done here.
        The direction is safe: it reads as `unchanged`, so nothing is written.
        """
        live = {"id": "a1", "has_custom_env": True, "custom_env_key_count": 1}
        self.backend.env["a1"] = {"RENAMED_LIVE": "v"}
        self.backend.env_readable = True
        repo_norm = {"custom_env": json.dumps({"OLD_NAME": "#x:y#"})}
        last = {"multica_state": {"custom_env": ["OLD_NAME"]}}

        value, _ = sync._live_custom_env_for_state(live, repo_norm, last)
        self.assertEqual(sorted(value), ["OLD_NAME"])
        self.assertEqual(self.backend.env_get_calls, 0)

    def test_carry_forward_says_so_on_stderr(self):
        """Item 18: a no-op guard whose only trigger is the next contract change
        must announce itself, or it hides the very event it exists to catch."""
        norm = {"instructions": None}
        live = {}
        last = {"multica_state": {"instructions": "the real instructions"}}
        with contextlib.redirect_stderr(io.StringIO()) as err:
            sync._carry_forward_unread_fields(norm, live, last)
        self.assertIn("omitted instructions", err.getvalue())
        self.assertIn("CHANGED READ CONTRACT", err.getvalue())

    def test_an_unread_comparable_field_is_carried_forward(self):
        """F4, generalized: any field the response omits keeps its baseline value."""
        norm = {"instructions": None, "description": "live"}
        live = {"description": "live"}  # `instructions` absent from the read
        last = {"multica_state": {"instructions": "the real instructions",
                                  "description": "live"}}
        out = sync._carry_forward_unread_fields(norm, live, last)
        self.assertEqual(out["instructions"], "the real instructions")
        self.assertEqual(out["description"], "live")


if __name__ == "__main__":
    unittest.main(verbosity=2)

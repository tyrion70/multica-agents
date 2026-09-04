#!/usr/bin/env python3
"""
sync.py — Bidirectional reconciliation: multica-agents repo ↔ Multica workspace.

Handles both agents and skills. Detects which side changed since the last sync
using a .sync-state.json snapshot file and applies the correct direction:

  repo changed, Multica unchanged  → push repo → Multica (create or update)
  Multica changed, repo unchanged  → pull Multica → repo (writes files)
  both changed                     → conflict: printed to stderr + JSON on stdout, exit 2
  neither changed                  → unchanged

On first sync (no state file), repo is treated as source of truth.

After a run that writes files back to the repo, the caller is responsible for
committing and pushing them (including .sync-state.json).

Exit codes:
  0  success (no conflicts)
  1  one or more errors (schema validation, API failure, etc.) OR one or more
     agents skipped fail-closed (a secret placeholder could not be resolved)
  2  one or more conflicts (no errors; manual resolution needed)

Usage:
  scripts/sync.py                              # sync agents + skills, all workspaces
  scripts/sync.py --type agents                # agents only
  scripts/sync.py --type skills                # skills only
  scripts/sync.py --workspace Chainlayer       # one workspace; passes --workspace-id to every CLI call
  scripts/sync.py --workspace Private          # Private workspace (9627be94-...)
  scripts/sync.py --dry-run                    # print what would happen, no writes
  scripts/sync.py --force                      # re-resolve + re-push every agent's mcp_config (full restore)
  scripts/sync.py --sync-state /tmp/state.json # alternate state file

Workspace IDs (same Multica instance, multica.252h.org):
  Chainlayer  0014efc5-f6fb-42bf-9616-4aaeb07ce237  (default on multica-02)
  Private     9627be94-0c29-49f7-a104-dff19d11a089  (default on multica-01)

Skills folder layout:
  skills/<name>/SKILL.md           # frontmatter (name, description) + body
  skills/<name>/<any-subdir>/...   # optional supporting files

Each workspace directory may contain a skills.json listing the skill names
owned by that workspace: ["bitwarden", "ssh", ...]
"""

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "agent.json"
SKILLS_DIR = REPO_ROOT / "skills"
DEFAULT_STATE_PATH = REPO_ROOT / ".sync-state.json"
SKIP_DIRS = {"schemas", "scripts", ".git", "skills", "claude-config"}

# Per-workspace agent UUID sidecar. Maps a stable, rename-proof key (the agent's
# directory path relative to the workspace dir, e.g. "_shared/maintainer" or
# "chainlayer-squad-claude/issue-coder") to the Multica agent UUID. Stored per
# workspace because the same agent name (e.g. "Private Maintainer") resolves to a
# different UUID in each workspace, so a single id field in agent.json won't do.
# This is the identity anchor: as long as the directory exists, sync upserts the
# same agent by id and never mints a fresh UUID on a name-lookup miss.
AGENT_IDS_FILENAME = "agent-ids.json"

# Default cap on how many agents a single run may create. A run that should be a
# no-op never creates anything (creates require --allow-create); this is a second
# safety net so a mis-scoped agent list can never mass-mint agents. Raise it with
# --max-creates for a deliberate bulk bootstrap.
DEFAULT_MAX_CREATES = 2

MULTICA = os.environ.get("MULTICA", "multica")

# Workspace slug → UUID mapping.
# Both workspaces live on the same Multica instance (multica.252h.org).
# Passing --workspace <slug> resolves to a UUID that is forwarded to every
# multica CLI call as --workspace-id <uuid>.
WORKSPACE_IDS = {
    "Chainlayer": "0014efc5-f6fb-42bf-9616-4aaeb07ce237",
    "Private": "9627be94-0c29-49f7-a104-dff19d11a089",
}

# Machine defaults (informational; used by the sync autopilots):
#   multica-01  → Private workspace
#   multica-02  → Chainlayer workspace

# Set by main() when --workspace resolves to a known UUID; injected into every
# CLI call as a global --workspace-id flag.
_workspace_id: Optional[str] = None

COMPARABLE_FIELDS = (
    "name",
    "description",
    "instructions",
    "runtime_id",
    "model",
    "thinking_level",
    "custom_args",
    "runtime_config",
    "visibility",
    "max_concurrent_tasks",
    "skills",
    "mcp_config",
    "custom_env",
)


# ---------------------------------------------------------------------------
# Multica CLI wrapper
# ---------------------------------------------------------------------------

def _multica(args: List[str], dry_run: bool = False, mutating: bool = False) -> Any:
    """Run a multica CLI command and return parsed JSON output.

    Pass mutating=True for commands that write data so dry-run can skip them.
    """
    assert len(args) > 0

    def _dry_run_cmd() -> str:
        flags = (["--workspace-id", _workspace_id] if _workspace_id else [])
        return f"{MULTICA} {' '.join(flags + args)}"

    if dry_run and mutating:
        print(f"      [DRY-RUN] would run: {_dry_run_cmd()}", file=sys.stderr)
        return None

    # Legacy agent mutation detection for backwards compatibility
    agent_mutating = (
        args[0] == "agent"
        and len(args) >= 2
        and args[1] in {"create", "update", "skills"}
    )
    if dry_run and agent_mutating:
        print(f"      [DRY-RUN] would run: {_dry_run_cmd()}", file=sys.stderr)
        return None

    global_flags = ["--workspace-id", _workspace_id] if _workspace_id else []
    cmd = [MULTICA] + global_flags + args + ["--output", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"multica command failed (exit {result.returncode}):\n"
            f"  command: {' '.join(cmd)}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Schema validation (agents)
# ---------------------------------------------------------------------------

def load_schema() -> Dict[str, Any]:
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def validate_agent_json(path: pathlib.Path, schema: Dict[str, Any]) -> Dict[str, Any]:
    import jsonschema

    with open(path) as f:
        data = json.load(f)
    jsonschema.validate(data, schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)
    return data


def get_workspace_dirs() -> List[pathlib.Path]:
    ws: List[pathlib.Path] = []
    for entry in sorted(REPO_ROOT.iterdir()):
        if entry.is_dir() and not entry.name.startswith(".") and entry.name not in SKIP_DIRS:
            ws.append(entry)
    return ws


# ---------------------------------------------------------------------------
# Agent normalization
# ---------------------------------------------------------------------------

def _norm_agent_field(key: str, val: Any) -> Any:
    if key in ("model", "thinking_level"):
        return val or ""
    if key == "skills":
        if not isinstance(val, list):
            return []
        names = []
        for item in val:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                names.append(item.get("name") or item.get("slug") or "")
        return sorted(names)
    if key == "mcp_config":
        if val is None:
            return None
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return val
        if isinstance(val, dict):
            return json.dumps(val, sort_keys=True)
        return val
    if key == "custom_env":
        if val is None:
            return None
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return val
        if isinstance(val, dict):
            return json.dumps(val, sort_keys=True)
        return val
    return val


def normalize_agent(data: Dict[str, Any]) -> Dict[str, Any]:
    return {f: _norm_agent_field(f, data.get(f)) for f in COMPARABLE_FIELDS}


# ---------------------------------------------------------------------------
# Sync state file
# ---------------------------------------------------------------------------

def load_sync_state(state_path: pathlib.Path) -> Dict[str, Any]:
    if not state_path.is_file():
        return {"version": 1, "agents": {}, "skills": {}}
    try:
        with open(state_path) as f:
            state = json.load(f)
        state.setdefault("agents", {})
        state.setdefault("skills", {})
        return state
    except Exception as e:
        print(f"WARNING: could not read state file {state_path}: {e}", file=sys.stderr)
        return {"version": 1, "agents": {}, "skills": {}}


def save_sync_state(state_path: pathlib.Path, state: Dict[str, Any]) -> None:
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------------------
# Per-workspace agent UUID sidecar (the identity anchor — Option A)
# ---------------------------------------------------------------------------

def agent_ids_path(workspace_dir: pathlib.Path) -> pathlib.Path:
    return workspace_dir / AGENT_IDS_FILENAME


def load_agent_ids(workspace_dir: pathlib.Path) -> Dict[str, str]:
    path = agent_ids_path(workspace_dir)
    if not path.is_file():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if v}
    except Exception as e:
        print(f"WARNING: could not read {path}: {e}", file=sys.stderr)
    return {}


def save_agent_ids(workspace_dir: pathlib.Path, id_map: Dict[str, str], dry_run: bool) -> None:
    path = agent_ids_path(workspace_dir)
    if dry_run:
        print(f"      [DRY-RUN] would write {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        return
    with open(path, "w") as f:
        json.dump(dict(sorted(id_map.items())), f, indent=2, ensure_ascii=False)
        f.write("\n")


def agent_key(agent_dir: pathlib.Path, workspace_dir: pathlib.Path) -> str:
    """Stable, rename-proof identity key: the agent directory relative to its
    workspace dir, as a POSIX path (e.g. '_shared/maintainer')."""
    return agent_dir.relative_to(workspace_dir).as_posix()


class CreateBudgetExceeded(RuntimeError):
    """Raised to abort the whole run when the number of would-be creates exceeds
    the configured threshold — the mass-mint safety net."""


class CreateGuard:
    """Gatekeeps agent creation. Creation requires an explicit opt-in
    (--allow-create); even then it is capped at max_creates per run so a
    mis-scoped agent list can never mass-mint agents."""

    def __init__(self, allow_create: bool, max_creates: int):
        self.allow_create = allow_create
        self.max_creates = max_creates
        self.used = 0

    def authorize(self, label: str) -> None:
        """Raise if a create is not permitted. Call immediately before creating.

        - No --allow-create  → refuse (no silent mint on a name-lookup miss).
        - Over the threshold → abort the entire run (mass-mint guard).
        """
        if not self.allow_create:
            raise PermissionError(
                f"refusing to create '{label}': identity anchor missing and "
                f"--allow-create not set (no silent agent creation)"
            )
        if self.used >= self.max_creates:
            raise CreateBudgetExceeded(
                f"create threshold exceeded while creating '{label}': "
                f"{self.used + 1} creates requested, limit is {self.max_creates}. "
                f"Aborting to avoid mass-minting agents (raise --max-creates for a "
                f"deliberate bulk bootstrap)."
            )

    def record(self) -> None:
        self.used += 1


# ---------------------------------------------------------------------------
# Agent write-back
# ---------------------------------------------------------------------------

def multica_to_agent_json(
    live: Dict[str, Any],
    existing: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    # Emitted in COMPARABLE_FIELDS order, every field in the same pass — including
    # custom_env and mcp_config, which used to be copied from `existing` in a
    # preamble and therefore came out FIRST. That put the writer's own output in a
    # different key order from the 38 files it does not touch, so the first pull of
    # any such agent reordered the whole file: a diff the reader never asked for, and
    # one the commit-scope guard then refuses. Same rule as the ""/null coercion
    # below — never write a change nobody made (CHA-1211).
    for field in COMPARABLE_FIELDS:
        if field == "skills":
            result["skills"] = _norm_agent_field("skills", live.get("skills"))
        elif field in ("model", "thinking_level"):
            val = live.get(field)
            # `""` and `null` BOTH mean "runtime default" — schemas/agent.json says
            # so in as many words for both fields — so rewriting one into the other
            # changes the file without changing its meaning. This coerced every `""`
            # to `null`, which invented a value neither side held: live had `""`, the
            # repo had `""`, and the pull wrote `null`.
            #
            # It is worse than cosmetic. The commit-scope guard refuses the resulting
            # dirty file, so the change can never land; the next run fast-forwards
            # main back to `""`, rewrites it to `null`, and is refused again — every
            # night, indefinitely (CHA-1216).
            #
            # Note what the fix is NOT: "a `""` read stays `""`" on its own would
            # rewrite `thinking_level: null` to `""` in 45 files that currently agree
            # with the writer, trading one spurious diff for forty-five. The rule that
            # holds in both directions is: when the two forms are equivalent, keep
            # whichever one the repo already uses, and never write a change the reader
            # cannot see.
            if (
                existing
                and field in existing
                and val in ("", None)
                and existing[field] in ("", None)
            ):
                result[field] = existing[field]
            else:
                result[field] = val
        elif field in ("mcp_config", "custom_env"):
            # Secret-bearing: the repo holds #Item:Field# placeholders that are
            # resolved ONLY when pushing repo→live. Never source these from `live` —
            # the live values are the *resolved* secrets, and writing those into a
            # repo file is the leak that put a raw NetBox token and a datafeeds
            # Postgres DSN onto `main` (CHA-85, commit 15868d7). So on live→repo we
            # only ever carry the existing repo placeholders through; the fail-closed
            # guard in write_agent_json is the backstop if a resolved value ever
            # reaches this path.
            if existing and field in existing:
                result[field] = existing[field]
        else:
            # K1: a field absent (or null) in the read is omitted rather than
            # written, so it keeps whatever the repo file already had — the same
            # "never write a change the reader cannot see" rule as the two branches
            # above. Zero files are affected today: all 46 live agents report a real
            # value for every field that reaches this branch. Recorded rather than
            # coded, because a guard for a case that cannot occur is a guard nobody
            # can test (CHA-1211 K1).
            val = live.get(field)
            if val is not None:
                result[field] = val
    return result


class RepoSecretLeakError(RuntimeError):
    """Raised when a *resolved* secret value would be written into a repo
    agent.json. Repo files must only ever hold #Item:Field# placeholders for
    secret-bearing fields; resolution happens solely on push (repo→live). This
    guard makes the live→repo leak (CHA-85, commit 15868d7 — a raw NetBox token
    and a Postgres DSN with embedded creds) structurally impossible: a run fails
    loud on the offending agent rather than committing a plaintext secret."""

    def __init__(self, field: str, keys: List[str]):
        self.field = field
        self.keys = sorted(keys)
        super().__init__(
            f"refusing to write resolved secret value(s) into repo {field}: "
            f"{', '.join(self.keys)} — repo files must hold #Item:Field# "
            f"placeholders only (secrets resolve on push, never on pull)"
        )


def _assert_custom_env_placeholders(custom_env: Any) -> None:
    """Fail closed if custom_env carries any non-placeholder (resolved) value.

    A repo custom_env must be a flat {KEY: "#Item:Field#"} map — every value a
    string containing a #…# placeholder. Anything else (a raw secret, or the
    malformed {"agent_id": …, "custom_env": {…}} nesting the leak produced) is
    rejected before it can reach a repo file.
    """
    if custom_env is None:
        return
    if isinstance(custom_env, str):
        try:
            custom_env = json.loads(custom_env)
        except (json.JSONDecodeError, TypeError):
            return
    if not isinstance(custom_env, dict):
        raise RepoSecretLeakError("custom_env", ["<non-object custom_env>"])
    leaked = [
        str(k) for k, v in custom_env.items()
        if not (isinstance(v, str) and _PLACEHOLDER_RE.search(v))
    ]
    if leaked:
        raise RepoSecretLeakError("custom_env", leaked)


def write_agent_json(
    agent_json_path: pathlib.Path,
    live_agent: Dict[str, Any],
    dry_run: bool,
) -> Dict[str, Any]:
    """Write the repo agent.json from a live read; return what was written.

    The return value is the point: this function deliberately does NOT take
    custom_env/mcp_config from live (see multica_to_agent_json — those are
    resolved secrets), so the file on disk is not the live state. A caller that
    baselines `multica_norm` after calling this records a file that was never
    written, and the next run sees the repo "change back" (CHA-1211 G1).
    Baseline the return value instead.
    """
    existing: Optional[Dict[str, Any]] = None
    if agent_json_path.is_file():
        with open(agent_json_path) as f:
            existing = json.load(f)
    new_data = multica_to_agent_json(live_agent, existing)
    # Backstop: never persist a resolved secret to a repo file (CHA-85).
    _assert_custom_env_placeholders(new_data.get("custom_env"))
    if dry_run:
        print(f"      [DRY-RUN] would write {agent_json_path}", file=sys.stderr)
        return new_data
    agent_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(agent_json_path, "w") as f:
        json.dump(new_data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return new_data


# ---------------------------------------------------------------------------
# Agent live data
# ---------------------------------------------------------------------------

def fetch_live_agents(dry_run: bool) -> Dict[str, Dict[str, Any]]:
    agents = _multica(["agent", "list"], dry_run=False)
    return {a["name"]: a for a in agents}


def fetch_live_agent_skills(dry_run: bool) -> Dict[str, str]:
    skills = _multica(["skill", "list"], dry_run=False)
    return {s["name"]: s["id"] for s in skills}


def ensure_agent_skills(
    agent_id: str,
    desired_skill_names: List[str],
    skill_name_to_id: Dict[str, str],
    dry_run: bool,
) -> None:
    desired_ids: List[str] = []
    missing: List[str] = []
    for name in desired_skill_names:
        sid = skill_name_to_id.get(name)
        if sid:
            desired_ids.append(sid)
        else:
            missing.append(name)
    if missing:
        print(f"      WARNING: skills not found in workspace: {', '.join(missing)}", file=sys.stderr)
    _multica(["agent", "skills", "set", agent_id, "--skill-ids", ",".join(desired_ids)], dry_run=dry_run)


def build_create_args(agent_data: Dict[str, Any]) -> List[str]:
    args: List[str] = []
    args += ["--name", agent_data["name"]]
    args += ["--runtime-id", agent_data["runtime_id"]]
    for field, flag in [
        ("description", "--description"),
        ("instructions", "--instructions"),
        ("model", "--model"),
        ("thinking_level", "--thinking-level"),
        ("visibility", "--visibility"),
    ]:
        val = agent_data.get(field)
        if val is not None and val != "":
            args += [flag, str(val)]
    mt = agent_data.get("max_concurrent_tasks")
    if mt is not None:
        args += ["--max-concurrent-tasks", str(mt)]
    ca = agent_data.get("custom_args")
    if ca:
        args += ["--custom-args", json.dumps(ca)]
    rc = agent_data.get("runtime_config")
    if rc:
        args += ["--runtime-config", json.dumps(rc)]
    return args


def build_update_args(agent_id: str, agent_data: Dict[str, Any]) -> List[str]:
    args: List[str] = [agent_id]
    for field, flag in [
        ("name", "--name"),
        ("description", "--description"),
        ("instructions", "--instructions"),
        ("model", "--model"),
        ("thinking_level", "--thinking-level"),
        ("visibility", "--visibility"),
        ("runtime_id", "--runtime-id"),
    ]:
        val = agent_data.get(field)
        if val is not None and val != "":
            args += [flag, str(val)]
    mt = agent_data.get("max_concurrent_tasks")
    if mt is not None:
        args += ["--max-concurrent-tasks", str(mt)]
    ca = agent_data.get("custom_args")
    if ca is not None:
        args += ["--custom-args", json.dumps(ca)]
    rc = agent_data.get("runtime_config")
    if rc is not None:
        args += ["--runtime-config", json.dumps(rc)]
    return args


_PLACEHOLDER_RE = re.compile(r"#([^#]+)#")

# stderr fragments (lowercased) that mean the bw session is dead/unusable — an
# AUTH failure, not a missing item. A stale session on this shared host is the
# CHA-873 root cause: with `--nointeraction` bw exits non-zero with one of these
# instead of silently dropping to a `? Master password:` prompt and printing
# nothing (rc=0, empty stdout), which used to masquerade as "item not found".
_BW_AUTH_MARKERS = (
    "vault is locked",
    "you are not logged in",
    "not logged in",
    "session key",
    "invalid master password",
    "mac failed",
)


class BitwardenAuthError(RuntimeError):
    """The bw session is missing/stale/locked — an auth failure that affects
    *every* item, distinct from a single item being absent. Raised (never
    swallowed as a None "not found") so the sync aborts loudly instead of
    skipping every agent as if all their secrets had vanished (CHA-873)."""


class OpAuthError(RuntimeError):
    """The 1Password service-account token is missing/unusable (or `op` itself
    failed) — an auth failure that affects every `op://` reference, distinct
    from a single item being absent. Raised (never swallowed as a None "not
    found") so the sync aborts loudly instead of skipping every agent as if all
    their secrets had vanished."""


# Per-run memo of resolved Bitwarden lookups. The same handful of vault items
# (~8: the MCP tokens + the two custom_env secrets) appears across all ~44
# agents' mcp_config/custom_env, so without this a single full sync fires
# hundreds of slow `bw list items` calls against the self-hosted Vaultwarden and
# blows every timeout. Keyed by the raw placeholder body ("Item" or
# "Item:Field"); stores the resolved value or None for a genuine miss. Auth
# failures are never cached (they are transient); the cache is cleared at the
# start of each sync run.
_BW_SECRET_CACHE: Dict[str, Optional[str]] = {}

# Same per-run memo for 1Password references (bodies like "op://Vault/Item/Field").
_OP_SECRET_CACHE: Dict[str, Optional[str]] = {}


def _bw_cache_clear() -> None:
    _BW_SECRET_CACHE.clear()
    _OP_SECRET_CACHE.clear()


def _bw_get_secret(item_name: str) -> Optional[str]:
    """Resolve a vault secret, memoised per run (see _BW_SECRET_CACHE).

    Routes `op://…` references (1Password) to _op_get_secret; everything else
    is a Bitwarden lookup. A BitwardenAuthError/OpAuthError from the underlying
    lookup propagates uncached so a stale session still fails loud on every
    subsequent placeholder.
    """
    if item_name.startswith("op://"):
        return _op_get_secret(item_name)
    if item_name in _BW_SECRET_CACHE:
        return _BW_SECRET_CACHE[item_name]
    val = _bw_get_secret_uncached(item_name)
    _BW_SECRET_CACHE[item_name] = val
    return val


def _op_get_secret(item_uri: str) -> Optional[str]:
    """Resolve a 1Password reference like #op://Vault/Item/Field#.

    Reads the service-account token at point of use (never exported to the
    session), runs `op read --no-newline <uri>`, and returns the value.

    Returns None only for a genuine miss (item/field not found); raises
    OpAuthError when the token is missing/unusable or `op` itself fails, so a
    vault auth problem aborts loudly instead of skipping every agent.
    """
    if item_uri in _OP_SECRET_CACHE:
        return _OP_SECRET_CACHE[item_uri]

    token_path = pathlib.Path.home() / ".config" / "op" / "service-account-token"
    if not token_path.is_file():
        raise OpAuthError(f"missing 1Password service-account token at {token_path}")
    try:
        token = token_path.read_text().strip()
    except OSError as e:
        raise OpAuthError(f"could not read 1Password service-account token at {token_path}: {e}")
    if not token:
        raise OpAuthError(f"1Password service-account token is empty at {token_path}")

    try:
        result = subprocess.run(
            ["op", "read", "--no-newline", item_uri],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "OP_SERVICE_ACCOUNT_TOKEN": token},
        )
    except Exception as e:
        raise OpAuthError(f"`op read {item_uri}` failed to run: {e}")

    if result.returncode != 0:
        stderr = (result.stderr or "").lower()
        if any(m in stderr for m in ("isn't an item", "could not find", "not found")):
            _OP_SECRET_CACHE[item_uri] = None
            return None
        raise OpAuthError(
            f"`op read {item_uri}` exited {result.returncode}: {result.stderr.strip()}"
        )
    val = result.stdout
    _OP_SECRET_CACHE[item_uri] = val
    return val


def _bw_get_secret_uncached(item_name: str) -> Optional[str]:
    """Resolve a Bitwarden secret.

    Supports two formats:
      #Item Name#              — the item (exact name), return the first hidden field.
      #Item Name:Field Name#   — the item (exact name), return the named field.

    Looks the item up with `bw list items --search` + exact-name match (not
    `bw get item`, whose substring matching collides on shared substrings), using
    BW_SESSION from the environment (set by sync.sh after unlock).

    Returns None only for a *genuine miss* — the item (or the named field) does
    not exist. A dead/stale/locked session raises BitwardenAuthError so it can
    never be mistaken for a missing item and silently skipped fail-closed.
    """
    field_name: Optional[str] = None
    if ":" in item_name:
        item_name, field_name = item_name.split(":", 1)
        item_name = item_name.strip()
        field_name = field_name.strip()

    bw_session = os.environ.get("BW_SESSION")
    if not bw_session:
        # No session at all is handled loudly upstream (sync.sh already printed
        # the unlock error); keep the historical fail-closed skip for this case.
        return None

    # Resolve via `bw list items --search` + exact-name match, not `bw get item
    # <name>`: get does substring matching and fails (or returns the wrong item)
    # when several items share a substring — e.g. "grafana" also matches
    # "InfluxDB prod — mqtt bucket token (grafana.252h.org)". list+search returns
    # every candidate so we can pick the exact name. A genuine no-match is a
    # well-formed empty array `[]` (rc=0), which stays cleanly distinct from the
    # empty/locked stdout a stale session produces — so fail-loud still holds.
    cmd_desc = f"bw list items --search '{item_name}'"
    try:
        result = subprocess.run(
            ["bw", "list", "items", "--search", item_name, "--nointeraction"],
            capture_output=True, text=True, timeout=15,
            # CHA-987: hand the session key via the child env (BW_SESSION), never
            # argv — the --session flag lands the vault-wide key in world-readable
            # /proc/<pid>/cmdline.
            env={**os.environ, "BW_SESSION": bw_session},
        )
    except Exception as e:
        raise BitwardenAuthError(f"`{cmd_desc}` failed to run: {e}")

    stderr = (result.stderr or "").strip()
    stderr_l = stderr.lower()
    stdout = (result.stdout or "").strip()

    # Auth failure: a locked/stale/invalid session. Fail LOUD.
    if any(marker in stderr_l for marker in _BW_AUTH_MARKERS):
        raise BitwardenAuthError(
            f"bw session is not usable while resolving '{item_name}': {stderr}"
        )
    if result.returncode != 0:
        # `list items` reports a no-match as rc=0 `[]`, so any non-zero exit is a
        # real failure (network/session), never a plain miss — fail LOUD.
        raise BitwardenAuthError(
            f"`{cmd_desc}` exited {result.returncode}: {stderr or '(no stderr)'}"
        )
    if not stdout:
        # rc=0 with empty stdout is the stale-session silent-prompt signature —
        # a real no-match is `[]`, never empty — so empty means auth failure.
        raise BitwardenAuthError(
            f"`{cmd_desc}` returned empty output (stale session?)"
        )
    try:
        candidates = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise BitwardenAuthError(
            f"`{cmd_desc}` returned non-JSON output ({e}); "
            "treating as an auth failure rather than a missing item"
        )

    # Pick the exact-name match; fall back to the sole candidate only when the
    # search is unambiguous (one hit). No match is a genuine miss (None), which
    # the caller fails closed on — never a key-wipe.
    data: Optional[Dict[str, Any]] = None
    for candidate in candidates:
        if candidate.get("name") == item_name:
            data = candidate
            break
    if data is None and len(candidates) == 1:
        data = candidates[0]
    if data is None:
        return None

    # From here we have the resolved item: a missing field IS a genuine miss.
    if field_name:
        for field in (data.get("fields") or []):
            if field.get("name") == field_name:
                return field.get("value")
        return None
    for field in (data.get("fields") or []):
        if field.get("type") == 1:
            return field.get("value")
    notes = (data.get("notes") or "").strip()
    return notes if notes else None


class SecretResolutionError(RuntimeError):
    """Raised when an mcp_config/custom_env `#…#` placeholder cannot be resolved
    to a real secret (BW_SESSION missing/expired, the 1Password token missing,
    or the vault item is not found). The sync fails closed on this: the agent's
    config is skipped and never pushed, so an unresolved placeholder can never
    be written over a live agent's MCP keys (the CHA-790 key-wipe: the old code
    logged "leaving placeholder as-is" and pushed it anyway)."""

    def __init__(self, unresolved: List[str]):
        self.unresolved = sorted(set(unresolved))
        super().__init__(
            "could not resolve vault placeholder(s): "
            + ", ".join(f"#{name}#" for name in self.unresolved)
        )


def _resolve_mcp_secrets(mcp_config: Any) -> Any:
    """Walk mcp_config recursively, replacing #Item Name# placeholders
    with real secrets fetched live from Bitwarden via bw CLI.

    Fails closed: if any placeholder can't be resolved (missing BW_SESSION or an
    unknown item), raises SecretResolutionError rather than returning a config
    that still holds the raw placeholder. The caller skips the agent instead of
    overwriting live keys with a `#…#` string.
    """
    unresolved: List[str] = []

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(v) for v in node]
        if isinstance(node, str):
            def _replace(m: re.Match) -> str:
                item_name = m.group(1).strip()
                val = _bw_get_secret(item_name)
                if val is None:
                    unresolved.append(item_name)
                    return m.group(0)
                return val
            return _PLACEHOLDER_RE.sub(_replace, node)
        return node

    resolved = _walk(mcp_config)
    if unresolved:
        raise SecretResolutionError(unresolved)
    return resolved


def _write_mcp_config_tempfile(agent_data: Dict[str, Any]) -> Optional[str]:
    mcp = agent_data.get("mcp_config")
    if mcp is None:
        return None
    mcp = _resolve_mcp_secrets(mcp)
    fd, path = tempfile.mkstemp(suffix=".json", prefix="mcp-config-")
    with os.fdopen(fd, "w") as f:
        json.dump(mcp, f)
    return path


def _write_custom_env_tempfile(agent_data: Dict[str, Any]) -> Optional[str]:
    """Resolve #Item Name# placeholders in custom_env and write to a temp file.

    Returns the temp file path, or None if custom_env is not set.
    """
    custom_env = agent_data.get("custom_env")
    if custom_env is None:
        return None
    resolved = _resolve_mcp_secrets(custom_env)
    fd, path = tempfile.mkstemp(suffix=".json", prefix="custom-env-")
    with os.fdopen(fd, "w") as f:
        json.dump(resolved, f)
    return path


class CustomEnvUnreadable(RuntimeError):
    """`agent env get` could not be read — NOT the same as "the agent has none".

    The endpoint is permission-gated to the agent's owner or a workspace
    owner/admin, so from a runtime that is neither it returns "You do not have
    permission to access this resource". Swallowing that as None recorded a
    denied read as an emptied env, which is the same defect as the skill
    deletion: a failed read treated as an intentional edit (CHA-1211)."""


def _fetch_agent_custom_env(agent_id: str) -> Optional[Dict[str, str]]:
    """Fetch the current custom_env for an agent via 'agent env get'.

    Returns the env dict, or None when the agent genuinely has none. Raises
    CustomEnvUnreadable when the call fails — callers must decide what an
    unreadable env means for them, rather than inheriting a silent None.
    """
    try:
        result = _multica(["agent", "env", "get", agent_id], dry_run=False)
    except Exception as e:
        raise CustomEnvUnreadable(str(e).strip()) from e
    if isinstance(result, dict):
        return result
    return None


# Placeholder stored in place of a resolved secret value. Only the KEY SET of a
# custom_env ever reaches the baseline (see _sanitize_custom_env_for_state), and
# conflict payloads are printed to stdout and filed into issues, so a resolved
# value must never enter a normalized snapshot in the first place.
_REDACTED = "<redacted>"


def _live_custom_env_for_state(
    live_agent: Dict[str, Any],
    repo_norm: Dict[str, Any],
    last: Optional[Dict[str, Any]],
) -> Tuple[Any, Optional[str]]:
    """Resolve a live agent's custom_env for change detection.

    `agent list` deliberately never returns custom_env — the values are secrets.
    It returns `has_custom_env` and `custom_env_key_count` instead. But
    `normalize_agent` does a bare `data.get("custom_env")`, so that absence
    became None, `_decide_action` read None as "the live env was emptied", and
    the baseline oscillated: key list → null → key list on alternating nights.
    That is the +36/−12 / +12/−36 signature on every sync commit from 08-23 to
    09-02, 12 fields wide — both baseline sides of the six agents that declare a
    custom_env (CHA-1211 item 12; CHA-1092 aimed at this and missed).

    Returns (value_for_the_snapshot, optional_warning). In order:

    1. `custom_env` present in the response — a real read, use it.
    2. `has_custom_env` false — the response positively says there is none.
    3. Present, and the baseline and the repo AGREE on a key set whose size
       matches the live count — reuse it. Free, and no audited call.
    4. Present, but the two sides disagree or cannot account for the count —
       something really did change, so read it authoritatively with
       `agent env get`.
    5. Even that is unreadable — carry the baseline forward and warn. An absent
       field is not an empty field, so it contributes nothing to the diff.

    Known residual: a workspace-side key RENAME that keeps the count the same,
    while baseline and repo still agree with each other, is invisible here — the
    response carries no signal that anything moved, so rung 3 reuses a set that
    is no longer live. Nothing short of an unconditional `agent env get` every
    run can see it, which is the cost rung 3 exists to avoid. Closing it needs a
    re-read trigger the response CAN supply (the agent's `updated_at` recorded in
    the baseline); that is a state-format change and is not done here. The error
    is safe in direction — it reads as `unchanged`, so neither side is written.
    """
    if "custom_env" in live_agent:
        # A real read — but keep only the key names. Change detection needs
        # nothing else, and a resolved value that never enters the snapshot
        # cannot escape through a payload that forgot to sanitize (CHA-1211 G2).
        #
        # Every shape has to be projected, not just the dict: `_norm_agent_field`
        # already handles custom_env arriving as a JSON STRING, so that shape is
        # anticipated elsewhere in this file — and returned unparsed it carried
        # the resolved value verbatim, which made this guard true of one shape
        # while its comment claimed both (CHA-1211 H3).
        env = live_agent["custom_env"]
        if env is None:
            return None, None
        if isinstance(env, str):
            try:
                env = json.loads(env)
            except (json.JSONDecodeError, TypeError):
                return None, (
                    "live custom_env came back as a string that is not JSON — "
                    "dropping it rather than recording an unparseable value, and "
                    "carrying nothing forward from it"
                )
        if isinstance(env, dict):
            return {k: _REDACTED for k in env}, None
        # Some other shape entirely: a changed contract again. Do not pass it on —
        # an unknown shape is exactly what must not be trusted or repeated.
        return None, (
            f"live custom_env came back as {type(env).__name__}, which this run "
            f"cannot read as a key map — dropping it rather than guessing"
        )

    if not live_agent.get("has_custom_env"):
        return None, None

    count = live_agent.get("custom_env_key_count")
    # The baseline already stores the sanitized projection (a sorted key list);
    # the repo side is still a normalized JSON blob and needs projecting.
    stored = (last or {}).get("multica_state") or {}
    baseline_keys = stored.get("custom_env")
    if not isinstance(baseline_keys, list):
        baseline_keys = _sanitize_custom_env_for_state(baseline_keys)
    repo_keys = _sanitize_custom_env_for_state(repo_norm.get("custom_env"))

    # Trust the count ONLY when the baseline and the repo agree on the key set.
    # The count is a weak identity claim — every agent with an env has exactly
    # one key, so "count == 1" matches any single-key set, live or not. When the
    # two sides we CAN read agree, reusing their set is safe and free. When they
    # disagree, one of them is wrong about the live agent and the count cannot
    # say which, so pay for the authoritative read (CHA-1211 item 17).
    if (
        isinstance(baseline_keys, list)
        and baseline_keys == repo_keys
        and len(baseline_keys) == count
    ):
        return {k: _REDACTED for k in baseline_keys}, None

    agent_id = live_agent.get("id", "")
    try:
        env = _fetch_agent_custom_env(agent_id)
    except CustomEnvUnreadable as e:
        note = (
            f"live custom_env holds {count} key(s) this run cannot name, and "
            f"`agent env get` is not readable from here ({e}) — carrying the "
            f"baseline forward rather than recording an emptied env"
        )
        return ({k: _REDACTED for k in baseline_keys} if baseline_keys else None), note
    if env is None:
        return None, None
    return {k: _REDACTED for k in env}, None


def _carry_forward_unread_fields(
    multica_norm: Dict[str, Any],
    live_agent: Dict[str, Any],
    last: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Stop a field the live read never carried from reading as "cleared".

    `normalize_agent` projects every COMPARABLE_FIELD with a bare `data.get(f)`,
    so a field the response simply omits is indistinguishable from one the
    operator emptied. custom_env is the case that bit us, but the shape is
    general: a single contract change on this endpoint would land on all 46
    agent definitions the same way the skill one landed on 22 skills
    (CHA-1211 F4). Today every other COMPARABLE_FIELD is present in
    `agent list`, so this is a no-op — which is the point of adding it now.

    Where the baseline knows what the field was, carry that value forward; the
    field then contributes nothing to the diff instead of a false change.

    It says so on stderr when it fires. A no-op today means the only event that
    can ever trigger it is the next contract change — precisely the event that
    would otherwise pass unnoticed, which is how this incident started
    (CHA-1211 item 18). Carrying a field forward silently would make the guard
    the thing that hides its own trigger.
    """
    if last is None:
        return multica_norm
    baseline = last.get("multica_state") or {}
    carried: List[str] = []
    for field in COMPARABLE_FIELDS:
        # custom_env is handled by _live_custom_env_for_state, which can see
        # more than the baseline. Both it and mcp_config are stored in the
        # baseline as a *projection* rather than the normalized value, so
        # copying one back into a normalized snapshot would not round-trip.
        if field in ("custom_env", "mcp_config"):
            continue
        if field not in live_agent and field in baseline:
            multica_norm[field] = baseline[field]
            carried.append(field)
    if carried:
        print(
            f"    ⚠ live read omitted {', '.join(carried)} — carrying the baseline "
            f"forward rather than reading the absence as a cleared field. This is a "
            f"CHANGED READ CONTRACT: check the CLI/API before trusting this run.",
            file=sys.stderr,
        )
    return multica_norm


def _get_mcp_server_keys(mcp_config: Any) -> Optional[set]:
    """Extract the set of MCP server names from an mcp_config value.

    The mcp_config may be a dict, a JSON string (from normalization), or None.
    Returns None if there's no meaningful MCP config (e.g. both null/missing).
    """
    if mcp_config is None:
        return None
    if isinstance(mcp_config, str):
        try:
            mcp_config = json.loads(mcp_config)
        except (json.JSONDecodeError, TypeError):
            return None
    if isinstance(mcp_config, dict):
        servers = mcp_config.get("mcpServers")
        if isinstance(servers, dict):
            return set(servers.keys())
        return set()
    return None


def _sanitize_mcp_for_state(mcp_norm: Any) -> Any:
    """Replace mcp_config values with just the server key names.

    Avoids committing resolved secret tokens to the sync state file.
    The server key set is enough for change detection (server structure).
    """
    servers = _get_mcp_server_keys(mcp_norm)
    if servers is not None:
        return json.dumps({"mcpServers": sorted(servers)}, sort_keys=True)
    return None


def _sanitize_custom_env_for_state(custom_env_norm: Any) -> Any:
    """Replace custom_env values with just the sorted key names.

    Avoids committing resolved secret values to the sync state file.
    The key set is enough for change detection (env var structure).
    """
    if custom_env_norm is None:
        return None
    try:
        env = json.loads(custom_env_norm) if isinstance(custom_env_norm, str) else custom_env_norm
        if isinstance(env, dict):
            return sorted(env.keys())
    except Exception:
        pass
    return None


def _sanitize_agent_for_state(norm: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Project a normalized agent/skill state onto the change-detection form
    that `.sync-state.json` baselines store.

    Secret-bearing fields are reduced to their structure exactly as the baseline
    write paths do — mcp_config → the sorted MCP server-name set, custom_env →
    the sorted key list — so a raw repo read (with `#…#` placeholders) and a
    live Multica read (with resolved secrets) can be diffed against the stored
    baseline like-for-like. Without this, `_decide_action` compared the full
    mcp_config block against the sanitized baseline and `repo_changed` was
    structurally always-true for any MCP-bearing agent (CHA-1092).

    Fields absent from the source are left absent, keeping the projection
    key-for-key compatible with stored baselines for both agents (all
    COMPARABLE_FIELDS) and skills ({name, description, body, files}).
    """
    if norm is None:
        return None
    out = dict(norm)
    if "mcp_config" in out:
        out["mcp_config"] = _sanitize_mcp_for_state(out["mcp_config"])
    if "custom_env" in out:
        out["custom_env"] = _sanitize_custom_env_for_state(out["custom_env"])
    return out


def _try_reconcile_agent_conflict(
    repo_norm: Dict[str, Any],
    multica_norm: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Try to reconcile a both-sides-changed agent conflict.

    For MCP configs, compares the server *structure* (which MCP servers exist)
    rather than resolved vs placeholder token values.

    For custom_env, compares the key set only (not resolved vs placeholder values).

    For skills, merges both side's lists (union).

    Returns the merged normalized state if reconcilable, or None if the
    conflict is genuine (non-MCP/non-skills/custom_env fields diverged, or MCP
    server sets differ).
    """
    # If any non-MCP/non-skills/non-custom_env fields differ, it's a genuine conflict
    structural_fields = set(COMPARABLE_FIELDS) - {"skills", "mcp_config", "custom_env"}
    for field in structural_fields:
        if repo_norm.get(field) != multica_norm.get(field):
            return None

    # custom_env: compare key sets only (ignore placeholder vs resolved values).
    # If one side has keys and the other doesn't, allow the side with keys to win
    # (repo adds custom_env; Multica may have none because it was never set).
    repo_env_keys = _sanitize_custom_env_for_state(repo_norm.get("custom_env"))
    multica_env_keys = _sanitize_custom_env_for_state(multica_norm.get("custom_env"))
    if repo_env_keys is not None and multica_env_keys is not None:
        if repo_env_keys != multica_env_keys:
            return None
    elif repo_env_keys != multica_env_keys:
        pass

    # MCP config: compare server keys only (ignore placeholder vs resolved)
    repo_servers = _get_mcp_server_keys(repo_norm.get("mcp_config"))
    multica_servers = _get_mcp_server_keys(multica_norm.get("mcp_config"))

    if repo_servers is not None and multica_servers is not None:
        if repo_servers != multica_servers:
            return None
    elif repo_servers != multica_servers:
        # One side has servers, the other doesn't — allow repo to win
        # (repo adds MCP servers; Multica may have none due to redaction)
        pass

    # Merge: start from repo norm, override skills (union), keep repo custom_env
    merged = dict(repo_norm)
    merged["skills"] = sorted(
        set(repo_norm.get("skills") or []) |
        set(multica_norm.get("skills") or [])
    )
    return merged


def _apply_reconciled_to_repo_data(
    repo_data: Dict[str, Any],
    reconciled: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply the reconciled state to repo_data for pushing to Multica.

    Merges skills, keeps other fields and MCP config from repo_data.
    """
    result = dict(repo_data)
    result["skills"] = reconciled.get("skills", [])
    return result


def _write_reconciled_agent_json(
    agent_json_path: pathlib.Path,
    reconciled: Dict[str, Any],
    repo_data: Dict[str, Any],
    dry_run: bool,
) -> None:
    """Write the reconciled state to the repo agent.json.

    Merges skills from the reconciled state, keeps MCP config from the
    existing repo file (preserving placeholder tokens).
    """
    existing: Optional[Dict[str, Any]] = None
    if agent_json_path.is_file():
        with open(agent_json_path) as f:
            existing = json.load(f)

    new_data = dict(existing or repo_data)
    new_data["skills"] = reconciled.get("skills", [])

    if dry_run:
        print(f"      [DRY-RUN] would write {agent_json_path}", file=sys.stderr)
        return
    with open(agent_json_path, "w") as f:
        json.dump(new_data, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------------------
# Direction detection (shared by agents and skills)
# ---------------------------------------------------------------------------

def _decide_action(
    repo_norm: Any,
    multica_norm: Any,
    last: Optional[Dict[str, Any]],
) -> str:
    # Treat legacy state entries (no repo_state/multica_state) as never-synced
    if last is not None and ("repo_state" not in last or "multica_state" not in last):
        last = None

    if last is None:
        if multica_norm is None:
            return "push_to_multica"
        if _sanitize_agent_for_state(repo_norm) == _sanitize_agent_for_state(multica_norm):
            return "unchanged"
        return "push_to_multica"

    last_repo = last.get("repo_state")
    last_multica = last.get("multica_state")

    # Baselines store secret-bearing fields sanitized (mcp_config → server-name
    # set, custom_env → key list); the live reads carry full blocks (placeholders
    # in the repo, resolved secrets in Multica). Diff like-for-like or any
    # MCP-bearing agent is structurally always-changed (CHA-1092).
    repo_snapshot = _sanitize_agent_for_state(repo_norm)
    multica_snapshot = _sanitize_agent_for_state(multica_norm)

    repo_changed = repo_snapshot != last_repo
    multica_changed = multica_snapshot != last_multica

    if not repo_changed and not multica_changed:
        return "unchanged"
    if repo_changed and not multica_changed:
        return "push_to_multica"
    if not repo_changed and multica_changed:
        if multica_norm is None:
            return "unchanged"
        return "pull_to_repo"
    if repo_snapshot == multica_snapshot:
        return "unchanged"
    return "conflict"


# ---------------------------------------------------------------------------
# Agent workspace sync
# ---------------------------------------------------------------------------

def _agent_name_to_slug(name: str) -> str:
    """Convert an agent name to a kebab-case directory slug."""
    return name.lower().replace(" ", "-").replace("/", "-").replace("_", "-")


def _squad_name_to_slug(name: str) -> str:
    """Convert a squad name to a kebab-case directory slug."""
    slug = name.lower().replace(" ", "-").replace("/", "-").replace("_", "-")
    # Strip common prefixes/suffixes for directory names
    for suffix in ("-squad", "-team", "-group"):
        if slug.endswith(suffix):
            slug = slug[: -len(suffix)]
    return slug


def _fetch_agent_squad_map(
    dry_run: bool,
) -> Dict[str, str]:
    """Build a mapping agent_name → squad_name (lowercase directory slug).

    Queries all squads and their members, then maps each agent member
    to its squad. Agents not in any squad map to '_shared'.
    """
    agent_squad: Dict[str, str] = {}
    try:
        squads = _multica(["squad", "list"], dry_run=False)
        for squad in squads:
            squad_id = squad["id"]
            squad_name = squad.get("name", "")
            squad_slug = _squad_name_to_slug(squad_name) if squad_name else ""
            if not squad_slug:
                continue
            try:
                members = _multica(["squad", "member", "list", squad_id], dry_run=False)
                for member in members:
                    if member.get("member_type") == "agent":
                        agent_id = member.get("member_id", "")
                        if agent_id:
                            agent_squad[agent_id] = squad_slug
            except RuntimeError:
                # Squad may have been deleted between list and member query
                pass
    except RuntimeError:
        # Fallback: no squads → everything in _shared
        pass
    return agent_squad


def sync_agents_workspace(
    workspace_dir: pathlib.Path,
    schema: Dict[str, Any],
    live_agents: Dict[str, Dict[str, Any]],
    skill_map: Dict[str, str],
    state: Dict[str, Any],
    id_map: Dict[str, str],
    create_guard: CreateGuard,
    dry_run: bool,
    force: bool = False,
) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    workspace_name = workspace_dir.name
    print(f"\n── Agents: {workspace_name} ──", file=sys.stderr)

    # Fresh memo per run: vault values are stable within a run but may have
    # changed since a previous one, and clearing keeps tests independent.
    _bw_cache_clear()

    counts: Dict[str, int] = defaultdict(int)
    conflicts: List[Dict[str, Any]] = []
    state_agents = state.setdefault("agents", {})
    live_by_id = {a["id"]: a for a in live_agents.values()}

    known_agent_names: set = set()
    # Live agent UUIDs already consumed by a repo file (matched by id-anchor or by
    # name). The discovery phase skips these so a renamed agent — whose live name
    # still differs from the repo until it's updated — isn't re-processed as a
    # phantom orphan under its stale name.
    handled_ids: set = set()

    for squad_dir in sorted(workspace_dir.iterdir()):
        if not squad_dir.is_dir() or squad_dir.name.startswith("."):
            continue
        for agent_dir in sorted(squad_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            agent_json_path = agent_dir / "agent.json"
            if not agent_json_path.is_file():
                continue

            rel_path = agent_json_path.relative_to(REPO_ROOT)
            print(f"  {rel_path}", file=sys.stderr)

            try:
                repo_data = validate_agent_json(agent_json_path, schema)
            except Exception as e:
                print(f"    ✗ SCHEMA VALIDATION FAILED: {e}", file=sys.stderr)
                counts["errors"] += 1
                continue

            agent_name = repo_data.get("name", "")
            if not agent_name:
                print(f"    ✗ missing required 'name' field", file=sys.stderr)
                counts["errors"] += 1
                continue

            known_agent_names.add(agent_name)
            key = agent_key(agent_dir, workspace_dir)

            # --- Identity resolution (Option A: anchor on the per-workspace id map) ---
            # 1. Stored UUID that still resolves to a live agent → the anchor.
            # 2. Otherwise fall back to a name match and ADOPT its UUID into the
            #    id map (one-time re-anchor / self-heal of a churned identity).
            # 3. Otherwise the agent is genuinely absent → a create (guarded).
            live_agent: Optional[Dict[str, Any]] = None
            stored_id = id_map.get(key)
            if stored_id and stored_id in live_by_id:
                live_agent = live_by_id[stored_id]
            else:
                by_name = live_agents.get(agent_name)
                if by_name is not None:
                    live_agent = by_name
                    if id_map.get(key) != by_name["id"]:
                        print(
                            f"    ⚑ anchoring id map: {key} → {by_name['id']}"
                            + (" (re-anchored)" if stored_id else ""),
                            file=sys.stderr,
                        )
                        id_map[key] = by_name["id"]

            if live_agent is not None:
                handled_ids.add(live_agent["id"])

            state_key = f"{workspace_name}~{agent_name}"
            last = state_agents.get(state_key)
            repo_norm = normalize_agent(repo_data)
            multica_norm = None
            if live_agent:
                multica_norm = normalize_agent(live_agent)
                # A field the live read never carried is not a cleared field
                # (CHA-1211 item 12 / F4).
                multica_norm = _carry_forward_unread_fields(multica_norm, live_agent, last)
                env_value, env_note = _live_custom_env_for_state(live_agent, repo_norm, last)
                multica_norm["custom_env"] = _norm_agent_field("custom_env", env_value)
                if env_note:
                    print(f"    ⚠ {env_note}", file=sys.stderr)

            action = _decide_action(repo_norm, multica_norm, last)
            agent_id: Optional[str] = live_agent["id"] if live_agent else None

            # --force: re-resolve and re-push mcp_config for every agent that has
            # a block and a live counterpart, bypassing change detection. The
            # diff compares against a redacted live read, so an agent already
            # holding placeholders (or whose secret was wiped) reads as
            # "unchanged" and is skipped forever; --force is the reliable
            # full-restore path. Fail-closed still applies inside the push, so a
            # forced run can never push an unresolved placeholder either.
            if (
                force
                and live_agent is not None
                and repo_data.get("mcp_config") is not None
                and action != "push_to_multica"
            ):
                print(f"    ⟳ --force: re-pushing mcp_config (bypassing diff, was '{action}')", file=sys.stderr)
                action = "push_to_multica"

            if action == "unchanged":
                print(f"    ✓ unchanged", file=sys.stderr)
                counts["unchanged"] += 1
                # multica_norm is None when the live list transiently omitted an
                # anchored agent (AC5): we deliberately don't re-mint, so preserve
                # the last-known multica_state rather than clobbering it with the miss.
                if multica_norm is not None:
                    multica_state = _sanitize_agent_for_state(multica_norm)
                else:
                    multica_state = last.get("multica_state") if last else None
                state_agents[state_key] = {
                    "repo_file": str(rel_path),
                    "repo_state": _sanitize_agent_for_state(repo_norm),
                    "multica_state": multica_state,
                }

            elif action == "push_to_multica":
                mcp_file = custom_env_file = None
                try:
                    mcp_file = _write_mcp_config_tempfile(repo_data)
                    custom_env_file = _write_custom_env_tempfile(repo_data)
                except (BitwardenAuthError, OpAuthError):
                    # A dead/stale vault session affects every agent — aborting
                    # loudly is correct (skipping each one hides the real cause).
                    # Clean the temp file and let it propagate to the top-level
                    # abort.
                    if mcp_file:
                        os.unlink(mcp_file)
                    raise
                except SecretResolutionError as e:
                    # Fail closed: never push an unresolved #…# placeholder over a
                    # live agent's config (the CHA-790 key-wipe). Skip + report,
                    # and leave the sync state untouched so the agent is retried
                    # once secrets resolve again. skipped>0 makes the run exit
                    # non-zero.
                    if mcp_file:
                        os.unlink(mcp_file)
                    print(f"    ✗ SKIPPING push (fail-closed): {e}", file=sys.stderr)
                    print(f"      refusing to overwrite a live config with an unresolved placeholder", file=sys.stderr)
                    counts["skipped"] += 1
                    continue
                try:
                    mcp_args = ["--mcp-config-file", mcp_file] if mcp_file else []
                    custom_env_args = ["--custom-env-file", custom_env_file] if custom_env_file else []
                    if live_agent is None:
                        # No identity anchor and no name match → genuine create.
                        # Gated by CreateGuard so a name-lookup miss can never
                        # silently mint a fresh UUID (AC5 / mass-mint guard).
                        try:
                            create_guard.authorize(f"{workspace_name}/{key}")
                        except CreateBudgetExceeded:
                            raise
                        except PermissionError as e:
                            print(f"    ✗ NOT CREATING: {e}", file=sys.stderr)
                            counts["errors"] += 1
                            continue
                        print(f"    → creating in Multica", file=sys.stderr)
                        try:
                            if not dry_run:
                                result = _multica(["agent", "create"] + build_create_args(repo_data) + mcp_args + custom_env_args)
                                agent_id = result["id"]
                                id_map[key] = agent_id
                                print(f"    ✓ created (id={agent_id}) — anchored {key}", file=sys.stderr)
                            else:
                                _multica(["agent", "create"] + build_create_args(repo_data) + mcp_args + custom_env_args, dry_run=True)
                            create_guard.record()
                            counts["created"] += 1
                        except Exception as e:
                            print(f"    ✗ CREATE FAILED: {e}", file=sys.stderr)
                            counts["errors"] += 1
                            continue
                    else:
                        print(f"    → updating Multica (repo changed, id={agent_id})", file=sys.stderr)
                        try:
                            _multica(["agent", "update"] + build_update_args(agent_id, repo_data) + mcp_args, dry_run=dry_run)
                            counts["updated"] += 1
                        except Exception as e:
                            print(f"    ✗ UPDATE FAILED: {e}", file=sys.stderr)
                            counts["errors"] += 1
                            continue
                    # Set custom_env separately via env set (not supported on agent update)
                    if custom_env_file and live_agent is not None:
                        try:
                            _multica(["agent", "env", "set", agent_id, "--custom-env-file", custom_env_file], dry_run=dry_run)
                        except Exception as e:
                            print(f"    ✗ CUSTOM_ENV SET FAILED: {e}", file=sys.stderr)
                            counts["errors"] += 1
                            continue
                finally:
                    if mcp_file:
                        os.unlink(mcp_file)
                    if custom_env_file:
                        os.unlink(custom_env_file)

                desired_skills = repo_norm.get("skills") or []
                if desired_skills and agent_id:
                    try:
                        ensure_agent_skills(agent_id, desired_skills, skill_map, dry_run)
                    except Exception as e:
                        print(f"    ✗ SKILLS FAILED: {e}", file=sys.stderr)
                        counts["errors"] += 1

                state_agents[state_key] = {
                    "repo_file": str(rel_path),
                    "repo_state": _sanitize_agent_for_state(repo_norm),
                    "multica_state": _sanitize_agent_for_state(repo_norm),
                }

            elif action == "pull_to_repo":
                print(f"    → writing repo (Multica changed)", file=sys.stderr)
                # Do NOT fetch live custom_env: those are resolved secrets, and
                # the repo must keep its #Item:Field# placeholders (CHA-85).
                # write_agent_json preserves the existing repo custom_env/mcp_config.
                try:
                    written = write_agent_json(agent_json_path, live_agent, dry_run)
                    counts["repo_updated"] += 1
                except Exception as e:
                    print(f"    ✗ REPO WRITE FAILED: {e}", file=sys.stderr)
                    counts["errors"] += 1
                    continue
                # repo_state is the file as WRITTEN, not the live read it came
                # from. Those differ by exactly custom_env/mcp_config, which the
                # write preserves from the repo — so baselining multica_norm here
                # claimed a file that was never written, the next run read the
                # repo as "changed back", and the entry alternated forever. That
                # is the seventh agent's flip-flop, one line wide (CHA-1211 G1).
                state_agents[state_key] = {
                    "repo_file": str(rel_path),
                    "repo_state": _sanitize_agent_for_state(normalize_agent(written)),
                    "multica_state": _sanitize_agent_for_state(multica_norm),
                }

            elif action == "conflict":
                reconciled = _try_reconcile_agent_conflict(repo_norm, multica_norm)
                if reconciled is not None:
                    print(f"    → reconciling: merging both sides' changes", file=sys.stderr)
                    # 1. Push merged state to Multica
                    merged_repo_data = _apply_reconciled_to_repo_data(repo_data, reconciled)
                    mcp_file = custom_env_file = None
                    try:
                        mcp_file = _write_mcp_config_tempfile(merged_repo_data)
                        custom_env_file = _write_custom_env_tempfile(merged_repo_data)
                    except (BitwardenAuthError, OpAuthError):
                        # Dead/stale vault session — abort loudly (see the push path).
                        if mcp_file:
                            os.unlink(mcp_file)
                        raise
                    except SecretResolutionError as e:
                        # Fail closed: same guard as the push path — never write an
                        # unresolved placeholder over a live agent while reconciling.
                        if mcp_file:
                            os.unlink(mcp_file)
                        print(f"    ✗ SKIPPING reconcile push (fail-closed): {e}", file=sys.stderr)
                        counts["skipped"] += 1
                        continue
                    try:
                        mcp_args = ["--mcp-config-file", mcp_file] if mcp_file else []
                        _multica(
                            ["agent", "update"] + build_update_args(agent_id, merged_repo_data) + mcp_args,
                            dry_run=dry_run,
                        )
                        counts["updated"] += 1

                        # Set custom_env after update (env set, not supported on agent update)
                        if custom_env_file:
                            _multica(["agent", "env", "set", agent_id, "--custom-env-file", custom_env_file], dry_run=dry_run)
                    except Exception as e:
                        print(f"    ✗ MULTICA UPDATE FAILED: {e}", file=sys.stderr)
                        counts["errors"] += 1
                        continue
                    finally:
                        if mcp_file:
                            os.unlink(mcp_file)
                        if custom_env_file:
                            os.unlink(custom_env_file)

                    desired_skills = reconciled.get("skills") or []
                    if desired_skills and agent_id:
                        try:
                            ensure_agent_skills(agent_id, desired_skills, skill_map, dry_run)
                        except Exception as e:
                            print(f"    ✗ SKILLS FAILED: {e}", file=sys.stderr)
                            counts["errors"] += 1

                    # 2. Write merged state to repo
                    try:
                        _write_reconciled_agent_json(agent_json_path, reconciled, repo_data, dry_run)
                        counts["repo_updated"] += 1
                    except Exception as e:
                        print(f"    ✗ REPO WRITE FAILED: {e}", file=sys.stderr)
                        counts["errors"] += 1
                        continue

                    state_agents[state_key] = {
                        "repo_file": str(rel_path),
                        "repo_state": _sanitize_agent_for_state(reconciled),
                        "multica_state": _sanitize_agent_for_state(reconciled),
                    }
                else:
                    print(f"    ✗ CONFLICT: both sides changed irreconcilably", file=sys.stderr)
                    # Sanitized, like every baseline write path: this payload is
                    # printed to stdout and step 5 of both sync autopilots parses
                    # it into an ISSUE BODY. Raw, a live custom_env/mcp_config
                    # value would be published the moment the API starts
                    # returning one — and "the API does not return that field"
                    # is the assumption this whole issue is about (CHA-1211 G2).
                    conflicts.append({
                        "type": "agent",
                        "name": agent_name,
                        "repo_file": str(rel_path),
                        "repo_state": _sanitize_agent_for_state(repo_norm),
                        "multica_state": _sanitize_agent_for_state(multica_norm),
                        "last_synced_repo": last.get("repo_state") if last else None,
                        "last_synced_multica": last.get("multica_state") if last else None,
                    })
                    counts["conflicts"] += 1

    # --- Discovery phase: Multica agents not in the repo ---
    agent_squad_map: Optional[Dict[str, str]] = None

    for live_name, live_agent in sorted(live_agents.items()):
        if live_name in known_agent_names:
            continue
        if live_agent.get("id") in handled_ids:
            # Already upserted via a repo file (e.g. matched by id after a rename).
            continue

        state_key = f"{workspace_name}~{live_name}"
        last = state_agents.get(state_key)

        # Determine action: if never synced → pull to repo;
        # if last state exists, use normal direction detection.
        if last is None:
            action = "pull_to_repo"
        else:
            # Build a dummy repo_norm (doesn't exist in repo files)
            # to detect direction via _decide_action.
            repo_norm = normalize_agent({})
            multica_norm = None
            if live_agent:
                multica_norm = normalize_agent(live_agent)
                multica_norm = _carry_forward_unread_fields(multica_norm, live_agent, last)
                env_value, env_note = _live_custom_env_for_state(live_agent, repo_norm, last)
                multica_norm["custom_env"] = _norm_agent_field("custom_env", env_value)
                if env_note:
                    print(f"    ⚠ {live_name}: {env_note}", file=sys.stderr)
            action = _decide_action(repo_norm, multica_norm, last)

        agent_id = live_agent.get("id", "")

        if action == "unchanged":
            counts["unchanged"] += 1
            continue

        elif action == "push_to_multica":
            # Agent exists in Multica but repo "wants" to push —
            # this shouldn't happen for a new agent, but handle safely:
            counts["unchanged"] += 1
            continue

        elif action == "pull_to_repo":
            # Build squad mapping lazily on first need
            if agent_squad_map is None:
                agent_squad_map = _fetch_agent_squad_map(dry_run)

            squad_slug = agent_squad_map.get(agent_id, "_shared")
            agent_slug = _agent_name_to_slug(live_name)
            squad_dir = workspace_dir / squad_slug
            agent_dir = squad_dir / agent_slug
            agent_json_path = agent_dir / "agent.json"
            rel_path = agent_json_path.relative_to(REPO_ROOT)

            if agent_json_path.exists():
                print(f"  {rel_path}")
                print(f"    ✗ path collision — agent '{live_name}' already has a file", file=sys.stderr)
                counts["errors"] += 1
                continue

            print(f"  {rel_path}")
            print(f"    → writing repo (new agent discovered in Multica)", file=sys.stderr)
            # A newly-discovered agent may have custom_env set live, but those are
            # resolved secrets — we must not write them to the repo (CHA-85). Warn
            # the operator which keys need #Item:Field# placeholders added by hand.
            if agent_id:
                try:
                    live_custom_env = _fetch_agent_custom_env(agent_id)
                except CustomEnvUnreadable as e:
                    # Say so rather than printing nothing: a denied read used to
                    # look identical to "this agent has no custom_env", so the
                    # operator got no warning at all (CHA-1211).
                    count = live_agent.get("custom_env_key_count")
                    live_custom_env = None
                    if live_agent.get("has_custom_env"):
                        print(
                            f"    ⚠ live custom_env present ({count} key(s), names "
                            f"unreadable from here: {e}); NOT written to repo — add "
                            f"#Item:Field# placeholder(s) to {rel_path} by hand",
                            file=sys.stderr,
                        )
                if live_custom_env:
                    keys = ", ".join(sorted(live_custom_env.keys()))
                    print(
                        f"    ⚠ live custom_env present ({keys}); NOT written to repo "
                        f"— add #Item:Field# placeholder(s) to {rel_path} by hand",
                        file=sys.stderr,
                    )
            try:
                written = write_agent_json(agent_json_path, live_agent, dry_run)
                counts["repo_updated"] += 1
            except Exception as e:
                print(f"    ✗ REPO WRITE FAILED: {e}", file=sys.stderr)
                counts["errors"] += 1
                continue

            # Anchor the freshly written agent so future runs upsert it by id.
            if agent_id:
                id_map[agent_key(agent_dir, workspace_dir)] = agent_id

            # Same rule as the pull path above: repo_state is the file as
            # written, which for a newly discovered agent has no custom_env at
            # all (CHA-1211 G1).
            state_agents[state_key] = {
                "repo_file": str(rel_path),
                "repo_state": _sanitize_agent_for_state(normalize_agent(written)),
                "multica_state": _sanitize_agent_for_state(normalize_agent(live_agent)),
            }

        elif action == "conflict":
            print(f"    ✗ CONFLICT: agent '{live_name}' — both sides changed", file=sys.stderr)
            # Sanitized (CHA-1211 G2 — see the other conflict payload), and built
            # from the `multica_norm` the decision was actually made on rather
            # than a fresh normalize_agent(): the fresh one got neither the
            # redaction nor the carry-forward, so it reported a state that
            # differed from the one that produced the verdict.
            conflicts.append({
                "type": "agent",
                "name": live_name,
                "repo_file": "(missing — agent only in Multica)",
                "repo_state": None,
                "multica_state": _sanitize_agent_for_state(multica_norm),
                "last_synced_repo": last.get("repo_state") if last else None,
                "last_synced_multica": last.get("multica_state") if last else None,
            })
            counts["conflicts"] += 1

    print(
        f"  agents {workspace_name}: created={counts['created']} updated={counts['updated']} "
        f"repo_updated={counts['repo_updated']} unchanged={counts['unchanged']} "
        f"skipped={counts['skipped']} conflicts={counts['conflicts']} errors={counts['errors']}",
        file=sys.stderr,
    )
    return counts, conflicts


# ---------------------------------------------------------------------------
# Skills: parsing, normalization, write-back
# ---------------------------------------------------------------------------

class SkillContentUnavailable(RuntimeError):
    """A skill body (or supporting-file body) is missing or empty, so the sync
    refuses to act on it — a failed or changed READ is not an intentional edit.

    Raised, never swallowed as an empty string. `multica skill get` made bodies
    opt-in behind --with-content in 2026-09; the sync kept reading
    `live.get("content", "")`, so every body came back "" and 22 company skills
    were rewritten as frontmatter-only files in eb50a85 (CHA-1211)."""


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)


def parse_skill_md(path: pathlib.Path) -> Tuple[str, str, str]:
    """Parse SKILL.md; return (name, description, body).

    Body is everything after the closing `---` line, with any single leading
    blank line stripped (SKILL.md uses a blank line as a visual separator after
    the frontmatter, but Multica stores the content without it).
    """
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"No YAML frontmatter found in {path}")

    fm_text, body = m.group(1), m.group(2)

    name = description = ""
    for line in fm_text.splitlines():
        if line.startswith("name:"):
            name = line[5:].strip()
        elif line.startswith("description:"):
            description = line[12:].strip()

    if not name:
        raise ValueError(f"Missing 'name:' in frontmatter of {path}")

    # Strip exactly one leading newline (the blank line between --- and content)
    if body.startswith("\n"):
        body = body[1:]

    return name, description, body


def write_skill_md(path: pathlib.Path, name: str, description: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Blank line between frontmatter and content matches the existing convention.
    text = f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"
    path.write_text(text, encoding="utf-8")


def _load_skill_supporting_files(skill_dir: pathlib.Path) -> Dict[str, str]:
    """Return {relative_path: content} for every file except SKILL.md."""
    files: Dict[str, str] = {}
    for p in sorted(skill_dir.rglob("*")):
        if p.is_file() and p.name != "SKILL.md":
            rel = str(p.relative_to(skill_dir))
            try:
                files[rel] = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                pass  # skip binary files
    return files


def normalize_skill_repo(skill_name: str) -> Optional[Dict[str, Any]]:
    """Load and normalize a skill from the repo."""
    skill_dir = SKILLS_DIR / skill_name
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        name, description, body = parse_skill_md(skill_md)
    except Exception as e:
        raise ValueError(f"Failed to parse {skill_md}: {e}")
    return {
        "name": name,
        "description": description,
        "body": body,
        "files": _load_skill_supporting_files(skill_dir),
    }


def normalize_skill_multica(live: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a live Multica skill for state comparison.

    Fails closed when the response carries no body: an absent `content` key
    means the read did not deliver the content, not that the workspace copy is
    empty, and defaulting it to "" is what deleted 22 skill bodies in eb50a85
    (CHA-1211). Same for a supporting file's `content`.

    An empty-but-present body is kept in the snapshot (so a repo→Multica push
    can still repair it) — it is the *write* side that refuses it, see
    `_assert_skill_content_writable`.
    """
    name = live.get("name", "")
    if "content" not in live:
        raise SkillContentUnavailable(
            f"'{name}': response carries no 'content' key "
            f"(content_size={live.get('content_size')!r}) — the body was not "
            f"served, so it cannot be compared. `multica skill get` needs "
            f"--with-content."
        )
    if "files" not in live:
        # The same contract change one level down. An absent `files` key is not
        # "this skill has no supporting files": it silently records files={} on
        # both sides of the baseline, which is the setup for exactly the
        # oscillation this issue is about (CHA-1211 F2).
        raise SkillContentUnavailable(
            f"'{name}': response carries no 'files' key — the file list was not "
            f"served, so an empty one cannot be trusted. A skill with no "
            f"supporting files returns files=[]."
        )
    files: Dict[str, str] = {}
    for f in live.get("files") or []:
        path = f.get("path", "<unknown>")
        if "content" not in f:
            raise SkillContentUnavailable(
                f"'{name}': supporting file '{path}' carries no 'content' key "
                f"(size={f.get('size')!r}) — the body was not served. "
                f"`multica skill get` needs --with-content."
            )
        files[path] = f["content"] or ""
    return {
        "name": name,
        "description": live.get("description", ""),
        "body": live.get("content") or "",
        "files": files,
    }


def _assert_skill_content_nonempty(
    skill_name: str,
    norm: Dict[str, Any],
    source: str,
    target: str,
) -> None:
    """Refuse to copy an empty body or a 0-byte supporting file over the other side.

    Emptying content is never a legitimate edit — nobody trims a skill down to
    frontmatter, in the repo or in the workspace UI — so this guards BOTH
    directions. The repo→Multica direction matters just as much: the 22 gutted
    files sat on main for hours, and the next push would have written them over
    the intact live copies, taking the last good version with them (CHA-1211).
    """
    if not (norm.get("body") or "").strip():
        raise SkillContentUnavailable(
            f"'{skill_name}': {source} body is empty — refusing to write a "
            f"frontmatter-only skill over {target}."
        )
    for rel_path, content in (norm.get("files") or {}).items():
        if content == "":
            raise SkillContentUnavailable(
                f"'{skill_name}': {source} supporting file '{rel_path}' is "
                f"0 bytes — refusing to empty it in {target}."
            )


def fetch_skill_detail(skill_id: str) -> Dict[str, Any]:
    # --with-content is REQUIRED. The CLI made bodies opt-in (2026-09): without
    # the flag the response carries content_hash/content_size and no `content`
    # key at all, which the sync read as "the workspace copy is now empty"
    # (CHA-1211). normalize_skill_multica fails closed if it is ever dropped.
    return _multica(["skill", "get", skill_id, "--with-content"], dry_run=False)


# ---------------------------------------------------------------------------
# Skills workspace sync
# ---------------------------------------------------------------------------

def sync_skills_workspace(
    workspace_dir: pathlib.Path,
    live_skills_map: Dict[str, Dict[str, Any]],
    state: Dict[str, Any],
    dry_run: bool,
) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    """Sync skills listed in <workspace>/skills.json."""
    workspace_name = workspace_dir.name
    skills_json_path = workspace_dir / "skills.json"

    if not skills_json_path.is_file():
        return defaultdict(int), []

    with open(skills_json_path) as f:
        skill_names: List[str] = json.load(f)

    print(f"\n── Skills: {workspace_name} ({len(skill_names)} skills) ──", file=sys.stderr)

    counts: Dict[str, int] = defaultdict(int)
    conflicts: List[Dict[str, Any]] = []
    state_skills = state.setdefault("skills", {}).setdefault(workspace_name, {})

    for skill_name in skill_names:
        print(f"  skills/{skill_name}/SKILL.md", file=sys.stderr)

        # Load repo state
        try:
            repo_norm = normalize_skill_repo(skill_name)
        except Exception as e:
            print(f"    ✗ REPO PARSE FAILED: {e}", file=sys.stderr)
            counts["errors"] += 1
            continue

        if repo_norm is None:
            print(f"    ✗ skills/{skill_name}/SKILL.md not found", file=sys.stderr)
            counts["errors"] += 1
            continue

        # Load Multica state
        live_skill = live_skills_map.get(skill_name)
        if live_skill:
            try:
                detail = fetch_skill_detail(live_skill["id"])
                multica_norm = normalize_skill_multica(detail)
            except SkillContentUnavailable as e:
                # Incomplete read — comparing against it would read as an edit.
                print(f"    ✗ LIVE READ INCOMPLETE (fail-closed, nothing written): {e}",
                      file=sys.stderr)
                counts["errors"] += 1
                continue
            except Exception as e:
                print(f"    ✗ MULTICA FETCH FAILED: {e}", file=sys.stderr)
                counts["errors"] += 1
                continue
        else:
            multica_norm = None

        last = state_skills.get(skill_name)
        action = _decide_action(repo_norm, multica_norm, last)

        skill_id: Optional[str] = live_skill["id"] if live_skill else None

        if action == "unchanged":
            print(f"    ✓ unchanged", file=sys.stderr)
            counts["unchanged"] += 1
            state_skills[skill_name] = {
                "repo_state": repo_norm,
                "multica_state": multica_norm,
            }

        elif action == "push_to_multica":
            try:
                _push_skill_to_multica(skill_name, repo_norm, skill_id, live_skill, counts, dry_run)
            except SkillContentUnavailable as e:
                # Leave the baseline alone as well as the workspace, so the next
                # run re-decides instead of calling the emptying "synced".
                print(f"    ✗ PUSH REFUSED (fail-closed, live copy kept): {e}",
                      file=sys.stderr)
                counts["errors"] += 1
                continue
            state_skills[skill_name] = {
                "repo_state": repo_norm,
                "multica_state": repo_norm,
            }

        elif action == "pull_to_repo":
            try:
                _pull_skill_to_repo(skill_name, multica_norm, dry_run)
            except SkillContentUnavailable as e:
                # Leave the baseline alone as well as the file: re-baselining an
                # empty body would make the next run call the deletion "synced".
                print(f"    ✗ PULL REFUSED (fail-closed, repo copy kept): {e}",
                      file=sys.stderr)
                counts["errors"] += 1
                continue
            counts["repo_updated"] += 1
            state_skills[skill_name] = {
                "repo_state": multica_norm,
                "multica_state": multica_norm,
            }

        elif action == "conflict":
            print(f"    ✗ CONFLICT: both sides changed", file=sys.stderr)
            conflicts.append({
                "type": "skill",
                "name": skill_name,
                "workspace": workspace_name,
                "repo_state": {k: v for k, v in repo_norm.items() if k != "body"},
                "multica_state": {k: v for k, v in (multica_norm or {}).items() if k != "body"},
                "last_synced_repo": {k: v for k, v in (last.get("repo_state") or {}).items() if k != "body"} if last else None,
                "last_synced_multica": {k: v for k, v in (last.get("multica_state") or {}).items() if k != "body"} if last else None,
            })
            counts["conflicts"] += 1

    print(
        f"  skills {workspace_name}: created={counts['created']} updated={counts['updated']} "
        f"repo_updated={counts['repo_updated']} unchanged={counts['unchanged']} "
        f"conflicts={counts['conflicts']} errors={counts['errors']}",
        file=sys.stderr,
    )
    return counts, conflicts


def _push_skill_to_multica(
    skill_name: str,
    repo_norm: Dict[str, Any],
    skill_id: Optional[str],
    live_skill: Optional[Dict[str, Any]],
    counts: Dict[str, int],
    dry_run: bool,
) -> None:
    # Same fail-closed rule as the pull side, in the other direction: never
    # overwrite a live skill with an emptied repo copy (CHA-1211).
    _assert_skill_content_nonempty(
        skill_name, repo_norm, source="repo", target="the live workspace copy"
    )

    body = repo_norm["body"]
    description = repo_norm["description"]
    files = repo_norm.get("files", {})

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tf:
        tf.write(body)
        body_path = tf.name

    try:
        if live_skill is None:
            print(f"    → creating in Multica", file=sys.stderr)
            try:
                if not dry_run:
                    result = _multica(
                        ["skill", "create", "--name", skill_name,
                         "--description", description,
                         "--content-file", body_path],
                        dry_run=False,
                    )
                    skill_id = result["id"]
                    print(f"    ✓ created (id={skill_id})", file=sys.stderr)
                else:
                    print(f"      [DRY-RUN] would create skill {skill_name}", file=sys.stderr)
                counts["created"] += 1
            except Exception as e:
                print(f"    ✗ CREATE FAILED: {e}", file=sys.stderr)
                counts["errors"] += 1
                return
        else:
            print(f"    → updating Multica (repo changed, id={skill_id})", file=sys.stderr)
            try:
                if not dry_run:
                    _multica(
                        ["skill", "update", skill_id,
                         "--description", description,
                         "--content-file", body_path],
                        dry_run=False,
                    )
                else:
                    print(f"      [DRY-RUN] would update skill {skill_name}", file=sys.stderr)
                counts["updated"] += 1
            except Exception as e:
                print(f"    ✗ UPDATE FAILED: {e}", file=sys.stderr)
                counts["errors"] += 1
                return
    finally:
        os.unlink(body_path)

    # Sync supporting files
    for rel_path, content in files.items():
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tmp", delete=False, encoding="utf-8") as tf:
            tf.write(content)
            file_tmp = tf.name
        try:
            if not dry_run and skill_id:
                _multica(
                    ["skill", "files", "upsert", skill_id,
                     "--path", rel_path, "--content-file", file_tmp],
                    dry_run=False,
                )
            elif dry_run:
                print(f"      [DRY-RUN] would upsert file {rel_path}", file=sys.stderr)
        except Exception as e:
            print(f"    ✗ FILE UPSERT FAILED ({rel_path}): {e}", file=sys.stderr)
            counts["errors"] += 1
        finally:
            os.unlink(file_tmp)


def _pull_skill_to_repo(
    skill_name: str,
    multica_norm: Dict[str, Any],
    dry_run: bool,
) -> None:
    skill_dir = SKILLS_DIR / skill_name
    skill_md = skill_dir / "SKILL.md"

    # Before the dry-run branch on purpose: a --dry-run must report the refusal
    # too, not print "would write" for a write that is never allowed.
    _assert_skill_content_nonempty(
        skill_name, multica_norm, source="live", target="the repo copy"
    )

    if dry_run:
        print(f"      [DRY-RUN] would write skills/{skill_name}/SKILL.md", file=sys.stderr)
        return

    write_skill_md(skill_md, multica_norm["name"], multica_norm["description"], multica_norm["body"])
    print(f"    ✓ wrote skills/{skill_name}/SKILL.md", file=sys.stderr)

    # Write back supporting files
    for rel_path, content in (multica_norm.get("files") or {}).items():
        target = skill_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"    ✓ wrote skills/{skill_name}/{rel_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bidirectional sync: multica-agents repo ↔ Multica workspace"
    )
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without changes")
    parser.add_argument("--workspace", type=str, default=None, help="Sync only this workspace directory")
    parser.add_argument(
        "--type",
        choices=["agents", "skills", "all"],
        default="all",
        help="What to sync (default: all)",
    )
    parser.add_argument(
        "--sync-state",
        type=str,
        default=str(DEFAULT_STATE_PATH),
        help=f"Path to the sync-state snapshot file (default: {DEFAULT_STATE_PATH})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-resolve and re-push mcp_config for every agent that has a block, "
             "bypassing change detection. The diff compares against a redacted "
             "live read, so an agent already holding placeholders reads as "
             "'unchanged' and is never re-pushed; --force is the reliable "
             "full-restore path. Fail-closed still applies (never pushes an "
             "unresolved placeholder).",
    )
    parser.add_argument(
        "--allow-create",
        action="store_true",
        help="Permit creating new agents. Without this, a repo agent with no "
             "live identity anchor is reported as an error instead of being "
             "minted (prevents silent re-creation on a name-lookup miss).",
    )
    parser.add_argument(
        "--max-creates",
        type=int,
        default=DEFAULT_MAX_CREATES,
        help=f"Abort the run if creates exceed this threshold, even with "
             f"--allow-create (mass-mint safety net; default {DEFAULT_MAX_CREATES}). "
             f"Raise it for a deliberate bulk bootstrap.",
    )
    args = parser.parse_args()

    global _workspace_id

    state_path = pathlib.Path(args.sync_state)
    sync_agents = args.type in ("agents", "all")
    sync_skills = args.type in ("skills", "all")

    print(f"==> Loading schema", file=sys.stderr)
    schema = load_schema() if sync_agents else {}

    print(f"==> Loading sync state from {state_path}", file=sys.stderr)
    state = load_sync_state(state_path)

    if args.workspace:
        ws_dir = REPO_ROOT / args.workspace
        if not ws_dir.is_dir():
            print(f"ERROR: workspace directory not found: {ws_dir}", file=sys.stderr)
            sys.exit(1)
        workspaces = [ws_dir]
    else:
        workspaces = get_workspace_dirs()

    if not workspaces:
        print("No workspace directories found.", file=sys.stderr)
        sys.exit(0)

    create_guard = CreateGuard(args.allow_create, args.max_creates)
    totals: Dict[str, int] = defaultdict(int)
    all_conflicts: List[Dict[str, Any]] = []
    aborted: Optional[str] = None

    try:
        for ws in workspaces:
            # Resolve and pin this workspace's UUID for the duration of its sync,
            # so every list/create/update CLI call is scoped to the same
            # workspace — never relying on the host default or the invocation
            # mode for correctness.
            ws_id = WORKSPACE_IDS.get(ws.name)
            _workspace_id = ws_id

            if sync_agents:
                if ws_id is None:
                    print(
                        f"\n── Agents: {ws.name} ──\n"
                        f"  ✗ unknown workspace '{ws.name}' (not in WORKSPACE_IDS) — "
                        f"refusing to sync agents (cannot scope safely). Known: {list(WORKSPACE_IDS)}",
                        file=sys.stderr,
                    )
                    totals["errors"] += 1
                else:
                    print(f"\n==> Workspace: {ws.name} ({ws_id})", file=sys.stderr)
                    print(f"==> Fetching live agents (scoped to {ws.name})", file=sys.stderr)
                    live_agents = fetch_live_agents(args.dry_run)
                    skill_map = fetch_live_agent_skills(args.dry_run)
                    id_map = load_agent_ids(ws)

                    counts, conflicts = sync_agents_workspace(
                        ws, schema, live_agents, skill_map, state, id_map,
                        create_guard, args.dry_run, args.force,
                    )
                    save_agent_ids(ws, id_map, args.dry_run)
                    for k, v in counts.items():
                        totals[k] += v
                    all_conflicts.extend(conflicts)

            if sync_skills:
                live_skills_detail = {
                    s["name"]: s for s in _multica(["skill", "list"], dry_run=False)
                }
                counts, conflicts = sync_skills_workspace(
                    ws, live_skills_detail, state, args.dry_run
                )
                for k, v in counts.items():
                    totals[k] += v
                all_conflicts.extend(conflicts)
    except CreateBudgetExceeded as e:
        aborted = str(e)
        print(f"\n✗ ABORTED: {e}", file=sys.stderr)
    except BitwardenAuthError as e:
        # A stale/locked bw session fails every item identically. Abort loudly
        # with the real cause instead of skipping every agent as "not found".
        aborted = f"Bitwarden auth/session failure — {e}"
        print(f"\n✗ ABORTED (Bitwarden session): {e}", file=sys.stderr)
        print(
            "    The session went stale or locked mid-run. sync.sh now isolates "
            "the session in a private data-dir; if you still hit this, re-run and "
            "check the bw unlock/liveness output above.",
            file=sys.stderr,
        )
    except OpAuthError as e:
        # A missing/unusable 1Password service-account token fails every op://
        # reference identically. Abort loudly with the real cause.
        aborted = f"1Password auth failure — {e}"
        print(f"\n✗ ABORTED (1Password): {e}", file=sys.stderr)
        print(
            "    The service-account token at ~/.config/op/service-account-token "
            "is missing or unusable, so op:// references cannot be resolved. "
            "Check the token file and `op read` connectivity, then re-run.",
            file=sys.stderr,
        )

    mode = "DRY-RUN" if args.dry_run else "SYNC"
    print(f"\n==> {mode} COMPLETE", file=sys.stderr)
    print(
        f"    total: created={totals['created']} updated={totals['updated']} "
        f"repo_updated={totals['repo_updated']} "
        f"unchanged={totals['unchanged']} skipped={totals['skipped']} "
        f"conflicts={totals['conflicts']} errors={totals['errors']}",
        file=sys.stderr,
    )
    if totals["skipped"] > 0:
        print(
            f"==> {totals['skipped']} agent(s) SKIPPED (fail-closed): an mcp_config/"
            f"custom_env secret could not be resolved, so the config was NOT pushed "
            f"(no live key overwritten with a placeholder). Fix the Bitwarden unlock/"
            f"item and re-run — with --force to re-push once secrets resolve.",
            file=sys.stderr,
        )

    if aborted:
        print(
            "==> Run aborted before completion — sync state NOT saved. "
            "Fix the cause and re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.dry_run:
        save_sync_state(state_path, state)
        print(f"==> State saved to {state_path}", file=sys.stderr)
        if totals["repo_updated"] > 0:
            print(
                f"==> {totals['repo_updated']} file(s) updated — commit and push to persist.",
                file=sys.stderr,
            )

    if all_conflicts:
        print(f"\n==> CONFLICTS ({len(all_conflicts)} — manual resolution needed):", file=sys.stderr)
        for c in all_conflicts:
            label = f"{c.get('type', 'agent')}: {c['name']}"
            if "workspace" in c:
                label += f" ({c['workspace']})"
            print(f"    - {label}", file=sys.stderr)
        print(json.dumps({"conflicts": all_conflicts}, indent=2))

    if totals["errors"] > 0 or totals["skipped"] > 0:
        sys.exit(1)
    if all_conflicts:
        sys.exit(2)


if __name__ == "__main__":
    main()

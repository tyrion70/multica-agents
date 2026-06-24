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
  1  one or more errors (schema validation, API failure, etc.)
  2  one or more conflicts (no errors; manual resolution needed)

Usage:
  scripts/sync.py                              # sync agents + skills, all workspaces
  scripts/sync.py --type agents                # agents only
  scripts/sync.py --type skills                # skills only
  scripts/sync.py --workspace Chainlayer       # one workspace; passes --workspace-id to every CLI call
  scripts/sync.py --workspace Private          # Private workspace (9627be94-...)
  scripts/sync.py --dry-run                    # print what would happen, no writes
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
SKIP_DIRS = {"schemas", "scripts", ".git", "skills"}

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
# Agent write-back
# ---------------------------------------------------------------------------

def multica_to_agent_json(
    live: Dict[str, Any],
    existing: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    if existing:
        for key in ("custom_env", "mcp_config"):
            if key in existing:
                result[key] = existing[key]
    for field in COMPARABLE_FIELDS:
        if field == "skills":
            result["skills"] = _norm_agent_field("skills", live.get("skills"))
        elif field in ("model", "thinking_level"):
            val = live.get(field)
            result[field] = val if val != "" else None
        elif field == "mcp_config":
            pass
        else:
            val = live.get(field)
            if val is not None:
                result[field] = val
    return result


def write_agent_json(
    agent_json_path: pathlib.Path,
    live_agent: Dict[str, Any],
    dry_run: bool,
) -> None:
    existing: Optional[Dict[str, Any]] = None
    if agent_json_path.is_file():
        with open(agent_json_path) as f:
            existing = json.load(f)
    new_data = multica_to_agent_json(live_agent, existing)
    if dry_run:
        print(f"      [DRY-RUN] would write {agent_json_path}", file=sys.stderr)
        return
    agent_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(agent_json_path, "w") as f:
        json.dump(new_data, f, indent=2, ensure_ascii=False)
        f.write("\n")


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


_PLACEHOLDER_RE = re.compile(r"#[^#]*/\s*([A-Z_][A-Z0-9_]*)\s*#")


def _resolve_mcp_secrets(mcp_config: Any) -> Any:
    """Walk mcp_config recursively, replacing #description / KEY_NAME# placeholders
    with values from environment variables (sourced by sync.sh from the host-local
    /etc/multica/mcp-secrets.env file).
    """
    if isinstance(mcp_config, dict):
        return {k: _resolve_mcp_secrets(v) for k, v in mcp_config.items()}
    if isinstance(mcp_config, list):
        return [_resolve_mcp_secrets(v) for v in mcp_config]
    if isinstance(mcp_config, str):
        def _replace(m: re.Match) -> str:
            key = m.group(1)
            val = os.environ.get(key)
            if val is None:
                print(f"      WARNING: mcp placeholder key {key} not found in environment — leaving as-is", file=sys.stderr)
                return m.group(0)
            return val
        return _PLACEHOLDER_RE.sub(_replace, mcp_config)
    return mcp_config


def _write_mcp_config_tempfile(agent_data: Dict[str, Any]) -> Optional[str]:
    mcp = agent_data.get("mcp_config")
    if mcp is None:
        return None
    mcp = _resolve_mcp_secrets(mcp)
    fd, path = tempfile.mkstemp(suffix=".json", prefix="mcp-config-")
    with os.fdopen(fd, "w") as f:
        json.dump(mcp, f)
    return path


# ---------------------------------------------------------------------------
# Direction detection (shared by agents and skills)
# ---------------------------------------------------------------------------

def _decide_action(
    repo_norm: Any,
    multica_norm: Any,
    last: Optional[Dict[str, Any]],
) -> str:
    if last is None:
        if multica_norm is None:
            return "push_to_multica"
        if repo_norm == multica_norm:
            return "unchanged"
        return "push_to_multica"

    last_repo = last.get("repo_state")
    last_multica = last.get("multica_state")

    repo_changed = repo_norm != last_repo
    multica_changed = multica_norm != last_multica

    if not repo_changed and not multica_changed:
        return "unchanged"
    if repo_changed and not multica_changed:
        return "push_to_multica"
    if not repo_changed and multica_changed:
        if multica_norm is None:
            return "unchanged"
        return "pull_to_repo"
    if repo_norm == multica_norm:
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
    dry_run: bool,
) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    workspace_name = workspace_dir.name
    print(f"\n── Agents: {workspace_name} ──", file=sys.stderr)

    counts: Dict[str, int] = defaultdict(int)
    conflicts: List[Dict[str, Any]] = []
    state_agents = state.setdefault("agents", {})

    known_agent_names: set = set()

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

            live_agent = live_agents.get(agent_name)
            state_key = f"{workspace_name}~{agent_name}"
            last = state_agents.get(state_key)
            repo_norm = normalize_agent(repo_data)
            multica_norm = normalize_agent(live_agent) if live_agent else None

            action = _decide_action(repo_norm, multica_norm, last)
            agent_id: Optional[str] = live_agent["id"] if live_agent else None

            if action == "unchanged":
                print(f"    ✓ unchanged", file=sys.stderr)
                counts["unchanged"] += 1
                state_agents[state_key] = {
                    "repo_file": str(rel_path),
                    "repo_state": repo_norm,
                    "multica_state": multica_norm,
                }

            elif action == "push_to_multica":
                mcp_file = _write_mcp_config_tempfile(repo_data)
                try:
                    mcp_args = ["--mcp-config-file", mcp_file] if mcp_file else []
                    if live_agent is None:
                        print(f"    → creating in Multica", file=sys.stderr)
                        try:
                            if not dry_run:
                                result = _multica(["agent", "create"] + build_create_args(repo_data) + mcp_args)
                                agent_id = result["id"]
                            else:
                                _multica(["agent", "create"] + build_create_args(repo_data) + mcp_args, dry_run=True)
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
                finally:
                    if mcp_file:
                        os.unlink(mcp_file)

                desired_skills = repo_norm.get("skills") or []
                if desired_skills and agent_id:
                    try:
                        ensure_agent_skills(agent_id, desired_skills, skill_map, dry_run)
                    except Exception as e:
                        print(f"    ✗ SKILLS FAILED: {e}", file=sys.stderr)
                        counts["errors"] += 1

                state_agents[state_key] = {
                    "repo_file": str(rel_path),
                    "repo_state": repo_norm,
                    "multica_state": repo_norm,
                }

            elif action == "pull_to_repo":
                print(f"    → writing repo (Multica changed)", file=sys.stderr)
                try:
                    write_agent_json(agent_json_path, live_agent, dry_run)
                    counts["repo_updated"] += 1
                except Exception as e:
                    print(f"    ✗ REPO WRITE FAILED: {e}", file=sys.stderr)
                    counts["errors"] += 1
                    continue
                state_agents[state_key] = {
                    "repo_file": str(rel_path),
                    "repo_state": multica_norm,
                    "multica_state": multica_norm,
                }

            elif action == "conflict":
                print(f"    ✗ CONFLICT: both sides changed", file=sys.stderr)
                conflicts.append({
                    "type": "agent",
                    "name": agent_name,
                    "repo_file": str(rel_path),
                    "repo_state": repo_norm,
                    "multica_state": multica_norm,
                    "last_synced_repo": last.get("repo_state") if last else None,
                    "last_synced_multica": last.get("multica_state") if last else None,
                })
                counts["conflicts"] += 1

    # --- Discovery phase: Multica agents not in the repo ---
    agent_squad_map: Optional[Dict[str, str]] = None

    for live_name, live_agent in sorted(live_agents.items()):
        if live_name in known_agent_names:
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
            multica_norm = normalize_agent(live_agent) if live_agent else None
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
            try:
                write_agent_json(agent_json_path, live_agent, dry_run)
                counts["repo_updated"] += 1
            except Exception as e:
                print(f"    ✗ REPO WRITE FAILED: {e}", file=sys.stderr)
                counts["errors"] += 1
                continue

            state_agents[state_key] = {
                "repo_file": str(rel_path),
                "repo_state": normalize_agent(live_agent),
                "multica_state": normalize_agent(live_agent),
            }

        elif action == "conflict":
            print(f"    ✗ CONFLICT: agent '{live_name}' — both sides changed", file=sys.stderr)
            conflicts.append({
                "type": "agent",
                "name": live_name,
                "repo_file": "(missing — agent only in Multica)",
                "repo_state": None,
                "multica_state": normalize_agent(live_agent),
                "last_synced_repo": last.get("repo_state") if last else None,
                "last_synced_multica": last.get("multica_state") if last else None,
            })
            counts["conflicts"] += 1

    print(
        f"  agents {workspace_name}: created={counts['created']} updated={counts['updated']} "
        f"repo_updated={counts['repo_updated']} unchanged={counts['unchanged']} "
        f"conflicts={counts['conflicts']} errors={counts['errors']}",
        file=sys.stderr,
    )
    return counts, conflicts


# ---------------------------------------------------------------------------
# Skills: parsing, normalization, write-back
# ---------------------------------------------------------------------------

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
    """Normalize a live Multica skill for state comparison."""
    files: Dict[str, str] = {}
    for f in live.get("files") or []:
        files[f["path"]] = f.get("content", "")
    return {
        "name": live.get("name", ""),
        "description": live.get("description", ""),
        "body": live.get("content", ""),
        "files": files,
    }


def fetch_skill_detail(skill_id: str) -> Dict[str, Any]:
    return _multica(["skill", "get", skill_id], dry_run=False)


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
            _push_skill_to_multica(skill_name, repo_norm, skill_id, live_skill, counts, dry_run)
            state_skills[skill_name] = {
                "repo_state": repo_norm,
                "multica_state": repo_norm,
            }

        elif action == "pull_to_repo":
            _pull_skill_to_repo(skill_name, multica_norm, dry_run)
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
    args = parser.parse_args()

    # Resolve workspace slug to UUID and forward as --workspace-id to every
    # multica CLI call via the module-level _workspace_id variable.
    global _workspace_id
    if args.workspace:
        workspace_id = WORKSPACE_IDS.get(args.workspace)
        if workspace_id:
            _workspace_id = workspace_id
            print(f"==> Workspace: {args.workspace} ({workspace_id})", file=sys.stderr)
        else:
            print(
                f"WARNING: workspace '{args.workspace}' not in WORKSPACE_IDS — "
                f"multica will use the host default workspace. Known slugs: {list(WORKSPACE_IDS)}",
                file=sys.stderr,
            )

    state_path = pathlib.Path(args.sync_state)
    sync_agents = args.type in ("agents", "all")
    sync_skills = args.type in ("skills", "all")

    print(f"==> Loading schema", file=sys.stderr)
    schema = load_schema() if sync_agents else {}

    print(f"==> Loading sync state from {state_path}", file=sys.stderr)
    state = load_sync_state(state_path)

    live_agents: Dict[str, Dict[str, Any]] = {}
    skill_map: Dict[str, str] = {}
    live_skills_detail: Dict[str, Dict[str, Any]] = {}

    if sync_agents:
        print("==> Fetching live agents from Multica", file=sys.stderr)
        live_agents = fetch_live_agents(args.dry_run)
        print("==> Fetching skill catalog from Multica", file=sys.stderr)
        skill_map = fetch_live_agent_skills(args.dry_run)

    if sync_skills:
        print("==> Fetching live skills from Multica", file=sys.stderr)
        skills_list = _multica(["skill", "list"], dry_run=False)
        live_skills_detail = {s["name"]: s for s in skills_list}

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

    totals: Dict[str, int] = defaultdict(int)
    all_conflicts: List[Dict[str, Any]] = []

    for ws in workspaces:
        if sync_agents:
            counts, conflicts = sync_agents_workspace(
                ws, schema, live_agents, skill_map, state, args.dry_run
            )
            for k, v in counts.items():
                totals[k] += v
            all_conflicts.extend(conflicts)

        if sync_skills:
            counts, conflicts = sync_skills_workspace(
                ws, live_skills_detail, state, args.dry_run
            )
            for k, v in counts.items():
                totals[k] += v
            all_conflicts.extend(conflicts)

    mode = "DRY-RUN" if args.dry_run else "SYNC"
    print(f"\n==> {mode} COMPLETE", file=sys.stderr)
    print(
        f"    total: created={totals['created']} updated={totals['updated']} "
        f"repo_updated={totals['repo_updated']} "
        f"unchanged={totals['unchanged']} conflicts={totals['conflicts']} errors={totals['errors']}",
        file=sys.stderr,
    )

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

    if totals["errors"] > 0:
        sys.exit(1)
    if all_conflicts:
        sys.exit(2)


if __name__ == "__main__":
    main()

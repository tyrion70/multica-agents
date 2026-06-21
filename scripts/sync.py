#!/usr/bin/env python3
"""
sync.py — Bidirectional reconciliation: multica-agents repo ↔ Multica workspace.

Detects which side changed since the last sync using a .sync-state.json snapshot
file and applies the newer side:

  repo changed, Multica unchanged  → push repo → Multica (create or update)
  Multica changed, repo unchanged  → pull Multica → repo (writes agent.json files)
  both changed                     → conflict: printed to stderr + JSON on stdout, exit 2
  neither changed                  → unchanged

On first sync (no state file), repo is treated as source of truth.

After a run that writes agent.json files back to the repo, the caller is
responsible for committing and pushing them (including .sync-state.json).

Exit codes:
  0  success (no conflicts)
  1  one or more errors (schema validation, API failure, etc.)
  2  one or more conflicts (no errors; manual resolution needed)

Usage:
  scripts/sync.py                         # full sync, all workspaces
  scripts/sync.py --dry-run               # print what would happen, no writes
  scripts/sync.py --workspace Chainlayer  # sync a single workspace
  scripts/sync.py --sync-state /tmp/state.json  # use an alternate state file
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "agent.json"
DEFAULT_STATE_PATH = REPO_ROOT / ".sync-state.json"
SKIP_DIRS = {"schemas", "scripts", ".git"}

MULTICA = os.environ.get("MULTICA", "multica")

# Fields compared between repo and Multica sides.
# custom_env: secrets live only in Multica, never in repo.
# mcp_config: redacted in Multica API responses — cannot be read back.
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
)


# ---------------------------------------------------------------------------
# Multica CLI wrapper
# ---------------------------------------------------------------------------

def _multica(args: List[str], dry_run: bool = False) -> Any:
    """Run a multica CLI command and return parsed JSON output.

    Mutating agent commands are skipped in dry-run mode.
    """
    assert len(args) > 0
    mutating_verbs = {"create", "update", "skills"}
    is_mutation = args[0] == "agent" and len(args) >= 2 and args[1] in mutating_verbs

    if dry_run and is_mutation:
        print(f"      [DRY-RUN] would run: {MULTICA} {' '.join(args)}", file=sys.stderr)
        return None

    cmd = [MULTICA] + args + ["--output", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"multica command failed (exit {result.returncode}):\n"
            f"  command: {' '.join(cmd)}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Schema validation
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
# Normalization: extract and canonicalise the comparable fields
# ---------------------------------------------------------------------------

def _norm_field(key: str, val: Any) -> Any:
    if key in ("model", "thinking_level"):
        # Treat None and "" as equivalent so agent.json null ↔ Multica "" don't diverge.
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
    return val


def normalize_agent(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and normalise COMPARABLE_FIELDS from an agent.json dict or a live Multica agent dict."""
    return {f: _norm_field(f, data.get(f)) for f in COMPARABLE_FIELDS}


# ---------------------------------------------------------------------------
# Sync state file
# ---------------------------------------------------------------------------

def load_sync_state(state_path: pathlib.Path) -> Dict[str, Any]:
    """Load .sync-state.json; returns an empty structure if missing or unreadable."""
    if not state_path.is_file():
        return {"version": 1, "agents": {}}
    try:
        with open(state_path) as f:
            return json.load(f)
    except Exception as e:
        print(f"WARNING: could not read state file {state_path}: {e}", file=sys.stderr)
        return {"version": 1, "agents": {}}


def save_sync_state(state_path: pathlib.Path, state: Dict[str, Any]) -> None:
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------------------
# Write-back: Multica → repo
# ---------------------------------------------------------------------------

def multica_to_agent_json(
    live: Dict[str, Any],
    existing: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build an agent.json dict from a live Multica agent.

    Preserves custom_env and mcp_config from the existing file — both are
    excluded from the Multica API response and must not be overwritten.
    """
    result: Dict[str, Any] = {}

    if existing:
        for key in ("custom_env", "mcp_config"):
            if key in existing:
                result[key] = existing[key]

    for field in COMPARABLE_FIELDS:
        if field == "skills":
            result["skills"] = _norm_field("skills", live.get("skills"))
        elif field in ("model", "thinking_level"):
            val = live.get(field)
            # Store None explicitly (matches the schema's oneOf null|string)
            result[field] = val if val != "" else None
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
    """Write (or update) an agent.json from a live Multica agent dict."""
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
# Live data fetching
# ---------------------------------------------------------------------------

def fetch_live_agents(dry_run: bool) -> Dict[str, Dict[str, Any]]:
    """Return {agent_name: agent_dict} for all agents in the workspace."""
    agents = _multica(["agent", "list"], dry_run=False)
    return {a["name"]: a for a in agents}


def fetch_live_skills(dry_run: bool) -> Dict[str, str]:
    """Return {skill_name: skill_id} for all skills in the workspace."""
    skills = _multica(["skill", "list"], dry_run=False)
    return {s["name"]: s["id"] for s in skills}


# ---------------------------------------------------------------------------
# Skills sync
# ---------------------------------------------------------------------------

def ensure_skills(
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


# ---------------------------------------------------------------------------
# CLI arg builders (repo → Multica)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Action determination
# ---------------------------------------------------------------------------

def _decide_action(
    repo_norm: Dict[str, Any],
    multica_norm: Optional[Dict[str, Any]],
    last: Optional[Dict[str, Any]],
) -> str:
    """Return the sync action for one agent.

    Possible return values:
      unchanged       — both sides match, nothing to do
      push_to_multica — repo is newer (or first sync); create/update Multica
      pull_to_repo    — Multica is newer; write agent.json
      conflict        — both sides changed since last sync
    """
    if last is None:
        # First time this agent has been seen — repo wins.
        if multica_norm is None:
            return "push_to_multica"
        if repo_norm == multica_norm:
            return "unchanged"
        return "push_to_multica"

    last_repo = last.get("repo_state") or {}
    last_multica = last.get("multica_state")

    repo_changed = repo_norm != last_repo
    multica_changed = multica_norm != last_multica

    if not repo_changed and not multica_changed:
        return "unchanged"
    if repo_changed and not multica_changed:
        return "push_to_multica"
    if not repo_changed and multica_changed:
        # If Multica deleted the agent (multica_norm is None) but the repo file
        # is still present, do nothing — don't auto-recreate or delete.
        if multica_norm is None:
            return "unchanged"
        return "pull_to_repo"
    return "conflict"


# ---------------------------------------------------------------------------
# Workspace sync
# ---------------------------------------------------------------------------

def sync_workspace(
    workspace_dir: pathlib.Path,
    schema: Dict[str, Any],
    live_agents: Dict[str, Dict[str, Any]],
    skill_map: Dict[str, str],
    state: Dict[str, Any],
    dry_run: bool,
) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    """Sync all agents under one workspace directory.

    Returns (counts, conflicts).
    Mutates state["agents"] in place for successfully processed agents.
    """
    workspace_name = workspace_dir.name
    print(f"\n── Workspace: {workspace_name} ──", file=sys.stderr)

    counts: Dict[str, int] = defaultdict(int)
    conflicts: List[Dict[str, Any]] = []
    state_agents = state.setdefault("agents", {})

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

            live_agent = live_agents.get(agent_name)
            last = state_agents.get(agent_name)
            repo_norm = normalize_agent(repo_data)
            multica_norm = normalize_agent(live_agent) if live_agent else None

            action = _decide_action(repo_norm, multica_norm, last)

            agent_id: Optional[str] = live_agent["id"] if live_agent else None

            # ----------------------------------------------------------
            if action == "unchanged":
                print(f"    ✓ unchanged", file=sys.stderr)
                counts["unchanged"] += 1
                state_agents[agent_name] = {
                    "repo_file": str(rel_path),
                    "repo_state": repo_norm,
                    "multica_state": multica_norm,
                }

            # ----------------------------------------------------------
            elif action == "push_to_multica":
                if live_agent is None:
                    print(f"    → creating in Multica (new in repo)", file=sys.stderr)
                    try:
                        if not dry_run:
                            result = _multica(["agent", "create"] + build_create_args(repo_data))
                            agent_id = result["id"]
                            print(f"    ✓ created (id={agent_id})", file=sys.stderr)
                        else:
                            _multica(["agent", "create"] + build_create_args(repo_data), dry_run=True)
                        counts["created"] += 1
                    except Exception as e:
                        print(f"    ✗ CREATE FAILED: {e}", file=sys.stderr)
                        counts["errors"] += 1
                        continue
                else:
                    print(f"    → updating Multica (repo changed, id={agent_id})", file=sys.stderr)
                    try:
                        _multica(["agent", "update"] + build_update_args(agent_id, repo_data), dry_run=dry_run)
                        counts["updated"] += 1
                    except Exception as e:
                        print(f"    ✗ UPDATE FAILED: {e}", file=sys.stderr)
                        counts["errors"] += 1
                        continue

                desired_skills = repo_norm.get("skills") or []
                if desired_skills and agent_id:
                    try:
                        ensure_skills(agent_id, desired_skills, skill_map, dry_run)
                        print(f"    ✓ skills set: {', '.join(desired_skills)}", file=sys.stderr)
                    except Exception as e:
                        print(f"    ✗ SKILLS FAILED: {e}", file=sys.stderr)
                        counts["errors"] += 1

                # After a successful push, both sides now mirror repo_norm.
                state_agents[agent_name] = {
                    "repo_file": str(rel_path),
                    "repo_state": repo_norm,
                    "multica_state": repo_norm,
                }

            # ----------------------------------------------------------
            elif action == "pull_to_repo":
                print(f"    → writing repo (Multica changed, id={agent_id})", file=sys.stderr)
                try:
                    write_agent_json(agent_json_path, live_agent, dry_run)
                    counts["repo_updated"] += 1
                    print(f"    ✓ wrote {rel_path}", file=sys.stderr)
                except Exception as e:
                    print(f"    ✗ REPO WRITE FAILED: {e}", file=sys.stderr)
                    counts["errors"] += 1
                    continue

                # After a successful pull, both sides now mirror multica_norm.
                state_agents[agent_name] = {
                    "repo_file": str(rel_path),
                    "repo_state": multica_norm,
                    "multica_state": multica_norm,
                }

            # ----------------------------------------------------------
            elif action == "conflict":
                print(
                    f"    ✗ CONFLICT: both repo and Multica changed since last sync",
                    file=sys.stderr,
                )
                conflicts.append({
                    "agent_name": agent_name,
                    "repo_file": str(rel_path),
                    "repo_state": repo_norm,
                    "multica_state": multica_norm,
                    "last_synced_repo": last.get("repo_state") if last else None,
                    "last_synced_multica": last.get("multica_state") if last else None,
                })
                counts["conflicts"] += 1
                # Do NOT update state — leave snapshot unchanged so the conflict
                # remains visible on the next run until it is manually resolved.

    print(
        f"  {workspace_name} summary: "
        f"created={counts['created']} updated={counts['updated']} "
        f"repo_updated={counts['repo_updated']} "
        f"unchanged={counts['unchanged']} conflicts={counts['conflicts']} errors={counts['errors']}",
        file=sys.stderr,
    )
    return counts, conflicts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bidirectional sync: multica-agents repo ↔ Multica workspace"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without making any changes",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Sync only the named workspace directory (default: all)",
    )
    parser.add_argument(
        "--sync-state",
        type=str,
        default=str(DEFAULT_STATE_PATH),
        help=f"Path to the sync-state snapshot file (default: {DEFAULT_STATE_PATH})",
    )
    args = parser.parse_args()

    state_path = pathlib.Path(args.sync_state)

    print(f"==> Loading schema from {SCHEMA_PATH}", file=sys.stderr)
    schema = load_schema()

    print(f"==> Loading sync state from {state_path}", file=sys.stderr)
    state = load_sync_state(state_path)

    print("==> Fetching live agents from Multica", file=sys.stderr)
    live_agents = fetch_live_agents(args.dry_run)

    print("==> Fetching skill catalog from Multica", file=sys.stderr)
    skill_map = fetch_live_skills(args.dry_run)

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
        counts, conflicts = sync_workspace(ws, schema, live_agents, skill_map, state, args.dry_run)
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
                f"==> {totals['repo_updated']} agent.json file(s) updated — "
                f"commit {state_path.name} and changed agent.json files to persist.",
                file=sys.stderr,
            )

    if all_conflicts:
        print(f"\n==> CONFLICTS ({len(all_conflicts)} — manual resolution needed):", file=sys.stderr)
        for c in all_conflicts:
            print(f"    - {c['agent_name']} ({c['repo_file']})", file=sys.stderr)
        # Emit structured conflict data to stdout for the calling agent to file issues.
        print(json.dumps({"conflicts": all_conflicts}, indent=2))

    if totals["errors"] > 0:
        sys.exit(1)
    if all_conflicts:
        sys.exit(2)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
sync.py — Reconcile multica-agents repo → Multica workspace.

Reads agent.json files from the repo's workspace/squad/agent/ structure,
validates them against schemas/agent.json, diffs against the live Multica
state, and creates or updates agents via the multica CLI.

Usage:
  scripts/sync.py                    # full sync, all workspaces
  scripts/sync.py --dry-run          # print what would happen, no API calls
  scripts/sync.py --workspace Chainlayer  # sync a single workspace
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "agent.json"
SKIP_DIRS = {"schemas", "scripts", ".git"}

MULTICA = os.environ.get("MULTICA", "multica")


def _multica(args: List[str], dry_run: bool = False) -> Any:
    """Run a multica CLI command and return parsed JSON output.

    If dry_run is True, mutating commands (create, update, skills set/add)
    are skipped and a dry-run log is printed instead.
    """
    assert len(args) > 0
    mutating_verbs = {"create", "update", "skills"}
    is_mutation = args[0] == "agent" and len(args) >= 2 and args[1] in mutating_verbs

    if dry_run and is_mutation:
        cmd_str = " ".join([MULTICA] + args)
        print(f"      [DRY-RUN] would run: {cmd_str}", file=sys.stderr)
        return None

    cmd = [MULTICA] + args + ["--output", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        cmd_str = " ".join(cmd)
        raise RuntimeError(
            f"multica command failed (exit {result.returncode}):\n"
            f"  command: {cmd_str}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


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


def _normalize(val: Any) -> Any:
    """Normalize None → '' for optional string fields used in comparison."""
    if val is None:
        return ""
    return val


def fetch_live_agents(dry_run: bool) -> Dict[str, Dict[str, Any]]:
    """Return {agent_name: agent_dict} from current Multica workspace.

    This is read-only; dry_run does not affect it.
    """
    agents = _multica(["agent", "list"], dry_run=False)
    by_name: Dict[str, Dict[str, Any]] = {}
    for a in agents:
        by_name[a["name"]] = a
    return by_name


def fetch_live_skills(dry_run: bool) -> Dict[str, str]:
    """Return {skill_name: skill_id} from current Multica workspace."""
    skills = _multica(["skill", "list"], dry_run=False)
    return {s["name"]: s["id"] for s in skills}


def agent_differs(
    desired: Dict[str, Any],
    live: Dict[str, Any],
) -> bool:
    """Compare repo agent.json fields against the live Multica agent.

    Excluded from comparison: custom_env (secrets live only in Multica),
    mcp_config (redacted for agent actors — placeholder comparison only).
    """
    for key, desired_val in desired.items():
        if key in ("custom_env", "mcp_config"):
            continue
        if key == "skills":
            live_skill_names = sorted(s.get("name", s.get("slug", "")) for s in (live.get("skills") or []))
            desired_skill_names = sorted(s for s in (desired_val or []))
            if live_skill_names != desired_skill_names:
                return True
            continue
        if key in ("model", "thinking_level"):
            if _normalize(desired_val) != _normalize(live.get(key, "")):
                return True
            continue
        if key in ("custom_args", "runtime_config"):
            if desired_val != live.get(key):
                return True
            continue
        if desired_val != live.get(key):
            return True

    return False


def apply_mcp_config(
    agent_id: str,
    agent_data: Dict[str, Any],
    dry_run: bool,
    tmpdir: pathlib.Path,
) -> bool:
    """Apply mcp_config from agent.json to the agent via --mcp-config-file.

    Returns True if MCP config was applied (or would have been).
    Skips if mcp_config is missing, None, or a placeholder string.
    """
    import tempfile

    mcp = agent_data.get("mcp_config")
    if not isinstance(mcp, dict):
        return False

    if dry_run:
        print(f"      [DRY-RUN] would apply mcp_config to {agent_id}", file=sys.stderr)
        return True

    fd, tmp_path = tempfile.mkstemp(
        suffix=".json",
        prefix="mcp-",
        dir=str(tmpdir),
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(mcp, f)
        _multica(
            ["agent", "update", agent_id, "--mcp-config-file", tmp_path],
            dry_run=False,
        )
        print(f"      ✓ mcp_config applied", file=sys.stderr)
        return True
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def build_create_args(agent_data: Dict[str, Any]) -> List[str]:
    """Build multica agent create CLI argument list from agent.json fields.

    custom_env is intentionally excluded. mcp_config is applied separately
    via apply_mcp_config() after create.
    """
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
    """Build multica agent update CLI argument list.

    Only the agent ID and changed fields are included.
    custom_env is intentionally excluded. mcp_config is applied separately
    via apply_mcp_config() after update.
    """
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


def ensure_skills(
    agent_id: str,
    desired_skill_names: List[str],
    skill_name_to_id: Dict[str, str],
    dry_run: bool,
) -> bool:
    """Set agent skills to match desired_skill_names.

    Returns True if skills were changed (or would have been).
    """
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
    return True


def sync_workspace(
    workspace_dir: pathlib.Path,
    schema: Dict[str, Any],
    live_agents: Dict[str, Dict[str, Any]],
    skill_map: Dict[str, str],
    dry_run: bool,
    tmpdir: pathlib.Path,
) -> Dict[str, int]:
    """Sync all agents under one workspace directory.

    Returns a dict of counts: created, updated, unchanged, errors, skipped_schema.
    """
    workspace_name = workspace_dir.name
    print(f"\n── Workspace: {workspace_name} ──", file=sys.stderr)

    counts: Dict[str, int] = defaultdict(int)

    for squad_dir in sorted(workspace_dir.iterdir()):
        if not squad_dir.is_dir() or squad_dir.name.startswith("."):
            continue

        squad_name = squad_dir.name

        for agent_dir in sorted(squad_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            agent_json_path = agent_dir / "agent.json"
            if not agent_json_path.is_file():
                continue

            agent_slug = agent_dir.name
            rel_path = agent_json_path.relative_to(REPO_ROOT)
            label = f"{workspace_name}/{squad_name}/{agent_slug}"
            print(f"  {rel_path}", file=sys.stderr)

            try:
                agent_data = validate_agent_json(agent_json_path, schema)
            except Exception as e:
                print(f"    ✗ SCHEMA VALIDATION FAILED: {e}", file=sys.stderr)
                counts["errors"] += 1
                continue

            agent_name = agent_data.get("name", "")
            if not agent_name:
                print(f"    ✗ missing required 'name' field", file=sys.stderr)
                counts["errors"] += 1
                continue

            if agent_name in live_agents:
                existing = live_agents[agent_name]
                if not agent_differs(agent_data, existing):
                    agent_id = existing["id"]
                    try:
                        apply_mcp_config(agent_id, agent_data, dry_run, tmpdir)
                    except Exception as e:
                        print(f"    ✗ MCP CONFIG FAILED: {e}", file=sys.stderr)
                        counts["errors"] += 1
                    print(f"    ✓ unchanged (id={existing['id']})", file=sys.stderr)
                    counts["unchanged"] += 1
                    continue

                agent_id = existing["id"]
                print(f"    → updating (id={existing['id']})", file=sys.stderr)
                try:
                    update_args = build_update_args(existing["id"], agent_data)
                    if not dry_run:
                        result = _multica(
                            ["agent", "update"] + update_args,
                            dry_run=dry_run,
                        )
                    else:
                        _multica(
                            ["agent", "update"] + update_args,
                            dry_run=dry_run,
                        )
                    counts["updated"] += 1
                except Exception as e:
                    print(f"    ✗ UPDATE FAILED: {e}", file=sys.stderr)
                    counts["errors"] += 1
                    continue
            else:
                print(f"    → creating new agent", file=sys.stderr)
                try:
                    create_args = build_create_args(agent_data)
                    if not dry_run:
                        result = _multica(
                            ["agent", "create"] + create_args,
                            dry_run=dry_run,
                        )
                        agent_id = result["id"]
                        print(f"    ✓ created (id={agent_id})", file=sys.stderr)
                    else:
                        _multica(
                            ["agent", "create"] + create_args,
                            dry_run=dry_run,
                        )
                        agent_id = None
                    counts["created"] += 1
                except Exception as e:
                    print(f"    ✗ CREATE FAILED: {e}", file=sys.stderr)
                    counts["errors"] += 1
                    continue

            try:
                apply_mcp_config(agent_id, agent_data, dry_run, tmpdir)
            except Exception as e:
                print(f"    ✗ MCP CONFIG FAILED: {e}", file=sys.stderr)
                counts["errors"] += 1

            desired_skills = agent_data.get("skills", [])
            if desired_skills and agent_id:
                try:
                    ensure_skills(agent_id, desired_skills, skill_map, dry_run)
                    print(f"    ✓ skills set: {', '.join(desired_skills)}", file=sys.stderr)
                except Exception as e:
                    print(f"    ✗ SKILLS FAILED: {e}", file=sys.stderr)
                    counts["errors"] += 1

    print(
        f"  {workspace_name} summary: "
        f"created={counts['created']} updated={counts['updated']} "
        f"unchanged={counts['unchanged']} errors={counts['errors']}",
        file=sys.stderr,
    )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync agents from repo to Multica workspace")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without making any API calls",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Sync only the named workspace directory (default: all workspaces)",
    )
    args = parser.parse_args()

    print(f"==> Loading schema from {SCHEMA_PATH}", file=sys.stderr)
    schema = load_schema()

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

    import tempfile
    with tempfile.TemporaryDirectory(prefix="multica-sync-") as tmpdir_path:
        tmpdir = pathlib.Path(tmpdir_path)
        for ws in workspaces:
            counts = sync_workspace(ws, schema, live_agents, skill_map, args.dry_run, tmpdir)
            for k, v in counts.items():
                totals[k] += v

    mode = "DRY-RUN" if args.dry_run else "SYNC"
    print(f"\n==> {mode} COMPLETE", file=sys.stderr)
    print(
        f"    total: created={totals['created']} updated={totals['updated']} "
        f"unchanged={totals['unchanged']} errors={totals['errors']}",
        file=sys.stderr,
    )

    if totals["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

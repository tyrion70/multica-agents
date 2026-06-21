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
  scripts/sync.py --workspace Chainlayer       # one workspace
  scripts/sync.py --dry-run                    # print what would happen, no writes
  scripts/sync.py --sync-state /tmp/state.json # alternate state file

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

def _multica(args: List[str], dry_run: bool = False, mutating: bool = False) -> Any:
    """Run a multica CLI command and return parsed JSON output.

    Pass mutating=True for commands that write data so dry-run can skip them.
    """
    assert len(args) > 0

    if dry_run and mutating:
        print(f"      [DRY-RUN] would run: {MULTICA} {' '.join(args)}", file=sys.stderr)
        return None

    # Legacy agent mutation detection for backwards compatibility
    agent_mutating = (
        args[0] == "agent"
        and len(args) >= 2
        and args[1] in {"create", "update", "skills"}
    )
    if dry_run and agent_mutating:
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
    return "conflict"


# ---------------------------------------------------------------------------
# Agent workspace sync
# ---------------------------------------------------------------------------

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

            if action == "unchanged":
                print(f"    ✓ unchanged", file=sys.stderr)
                counts["unchanged"] += 1
                state_agents[agent_name] = {
                    "repo_file": str(rel_path),
                    "repo_state": repo_norm,
                    "multica_state": multica_norm,
                }

            elif action == "push_to_multica":
                if live_agent is None:
                    print(f"    → creating in Multica", file=sys.stderr)
                    try:
                        if not dry_run:
                            result = _multica(["agent", "create"] + build_create_args(repo_data))
                            agent_id = result["id"]
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
                        ensure_agent_skills(agent_id, desired_skills, skill_map, dry_run)
                    except Exception as e:
                        print(f"    ✗ SKILLS FAILED: {e}", file=sys.stderr)
                        counts["errors"] += 1

                state_agents[agent_name] = {
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
                state_agents[agent_name] = {
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

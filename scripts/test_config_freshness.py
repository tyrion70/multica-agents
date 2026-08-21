"""check-config-freshness.sh — the BASELINE_LAG detector (CHA-1087).

.sync-state.json is the committed record of what was last pushed to each Multica
workspace. When a skill or agent merges and nobody commits the refreshed state, the
baseline falls behind the live workspaces — so the NEXT unrelated change reads as
"both sides changed" and sync.sh exits 2 on a conflict that is not one. That is
precisely how the Private/ssh conflict arose.

These drive the real script against a purpose-built git repo, so they test the
detector rather than its source text.
"""
import os
import pathlib
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parent / "check-config-freshness.sh"


def _git(repo, *args, env=None):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, env={**os.environ, **(env or {})})


def _commit(repo, message, when):
    """Commit with a fixed timestamp so ordering is deterministic, not wall-clock."""
    stamp = f"{when} +0000"
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message,
         env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})


@pytest.fixture
def repo(tmp_path):
    """A repo shaped like multica-agents, with origin/main resolvable locally."""
    r = tmp_path / "multica-agents"
    (r / "skills" / "demo").mkdir(parents=True)
    (r / "claude-config" / "chainlayer").mkdir(parents=True)
    _git(r.parent, "init", "-q", "-b", "main", str(r))
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "claude-config" / "chainlayer" / "CLAUDE.md").write_text("deployed content\n")
    (r / "skills" / "demo" / "SKILL.md").write_text("v1\n")
    (r / ".sync-state.json").write_text('{"version": 1}\n')
    _commit(r, "initial", 1000000000)
    # the script reads origin/main; point origin at the repo itself so fetch works
    _git(r, "remote", "add", "origin", str(r))
    _git(r, "fetch", "-q", "origin", "main")
    return r


def _run(repo, deployed):
    env = {**os.environ,
           "CONFIG_FRESHNESS_REPO": str(repo),
           "CONFIG_FRESHNESS_DEPLOYED": str(deployed),
           "CONFIG_FRESHNESS_LOG_DIR": str(repo.parent / "logs"),
           "CONFIG_FRESHNESS_SLACK_TOKEN": "",
           "CONFIG_FRESHNESS_SLACK_WEBHOOK": "",
           "CONFIG_FRESHNESS_STALE_HOURS": "999999"}
    p = subprocess.run(["bash", str(SCRIPT), "--profile", "chainlayer",
                        "--repo", str(repo)],
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stdout


@pytest.fixture
def deployed(repo, tmp_path):
    """A deployed CLAUDE.md matching origin/main, so the existing checks pass and the
    lag branch is the one under test."""
    d = tmp_path / "CLAUDE.md"
    d.write_text((repo / "claude-config" / "chainlayer" / "CLAUDE.md").read_text())
    return d


def test_a_committed_baseline_newer_than_the_definitions_is_fresh(repo, deployed):
    (repo / "skills" / "demo" / "SKILL.md").write_text("v2\n")
    _commit(repo, "change the skill", 1000001000)
    (repo / ".sync-state.json").write_text('{"version": 2}\n')
    _commit(repo, "chore: sync state", 1000002000)      # state AFTER the skill
    _git(repo, "fetch", "-q", "origin", "main")
    rc, out = _run(repo, deployed)
    assert "state=FRESH" in out, out
    assert "baseline_lag_sec=0" in out
    assert rc == 0


def test_a_skill_merged_after_the_last_state_commit_is_baseline_lag(repo, deployed):
    """The real scenario: #112 merged, nobody committed the refreshed state."""
    (repo / ".sync-state.json").write_text('{"version": 2}\n')
    _commit(repo, "chore: sync state", 1000001000)
    (repo / "skills" / "demo" / "SKILL.md").write_text("v2\n")
    _commit(repo, "docs(demo): change the skill", 1000002000)   # skill AFTER the state
    _git(repo, "fetch", "-q", "origin", "main")
    rc, out = _run(repo, deployed)
    assert "state=BASELINE_LAG" in out, out
    assert "baseline_lag_sec=1000" in out
    assert rc == 4


def test_an_agent_definition_counts_too(repo, deployed):
    """Agents drift the baseline exactly like skills do."""
    (repo / ".sync-state.json").write_text('{"version": 2}\n')
    _commit(repo, "chore: sync state", 1000001000)
    ws = repo / "Chainlayer" / "some-agent"
    ws.mkdir(parents=True)
    (ws / "agent.json").write_text('{"name": "some-agent"}\n')
    _commit(repo, "feat: add an agent", 1000002000)
    _git(repo, "fetch", "-q", "origin", "main")
    rc, out = _run(repo, deployed)
    assert "state=BASELINE_LAG" in out, out
    assert rc == 4


def test_a_mismatched_claude_md_still_outranks_baseline_lag(repo, deployed, tmp_path):
    """A wrong deployed CLAUDE.md is the more urgent failure and must not be masked."""
    (repo / ".sync-state.json").write_text('{"version": 2}\n')
    _commit(repo, "chore: sync state", 1000001000)
    (repo / "skills" / "demo" / "SKILL.md").write_text("v2\n")
    _commit(repo, "docs(demo): change the skill", 1000002000)
    _git(repo, "fetch", "-q", "origin", "main")
    wrong = tmp_path / "wrong-CLAUDE.md"
    wrong.write_text("something else entirely\n")
    rc, out = _run(repo, wrong)
    assert "state=MISMATCH" in out, out
    assert rc == 1


def test_the_lag_seconds_are_reported_for_triage(repo, deployed):
    """The number is the point — it says how long the baseline has been behind."""
    (repo / ".sync-state.json").write_text('{"version": 2}\n')
    _commit(repo, "chore: sync state", 1000000500)
    (repo / "skills" / "demo" / "SKILL.md").write_text("v2\n")
    _commit(repo, "docs(demo): change", 1000086900)
    _git(repo, "fetch", "-q", "origin", "main")
    rc, out = _run(repo, deployed)
    assert "baseline_lag_sec=86400" in out, out

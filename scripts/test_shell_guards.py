#!/usr/bin/env python3
"""Automated coverage for the shell guards (CHA-1211 G3).

`sync.sh`'s commit-scope guard, `commit-sync-state.sh`, and `update-checkout.sh`
were each verified by hand once and then unwatched — CI ran `test_sync.py` only.
By this incident's own standard that is a guard that regresses quietly, so these
drive the real scripts through `subprocess` in throwaway git repos.

Exit codes under test:
  5  commit-scope violation, or a `git status` that could not be read
  6  the checkout is not at origin/main and must not be synced

Run with:  python3 -m pytest scripts/test_shell_guards.py
"""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"

# A `git` that fails only on `status`, to exercise the fail-closed probes. Every
# other subcommand is delegated, so the scripts otherwise behave normally.
GIT_SHIM = """#!/usr/bin/env bash
for a in "$@"; do
  if [ "$a" = "status" ]; then
    echo "fatal: unable to read index file .git/index: Input/output error" >&2
    exit 128
  fi
done
exec {git} "$@"
"""

# A `git` that fails only on `fetch`. Isolates the H1 line: the pull still
# succeeds, the cached `origin/main` still agrees with HEAD, and the only thing
# that goes wrong is the verification step itself.
GIT_FETCH_SHIM = """#!/usr/bin/env bash
for a in "$@"; do
  if [ "$a" = "fetch" ]; then
    echo "fatal: unable to access remote: Could not resolve host" >&2
    exit 128
  fi
done
exec {git} "$@"
"""


# A `git` whose `fetch` never returns, to exercise the wall-clock cap.
GIT_HANG_SHIM = """#!/usr/bin/env bash
for a in "$@"; do
  if [ "$a" = "fetch" ]; then
    sleep 30
    exit 0
  fi
done
exec {git} "$@"
"""

# A `multica` stand-in for sync.sh's workspace pre-flight guard. MODE picks the
# failure being modelled; nothing else in sync.sh calls multica before the guard.
MULTICA_SHIM = """#!/usr/bin/env bash
case "{mode}" in
  fail)      echo "You do not have permission to access this resource." >&2; exit 3 ;;
  garbage)   echo "not json at all" ;;
  mismatch)  echo '{{"name": "Private"}}' ;;
  match)     echo '{{"name": "Chainlayer"}}' ;;
esac
"""


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"},
    )


class ShellGuardTestCase(unittest.TestCase):
    """A throwaway repo with a local bare remote and the real scripts in it."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.remote = self.tmp / "remote.git"
        self.work = self.tmp / "work"
        _git("init", "-q", "--bare", "-b", "main", str(self.remote), cwd=self.tmp)
        _git("clone", "-q", str(self.remote), str(self.work), cwd=self.tmp)

        (self.work / "scripts").mkdir()
        # Copy what exists rather than asserting the set: run against an older
        # tree (a counterfactual check) and the missing script should make its
        # own tests skip, not blow up every class's setUp.
        for name in ("sync.sh", "commit-sync-state.sh", "update-checkout.sh", "sync.py"):
            if (SCRIPTS / name).is_file():
                shutil.copy2(SCRIPTS / name, self.work / "scripts" / name)
        (self.work / "skills" / "demo").mkdir(parents=True)
        (self.work / "skills" / "demo" / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\n---\n\nreal body\n", encoding="utf-8")
        (self.work / ".sync-state.json").write_text(
            json.dumps({"version": 1, "agents": {}, "skills": {}}) + "\n", encoding="utf-8")
        _git("add", "-A", cwd=self.work)
        _git("commit", "-q", "-m", "baseline", cwd=self.work)
        _git("push", "-q", "-u", "origin", "main", cwd=self.work)

        shim_dir = self.tmp / "shim"
        shim_dir.mkdir()
        shim = shim_dir / "git"
        shim.write_text(GIT_SHIM.format(git=shutil.which("git")), encoding="utf-8")
        shim.chmod(0o755)
        self.shim_path = f"{shim_dir}:{os.environ['PATH']}"

        fetch_shim_dir = self.tmp / "fetch-shim"
        fetch_shim_dir.mkdir()
        fetch_shim = fetch_shim_dir / "git"
        fetch_shim.write_text(GIT_FETCH_SHIM.format(git=shutil.which("git")), encoding="utf-8")
        fetch_shim.chmod(0o755)
        self.fetch_shim_path = f"{fetch_shim_dir}:{os.environ['PATH']}"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ----------------------------------------------------------

    def run_script(self, name, *args, path=None, cwd=None):
        env = {**os.environ, "BW_BOOTSTRAP": str(self.tmp / "no-such-bootstrap")}
        if path:
            env["PATH"] = path
        return subprocess.run(
            ["bash", str(self.work / "scripts" / name), *args],
            cwd=str(cwd or self.work), capture_output=True, text=True, env=env,
        )

    def _shim(self, name, body):
        """Put a single executable on a PATH prefix and return that PATH."""
        d = self.tmp / f"shim-{name}"
        d.mkdir(exist_ok=True)
        exe = d / name
        exe.write_text(body, encoding="utf-8")
        exe.chmod(0o755)
        return f"{d}:{os.environ['PATH']}"

    def run_sync_sh(self, path=None):
        """sync.sh with an argument sync.py rejects, so it exits fast and the
        commit-scope guard still runs — which is the point of `|| rc=$?`."""
        return self.run_script("sync.sh", "--deliberately-bogus-flag", path=path)

    def gut_a_skill(self):
        (self.work / "skills" / "demo" / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\n---\n\n", encoding="utf-8")

    def touch_state(self):
        (self.work / ".sync-state.json").write_text(
            json.dumps({"version": 1, "agents": {}, "skills": {"Chainlayer": {}}}) + "\n",
            encoding="utf-8")


class SyncShScopeGuardTest(ShellGuardTestCase):
    def test_out_of_scope_write_fails_the_run(self):
        """A repo file other than .sync-state.json exits 5 and names the path."""
        self.gut_a_skill()
        self.touch_state()
        r = self.run_sync_sh()
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("COMMIT SCOPE VIOLATION", r.stdout)
        self.assertIn("skills/demo/SKILL.md", r.stdout)

    def test_untracked_file_is_also_out_of_scope(self):
        """--untracked-files=all: a new file counts, not just a modified one."""
        (self.work / "skills" / "demo" / "leftover.sh").write_text("x", encoding="utf-8")
        r = self.run_sync_sh()
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("skills/demo/leftover.sh", r.stdout)

    def test_only_the_state_file_dirty_passes_the_guard(self):
        """The in-scope case must still pass — the guard is not a blanket stop."""
        self.touch_state()
        r = self.run_sync_sh()
        self.assertNotEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertNotIn("COMMIT SCOPE VIOLATION", r.stdout)
        self.assertIn("ACTION REQUIRED", r.stdout)

    def test_clean_tree_passes_silently(self):
        r = self.run_sync_sh()
        self.assertNotEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertNotIn("COMMIT SCOPE VIOLATION", r.stdout)
        self.assertNotIn("ACTION REQUIRED", r.stdout)

    def test_unreadable_git_status_fails_closed(self):
        """F5: a failing `git status` must not read as 'nothing out of scope'."""
        self.gut_a_skill()
        r = self.run_sync_sh(path=self.shim_path)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("cannot verify the commit scope", r.stderr)


class WorkspacePreflightTest(ShellGuardTestCase):
    """sync.sh's workspace pre-flight guard — the eighth instance (CHA-1211).

    It fired only when `$active` was non-empty, so a FAILING `multica workspace get`
    left it empty, short-circuited the test, and the guard passed. It could not tell
    "matches" from "couldn't check". These four cases are the four outcomes it now
    distinguishes.
    """

    def _run_with_multica(self, mode):
        return self.run_script(
            "sync.sh", "--workspace", "Chainlayer",
            path=self._shim("multica", MULTICA_SHIM.format(mode=mode)))

    def test_fails_closed_when_the_check_itself_fails(self):
        r = self._run_with_multica("fail")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("cannot", r.stderr)
        self.assertIn("a guard that cannot check must not pass", r.stderr)
        # It must stop here, not fall through to sync.py.
        self.assertNotIn("Loading schema", r.stderr)

    def test_fails_closed_on_output_it_cannot_parse(self):
        r = self._run_with_multica("garbage")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("could not parse", r.stderr)
        self.assertNotIn("Loading schema", r.stderr)

    def test_still_catches_a_real_mismatch(self):
        r = self._run_with_multica("mismatch")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("active workspace is 'Private'", r.stderr)
        self.assertNotIn("Loading schema", r.stderr)

    def test_a_matching_workspace_is_allowed_through(self):
        """The guard must not become a blanket stop: a match proceeds to sync.py."""
        r = self._run_with_multica("match")
        # Reaching sync.py at all is the proof: it prints this before anything else,
        # and it only runs if the guard let the run through. sync.py then fails on
        # its own terms in this fixture (no schemas/ dir), which is not the guard's
        # business — so assert on the guard's silence, not on sync.py's outcome.
        self.assertIn("Loading schema", r.stderr, r.stdout + r.stderr)
        self.assertNotIn("--workspace is", r.stderr)
        self.assertNotIn("cannot be verified", r.stderr)


class CommitSyncStateTest(ShellGuardTestCase):
    def _head_subject(self):
        return _git("log", "-1", "--format=%s", cwd=self.work).stdout.strip()

    def test_refuses_a_mixed_tree_and_stages_nothing(self):
        self.gut_a_skill()
        self.touch_state()
        r = self.run_script("commit-sync-state.sh")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("skills/demo/SKILL.md", r.stderr)
        self.assertEqual(self._head_subject(), "baseline")
        self.assertEqual(_git("diff", "--cached", "--name-only", cwd=self.work).stdout, "")

    def test_refuses_when_the_out_of_scope_file_is_already_staged(self):
        self.gut_a_skill()
        self.touch_state()
        _git("add", "skills/demo/SKILL.md", cwd=self.work)
        r = self.run_script("commit-sync-state.sh")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertEqual(self._head_subject(), "baseline")

    def test_refuses_an_untracked_stray(self):
        (self.work / "stray.txt").write_text("x", encoding="utf-8")
        self.touch_state()
        r = self.run_script("commit-sync-state.sh")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("stray.txt", r.stderr)

    def test_a_nested_lookalike_does_not_pass_as_the_state_file(self):
        """`sub/.sync-state.json` is not `.sync-state.json` — anchored match."""
        (self.work / "sub").mkdir()
        (self.work / "sub" / ".sync-state.json").write_text("{}", encoding="utf-8")
        r = self.run_script("commit-sync-state.sh")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("sub/.sync-state.json", r.stderr)

    def test_commits_exactly_one_file_when_scoped(self):
        self.touch_state()
        r = self.run_script("commit-sync-state.sh")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._head_subject(), "chore: sync state")
        changed = _git("show", "--stat", "--format=", "--name-only", "HEAD",
                       cwd=self.work).stdout.split()
        self.assertEqual(changed, [".sync-state.json"])

    def test_nothing_to_commit_is_not_an_error(self):
        r = self.run_script("commit-sync-state.sh")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("nothing to commit", r.stdout)
        self.assertEqual(self._head_subject(), "baseline")

    def test_push_moves_the_remote(self):
        self.touch_state()
        r = self.run_script("commit-sync-state.sh", "--push")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        remote_head = _git("rev-parse", "main", cwd=self.remote).stdout.strip()
        self.assertEqual(remote_head, _git("rev-parse", "HEAD", cwd=self.work).stdout.strip())

    def test_unreadable_git_status_fails_closed(self):
        self.touch_state()
        r = self.run_script("commit-sync-state.sh", path=self.shim_path)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("cannot verify the commit scope", r.stderr)
        self.assertEqual(self._head_subject(), "baseline")


class UpdateCheckoutTest(ShellGuardTestCase):
    """Step 1 of both sync autopilots, moved into the repo so it can be tested.

    The idiom it replaces — `[ -d .git ] && git pull --ff-only || git clone …` —
    could not report failure: `||` fires only when the pull fails, `git clone`
    cannot clone into a non-empty directory, and the caller checked nothing. A
    stale checkout was then synced and reported clean (CHA-1211 item 10).
    """

    def setUp(self):
        if not (SCRIPTS / "update-checkout.sh").is_file():
            self.skipTest("scripts/update-checkout.sh not present in this tree")
        super().setUp()

    def _update(self, repo, path=None):
        return self.run_script(
            "update-checkout.sh", "--repo", str(repo), "--remote", str(self.remote),
            cwd=self.tmp, path=path)

    def test_clones_when_the_directory_is_missing(self):
        target = self.tmp / "fresh"
        r = self._update(target)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((target / ".git").is_dir())

    def test_fast_forwards_an_existing_checkout(self):
        (self.work / "new.txt").write_text("x", encoding="utf-8")
        _git("add", "-A", cwd=self.work)
        _git("commit", "-q", "-m", "second", cwd=self.work)
        _git("push", "-q", "origin", "main", cwd=self.work)
        other = self.tmp / "other"
        _git("clone", "-q", str(self.remote), str(other), cwd=self.tmp)
        _git("reset", "-q", "--hard", "HEAD~1", cwd=other)

        r = self._update(other)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(
            _git("rev-parse", "HEAD", cwd=other).stdout,
            _git("rev-parse", "origin/main", cwd=other).stdout,
        )

    def test_refuses_a_non_empty_non_git_directory(self):
        """The case the old one-liner could only fail silently at."""
        junk = self.tmp / "junk"
        junk.mkdir()
        (junk / "x").write_text("x", encoding="utf-8")
        r = self._update(junk)
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("refusing to clone into it", r.stderr)
        self.assertIn("Do NOT run sync.sh", r.stderr)

    def test_a_local_commit_that_blocks_the_pull_is_a_failure(self):
        """`pull --ff-only` says 'Already up to date' while HEAD is not origin/main."""
        (self.work / "local.txt").write_text("x", encoding="utf-8")
        _git("add", "-A", cwd=self.work)
        _git("commit", "-q", "-m", "local only", cwd=self.work)
        r = self._update(self.work)
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("is not origin/main", r.stderr)

    def test_an_unreachable_remote_is_a_failure_not_a_fall_through(self):
        shutil.rmtree(self.remote)
        r = self._update(self.work)
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("CHECKOUT NOT UPDATED", r.stderr)

    def test_a_deleted_remote_branch_is_not_papered_over_by_a_stale_ref(self):
        """H1, and the ordinary half of it: deleting or renaming a default branch.

        The local `origin/main` tracking ref survives on disk, so a swallowed
        fetch error let `rev-parse origin/main` answer from cache and the script
        printed its success line for a checkout it could not verify.
        """
        _git("update-ref", "-d", "refs/heads/main", cwd=self.remote)
        # The stale tracking ref is still there — that is the whole trap.
        self.assertTrue(
            _git("rev-parse", "origin/main", cwd=self.work, check=False).returncode == 0)

        r = self._update(self.work)
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertNotIn("✓", r.stdout)
        # On this fixture the pull catches it first (the branch tracks the ref
        # that was deleted), which is fine — the invariant is that no path
        # reports success. The variant below drives the ls-remote gate itself.

    def test_a_deleted_remote_branch_while_the_pull_still_succeeds(self):
        """H1's first reproduction, isolated: the pull works, `main` is gone.

        The shape is a repo whose default branch was renamed or removed while the
        local checkout tracks something else, so nothing in the pull path notices.
        Pre-fix, the swallowed fetch left a stale `origin/main` that equalled HEAD
        and the script printed `✓ … at origin/main` for a branch that no longer
        existed. `ls-remote --exit-code` is what closes this.
        """
        # A branch that does exist, for the pull to track and succeed against.
        _git("push", "-q", "origin", "main:keep", cwd=self.work)
        _git("config", "branch.main.merge", "refs/heads/keep", cwd=self.work)
        _git("update-ref", "-d", "refs/heads/main", cwd=self.remote)

        pull = _git("pull", "--ff-only", cwd=self.work, check=False)
        self.assertEqual(pull.returncode, 0, "fixture invalid: the pull must succeed")
        self.assertEqual(
            _git("rev-parse", "origin/main", cwd=self.work).stdout,
            _git("rev-parse", "HEAD", cwd=self.work).stdout,
            "fixture invalid: the stale ref must agree with HEAD",
        )

        r = self._update(self.work)
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("has no 'main' branch", r.stderr)
        self.assertNotIn("✓", r.stdout)

    def test_a_failing_fetch_is_not_answered_from_cache(self):
        """H1: the fetch itself fails while the cached ref agrees with HEAD.

        The worst shape, because every other signal looks healthy — the pull
        succeeds, `origin/main` resolves, and it equals HEAD. Only the fetch
        failed, which is precisely the read that makes the comparison meaningful.
        """
        r = self._update(self.work, path=self.fetch_shim_path)
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("cannot be verified against the remote", r.stderr)
        self.assertNotIn("✓", r.stdout)

    def test_it_cannot_wait_for_a_human(self):
        """Item 27: no-prompt is the script's property, not the host's."""
        body = (SCRIPTS / "update-checkout.sh").read_text(encoding="utf-8")
        self.assertIn("GIT_TERMINAL_PROMPT=0", body)
        self.assertIn("BatchMode=yes", body)

    def test_an_unreadable_directory_is_not_treated_as_empty(self):
        """`[ -n "$(ls -A … 2>/dev/null)" ]` read an unreadable dir as an empty one
        and fell through to the clone, which then failed for the wrong reason."""
        if os.geteuid() == 0:
            self.skipTest("running as root: mode 0000 does not deny access")
        blocked = self.tmp / "blocked"
        blocked.mkdir()
        (blocked / "something").write_text("x", encoding="utf-8")
        blocked.chmod(0o000)
        try:
            r = self._update(blocked)
        finally:
            blocked.chmod(0o755)
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("cannot be read", r.stderr)

    def test_an_empty_directory_is_still_safe_to_clone_into(self):
        """The other side of that fix: readable and empty must still clone."""
        empty = self.tmp / "empty"
        empty.mkdir()
        r = self._update(empty)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((empty / ".git").is_dir())

    def test_a_hung_network_call_is_capped(self):
        """A wedged connection becomes a failed run, not a job that looks alive.

        GIT_TERMINAL_PROMPT/BatchMode stop git waiting for a human; this is the
        wall-clock cap that stops it waiting for a host (300s in production).
        """
        env_before = os.environ.get("GIT_NET_TIMEOUT")
        os.environ["GIT_NET_TIMEOUT"] = "1"
        try:
            started = time.monotonic()
            r = self._update(
                self.work,
                path=self._shim("git", GIT_HANG_SHIM.format(git=shutil.which("git"))))
            elapsed = time.monotonic() - started
        finally:
            if env_before is None:
                os.environ.pop("GIT_NET_TIMEOUT", None)
            else:
                os.environ["GIT_NET_TIMEOUT"] = env_before
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertLess(elapsed, 20, "the cap did not fire — git ran to completion")
        self.assertIn("CHECKOUT NOT UPDATED", r.stderr)

    def test_a_dirty_tree_is_reported_but_not_fatal(self):
        (self.work / ".sync-state.json").write_text("{}\n", encoding="utf-8")
        r = self._update(self.work)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("working tree is dirty", r.stdout)
        self.assertIn("commit-sync-state.sh", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""
test_backlog_reconcile_closed.py
=================================
Tests the "reconcile closed-not-merged PRs" fix in scripts/hermes/backlog-reconcile.sh.

Background: a review-fix backlog item (frontmatter `PR: #N`) used to be removed
only when PR #N was MERGED. A CLOSED-but-never-merged PR (abandoned, or whose
changes shipped via a superseding merged PR) therefore left its review-fix item
permanently open — a "phantom item" the nightly implementer keeps re-selecting,
trying to update a dead PR branch forever (this is exactly what happened with
008-fix-pr10 / closed PR #10 whose work shipped via merged PR #9).

The fix makes the no-arg sweep scan BOTH merged and closed auto/* PRs, so a
closed PR's review-fix item is removed, while an OPEN PR's item survives.

These tests drive the real shell script in a throwaway repo with `gh`, `git` and
`flock` stubbed, so no network / no real remote is touched.

Run with:  python3 scripts/test_backlog_reconcile_closed.py   (unittest — no external deps)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

# Path to the script under test (lives in scripts/hermes/, this test in scripts/).
_HERE = Path(__file__).resolve().parent
SCRIPT = _HERE / "hermes" / "backlog-reconcile.sh"
LIB_LOOP = _HERE / "hermes" / "lib-loop.sh"


def _gh_stub() -> str:
    """A `gh` that fakes `gh pr list` for merged / closed / open states.

    - merged  -> PR 9 (the validation tracker that actually shipped)
    - closed  -> PR 10 (never merged; its review-fix item must be removed)
    - open    -> PR 13 (in flight; its review-fix item must SURVIVE)
    All are auto/* heads on the base branch so the select() passes them through.
    """
    return textwrap.dedent(
        """\
        #!/usr/bin/env bash
        args=("$@")
        # find the value of --state
        state=""
        for i in "${!args[@]}"; do
          if [ "${args[$i]}" = "--state" ]; then state="${args[$((i+1))]}"; fi
        done
        case "$state" in
          merged)  printf '9\\n' ;;
          closed)  printf '10\\n' ;;
          open)    printf '13\\n' ;;
          *)       : ;;
        esac
        exit 0
        """
    )

def _git_stub() -> str:
    """A `git` that answers the few queries the script makes, does a REAL `rm` for
    `git rm` (the fake root is not a git repo), and logs every call to $GITLOG."""
    return textwrap.dedent(
        """\
        #!/usr/bin/env bash
        [ -n "${GITLOG:-}" ] && echo "git $*" >> "$GITLOG"
        case "$1" in
          rev-parse)
            case "$2" in
              --abbrev-ref) printf 'autonomous/scaffolding\\n' ;;
              *) /usr/bin/git "$@" ;;
            esac
            ;;
          rm)        shift; while [ $# -gt 0 ]; do case "$1" in -*) :;; *) /bin/rm -f "$1";; esac; shift; done ;;
          status)    printf '\\n' ;;   # empty => clean tree
          fetch)     exit 0 ;;
          merge)     exit 0 ;;
          push)      exit 0 ;;
          add)       exit 0 ;;
          commit)    exit 0 ;;
          *)         /usr/bin/git "$@" ;;
        esac
        exit 0
        """
    )


class ReconcileClosedPrTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._make_repo()
        self._make_bin()

    def tearDown(self):
        self._tmp.cleanup()

    def _make_repo(self):
        # Backlog tree on the (fake) base branch:
        #  - 008-fix-pr10 -> names closed PR #10   => must be REMOVED
        #  - 009-fix-pr13 -> names open   PR #13   => must SURVIVE
        #  - 011-plain    -> feature item, no PR ref => must SURVIVE (untouched)
        (self.root / "backlog").mkdir(parents=True)
        (self.root / "scripts" / "hermes").mkdir(parents=True)
        (self.root / "metrics").mkdir(parents=True)
        (self.root / ".hermes").mkdir(parents=True)

        (self.root / "backlog" / "008-fix-pr10.md").write_text(
            "---\nrank: 0\ntitle: Address review on PR #10\narea: review-fix\n---\n"
            "PR: #10\nResolves-Backlog: 008-fix-pr10\nbody\n"
        )
        (self.root / "backlog" / "009-fix-pr13.md").write_text(
            "---\nrank: 0\ntitle: Address review on PR #13\narea: review-fix\n---\n"
            "PR: #13\nResolves-Backlog: 009-fix-pr13\nbody\n"
        )
        (self.root / "backlog" / "011-plain.md").write_text(
            "---\nrank: 2\ntitle: A normal feature\narea: devex\n---\nbody\n"
        )
        # Copy the real script + lib so we exercise the actual code under test.
        (self.root / "scripts" / "hermes" / "backlog-reconcile.sh").write_text(SCRIPT.read_text())
        (self.root / "scripts" / "hermes" / "lib-loop.sh").write_text(LIB_LOOP.read_text())

    def _make_bin(self):
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "gh").write_text(_gh_stub())
        (self.bin / "git").write_text(_git_stub())
        (self.bin / "flock").write_text("#!/usr/bin/env bash\nexit 0\n")
        for name in ("gh", "git", "flock"):
            os.chmod(self.bin / name, 0o755)

    def _run(self, env_extra=None):
        env = dict(os.environ)
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        env["HOME"] = str(self.root)          # isolate STATE file
        env["LOOP_BASE_BRANCH"] = "autonomous/scaffolding"
        env["DRY_RUN"] = "0"
        env["LOOP_LOCK"] = str(self.root / "git.lock")
        env["GITLOG"] = str(self.root / "gitlog.txt")
        if env_extra:
            env.update(env_extra)
        # Run the script from the fake repo root (ROOT is derived from script path,
        # which we already placed under root/scripts/hermes/).
        return subprocess.run(
            ["bash", str(self.root / "scripts" / "hermes" / "backlog-reconcile.sh")],
            cwd=str(self.root), env=env, capture_output=True, text=True, timeout=60,
        )

    def test_closed_pr_reviewfix_item_removed(self):
        """A CLOSED (not merged) PR's review-fix item must be removed."""
        res = self._run()
        self.assertEqual(res.returncode, 0, f"script failed: {res.stdout}\n{res.stderr}")
        self.assertFalse(
            (self.root / "backlog" / "008-fix-pr10.md").exists(),
            "expected 008-fix-pr10 (closed PR #10) to be reconciled away",
        )
        self.assertIn("008-fix-pr10", res.stderr, "removal should be reported on stderr")

    def test_open_pr_reviewfix_item_survives(self):
        """An OPEN PR's review-fix item must NOT be removed (in flight)."""
        res = self._run()
        self.assertEqual(res.returncode, 0, f"script failed: {res.stdout}\n{res.stderr}")
        self.assertTrue(
            (self.root / "backlog" / "009-fix-pr13.md").exists(),
            "009-fix-pr13 (open PR #13) must survive — it is in flight",
        )

    def test_unrelated_feature_item_survives(self):
        """A feature item with no PR reference must be left alone."""
        res = self._run()
        self.assertEqual(res.returncode, 0, f"script failed: {res.stdout}\n{res.stderr}")
        self.assertTrue(
            (self.root / "backlog" / "011-plain.md").exists(),
            "011-plain (no PR ref) must survive",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

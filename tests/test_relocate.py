#!/usr/bin/env python3
"""Tests for review-core's relocate-findings.py.

Run:  python3 -m unittest discover -s tests -v

Stdlib only. Each test builds a throwaway two-commit git repo (base -> head) so
the script runs against real `git show` / `git diff` output, not mocks.
"""
import importlib.util
import os
import subprocess
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "payload", "skills", "review-core", "scripts",
                      "relocate-findings.py")
spec = importlib.util.spec_from_file_location("relocate", SCRIPT)
relocate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relocate)

BASE_SRC = textwrap.dedent("""\
    class Player {
      void init() {
        controller.initialize();
      }

      void dispose() {
        controller.dispose();
      }
    }
    """)

# head adds a retry() method between init and dispose, shifting dispose down
HEAD_SRC = textwrap.dedent("""\
    class Player {
      void init() {
        controller.initialize();
      }

      Future<void> retry() async {
        hasError = false;
        await controller.initialize();
        await controller.play();
      }

      void dispose() {
        controller.dispose();
      }
    }
    """)


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class RelocateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        sh(d, "git", "init", "-q")
        sh(d, "git", "config", "user.email", "t@t")
        sh(d, "git", "config", "user.name", "t")
        os.makedirs(os.path.join(d, "lib"))
        with open(os.path.join(d, "lib", "player.dart"), "w") as f:
            f.write(BASE_SRC)
        sh(d, "git", "add", ".")
        sh(d, "git", "commit", "-q", "-m", "base")
        cls.base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=d, text=True).strip()
        with open(os.path.join(d, "lib", "player.dart"), "w") as f:
            f.write(HEAD_SRC)
        sh(d, "git", "commit", "-q", "-am", "head")
        cls.head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=d, text=True).strip()
        cls.repo = relocate.Repo(d, cls.head, cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_one(self, **f):
        f.setdefault("file", "lib/player.dart")
        return relocate.relocate(f, self.repo)

    def test_exact_line_kept(self):
        r = self.run_one(line=8, snippet="await controller.initialize();")
        self.assertEqual((r["line"], r["relocation"]), (8, "exact"))
        self.assertNotIn("relocation_delta", r)

    def test_off_by_n_line_is_corrected(self):
        # reviewer counted from the hunk header and landed 3 lines low
        r = self.run_one(line=5, snippet="await controller.initialize();")
        self.assertEqual((r["line"], r["relocation"], r["relocation_delta"]), (8, "moved", 3))

    def test_base_side_line_number_is_corrected(self):
        # dispose() body was line 7 on the base; it is line 13 at head
        r = self.run_one(line=7, snippet="controller.dispose();")
        self.assertEqual((r["line"], r["relocation"]), (13, "moved"))

    def test_multiline_snippet_with_claimed_line_inside_block(self):
        snip = "hasError = false;\nawait controller.initialize();\nawait controller.play();"
        r = self.run_one(line=8, snippet=snip)
        self.assertEqual((r["line"], r["relocation"]), (8, "exact"))

    def test_multiline_snippet_ignores_indentation(self):
        snip = "    hasError   = false;\n        await controller.initialize();"
        r = self.run_one(line=30, snippet=snip)
        self.assertEqual((r["line"], r["relocation"]), (7, "moved"))

    def test_ambiguous_snippet_picks_nearest(self):
        # `controller.initialize();` is a substring of lines 3 and 8
        r = self.run_one(line=9, snippet="controller.initialize();")
        self.assertEqual(r["line"], 8)
        self.assertEqual(r["candidates"], 2)
        r = self.run_one(line=2, snippet="controller.initialize();")
        self.assertEqual(r["line"], 3)

    def test_fuzzy_match_for_paraphrased_snippet(self):
        r = self.run_one(line=1, snippet="await controller.initialise();")
        self.assertEqual((r["line"], r["relocation"]), (8, "fuzzy"))

    def test_snippet_not_in_file(self):
        r = self.run_one(line=8, snippet="controller.setLooping(true);")
        self.assertEqual((r["line"], r["relocation"]), (8, "not_found"))

    def test_short_generic_snippet_confirms_but_never_moves(self):
        r = self.run_one(line=4, snippet="}")
        self.assertEqual((r["line"], r["relocation"]), (4, "exact"))
        # line 5 is blank; a lone `}` must not drag the finding to some other brace
        r = self.run_one(line=5, snippet="}")
        self.assertEqual((r["line"], r["relocation"]), (5, "not_found"))

    def test_no_snippet(self):
        r = self.run_one(line=8)
        self.assertEqual((r["line"], r["relocation"]), (8, "no_snippet"))

    def test_missing_file(self):
        r = self.run_one(file="lib/nope.dart", line=1, snippet="x = 1;")
        self.assertEqual(r["relocation"], "no_file")

    def test_anchor_classification(self):
        added = self.run_one(line=8, snippet="await controller.initialize();")
        self.assertEqual(added["anchor"], "added")
        # line 12 `void dispose() {` is unchanged but within 3 lines of the hunk
        ctx = self.run_one(line=12, snippet="void dispose() {")
        self.assertEqual((ctx["anchor"], ctx["old_line"]), ("context", 6))
        self.assertNotIn("old_line", added)
        # line 1 is more than 3 lines above the hunk that starts at line 6
        out = self.run_one(line=1, snippet="class Player {")
        self.assertEqual(out["anchor"], "outside")

    def test_anchor_uses_corrected_line(self):
        # reported on line 1 (outside); the snippet really lives on added line 9
        r = self.run_one(line=1, snippet="await controller.play();")
        self.assertEqual((r["line"], r["anchor"]), (9, "added"))

    def test_cli_round_trip_preserves_envelope(self):
        import json
        doc = {"mr": 238, "findings": [{"file": "lib/player.dart", "line": 5,
                                        "snippet": "await controller.play();"}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(doc, f)
            path = f.name
        out = path + ".out"
        try:
            rc = relocate.main(["--repo", self.tmp.name, "--ref", self.head,
                                "--base", self.base, "--in", path, "--out", out])
            self.assertEqual(rc, 0)
            with open(out) as fh:
                got = json.load(fh)
            self.assertEqual(got["mr"], 238)
            self.assertEqual(got["findings"][0]["line"], 9)
            self.assertEqual(got["findings"][0]["original_line"], 5)
        finally:
            os.unlink(path)
            if os.path.exists(out):
                os.unlink(out)

    def test_cli_rejects_unknown_ref(self):
        self.assertEqual(relocate.main(["--repo", self.tmp.name, "--ref", "deadbeef"]), 2)


if __name__ == "__main__":
    unittest.main()

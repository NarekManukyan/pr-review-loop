#!/usr/bin/env python3
"""Tests for review-core's build-packets.py and build-gate.py (pure parts).

Run:  python3 -m unittest discover -s tests -v
Stdlib only; a throwaway git repo stands in for a real PR.
"""
import importlib.util
import json
import os
import subprocess
import tempfile
import textwrap
import unittest


def read(path, **kw):
    with open(path, **kw) as fh:
        return fh.read()

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "payload", "skills", "review-core", "scripts")


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


packets = load("packets", "build-packets.py")
gate = load("gate", "build-gate.py")


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class PacketsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        sh(d, "git", "init", "-q")
        sh(d, "git", "config", "user.email", "t@t")
        sh(d, "git", "config", "user.name", "t")
        os.makedirs(os.path.join(d, "lib", "store"))
        with open(os.path.join(d, "AGENTS.md"), "w") as f:
            f.write("# Rules\nEvery catch rethrows or calls IssueTrackingService.\n" * 3)
        with open(os.path.join(d, "CLAUDE.md"), "w") as f:  # generated mirror of AGENTS.md
            f.write("# Rules\nEvery catch rethrows or calls IssueTrackingService.\n" * 3)
        with open(os.path.join(d, "lib", "store", "cart_store.dart"), "w") as f:
            f.write("class CartStore {\n  int count = 0;\n}\n")
        with open(os.path.join(d, "lib", "store", "user_store.dart"), "w") as f:
            f.write("class UserStore {}\n")
        sh(d, "git", "add", ".")
        sh(d, "git", "commit", "-q", "-m", "base")
        cls.base = sh(d, "git", "rev-parse", "HEAD")
        with open(os.path.join(d, "lib", "store", "cart_store.dart"), "w") as f:
            f.write("class CartStore {\n  int count = 0;\n  void add() => count++;\n}\n")
        with open(os.path.join(d, "lib", "store", "promo_store.dart"), "w") as f:
            f.write("class PromoStore {}\n")
        with open(os.path.join(d, "lib", "api.g.dart"), "w") as f:
            f.write("// generated\n")
        sh(d, "git", "add", ".")
        sh(d, "git", "commit", "-q", "-m", "head")
        cls.head = sh(d, "git", "rev-parse", "HEAD")
        cls.out = os.path.join(d, "_packets")
        packets.main(["--repo", d, "--base", cls.base, "--head", cls.head, "--out", cls.out,
                      "--pack", "lenses/_base-flutter.md"])
        cls.common = "".join(read(os.path.join(cls.out, f))
                             for f in sorted(os.listdir(cls.out)) if f.startswith("common-"))
        cls.manifest = json.loads(read(os.path.join(cls.out, "manifest.json")))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_annotated_view_marks_added_lines_with_head_numbers(self):
        self.assertIn("    3 + ", self.common)
        self.assertIn("void add() => count++;", self.common)
        self.assertIn("    1   class CartStore {", self.common)

    def test_generated_files_are_skipped_and_listed(self):
        self.assertEqual([x["path"] for x in self.manifest["skipped"]], ["lib/api.g.dart"])
        self.assertNotIn("// generated", self.common)

    def test_mirrored_claude_md_is_not_repeated(self):
        self.assertEqual(self.common.count("Every catch rethrows"), 3)
        self.assertIn("mirrors `AGENTS.md`", self.common)

    def test_likely_reads_flag_unwired_symbol_and_siblings(self):
        self.assertIn("`PromoStore` — no use outside this diff", self.common)
        self.assertIn("siblings: `lib/store/user_store.dart`", self.common)

    def test_seat_slices_carry_only_owned_lenses(self):
        b = read(os.path.join(self.out, "seat-B.md"))
        e = read(os.path.join(self.out, "seat-E.md"))
        self.assertIn("## Reviewer B ", b)
        self.assertIn("## U1 ", b)
        self.assertNotIn("## U5 ", b)
        self.assertIn("## U5 ", e)
        self.assertNotIn("## Reviewer B ", e)
        # pack sections are routed by their (maps …; X) tag
        self.assertIn("Correctness patterns", b)
        self.assertNotIn("Correctness patterns", e)

    def test_chunks_stay_under_read_cap(self):
        for f in os.listdir(self.out):
            if f.startswith("common-"):
                self.assertLessEqual(os.path.getsize(os.path.join(self.out, f)), packets.CHUNK_BYTES + 2000)


class GateTest(unittest.TestCase):
    def test_flutter_analyzer_errors_become_p0_findings(self):
        out = textwrap.dedent("""\
            Analyzing app...
              error • Undefined name 'foo' • lib/a.dart:3:5 • undefined_identifier
            warning • Unused import • lib/b.dart:1:8 • unused_import
               info • Prefer const • lib/c.dart:2:1 • prefer_const_constructors
            3 issues found.
            """)
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "lib"))
            with open(os.path.join(d, "lib", "a.dart"), "w") as f:
                f.write("x\ny\n  print(foo);\n")
            findings, errors, warnings = gate.analyzer_findings(out, d)
        self.assertEqual((errors, warnings), (1, 1))
        self.assertEqual(findings[0]["file"], "lib/a.dart")
        self.assertEqual(findings[0]["line"], 3)
        self.assertEqual(findings[0]["severity"], "P0")
        self.assertEqual(findings[0]["snippet"], "print(foo);")

    def test_related_tests_maps_lib_to_test_mirror(self):
        with tempfile.TemporaryDirectory() as d:
            for p in ("lib/x/cart.dart", "test/x/cart_test.dart", "test/y/other_test.dart"):
                os.makedirs(os.path.dirname(os.path.join(d, p)), exist_ok=True)
                open(os.path.join(d, p), "w").close()
            got = gate.related_tests(d, ["lib/x/cart.dart", "test/y/other_test.dart", "README.md"])
        self.assertEqual(got, ["test/x/cart_test.dart", "test/y/other_test.dart"])

    def test_stack_detection(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(gate.stack_of(d), "unknown")
            with open(os.path.join(d, "go.mod"), "w") as f:
                f.write("module x\n")
            self.assertEqual(gate.stack_of(d), "go")


if __name__ == "__main__":
    unittest.main()

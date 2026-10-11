#!/usr/bin/env python3
"""Reviewer D as a script: build + analyze + format + targeted tests, zero tokens.

The agent version spent 22-41 turns per review running commands and reading exit
codes. That is deterministic work, so it is code now. Run it in the shell's
background while the reviewer seats work; it writes one JSON build record.

  build-gate.py --repo <dir> --head <sha> --base <sha> --out build.json \
      [--pr-url <url>] [--scratch <dir>] [--timeout 1500] [--keep]

Gates, in order of preference:
  1. `.review-memory/config.json` -> "build_gate": [{"name": "...", "cmd": "..."}]
     (the repo's own list; `{flutter}` / `{dart}` expand to the pinned SDK)
  2. stack defaults (Flutter/Dart, Go, Node/TS, Python), using the pinned
     toolchain (.fvmrc, .tool-versions, go.mod) by absolute path
The PR's own pipeline (gh pr checks / glab ci status) is recorded alongside.

Output record (same shape Reviewer D returned):
  {"reviewer":"D","build":{"compiles":true|false|null,"analyzer_errors":N,
   "analyzer_warnings":N,"sdk":"…","ci_gates":[…],"pipeline":"passed|failed|pending|n/a",
   "tool":"build-gate.py","notes":"…"},"gates":[{"name","cmd","exit","seconds","tail"}],
   "findings":[{file,line,severity,reviewer:"D",category:"Build & Analyze",title,body,snippet}]}
"compiles" is null when the toolchain or dependency install could not run — an
unverified build, which the front-end treats as a blocker. Exit 0 always (the
record carries the result); 2 on bad invocation.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time


def read(path, **kw):
    with open(path, **kw) as fh:
        return fh.read()

TAIL = 40


def sh(cmd, cwd, timeout, env=None):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True,
                           timeout=timeout, env=env)
        out, code = (r.stdout + r.stderr), r.returncode
    except subprocess.TimeoutExpired as e:
        out, code = ((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes)
                     else (e.stdout or "")) + "\n[timed out]", 124
    return code, out, round(time.time() - t0, 1)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout


def pinned_flutter(wt):
    pin = None
    for f in (".fvmrc", ".fvm/fvm_config.json"):
        p = os.path.join(wt, f)
        if os.path.isfile(p):
            try:
                d = json.loads(read(p))
                pin = d.get("flutter") or d.get("flutterSdkVersion")
            except (json.JSONDecodeError, OSError):
                pass
            if pin:
                break
    env_root = os.environ.get("FLUTTER_ROOT")
    candidates = []
    if pin:
        candidates.append(os.path.expanduser(f"~/fvm/versions/{pin}"))
    if env_root:
        candidates.append(env_root)
    candidates += sorted(glob.glob(os.path.expanduser("~/fvm/versions/*")), reverse=True)
    for root in candidates:
        if os.path.isfile(os.path.join(root, "bin", "flutter")):
            note = "" if (not pin or root.endswith(pin)) else f" (pin {pin} not installed)"
            return root, pin, note
    return None, pin, f"no Flutter SDK found (pin {pin})"


def stack_of(wt):
    if os.path.isfile(os.path.join(wt, "pubspec.yaml")):
        txt = read(os.path.join(wt, "pubspec.yaml"))
        return "flutter" if re.search(r"^\s*flutter:\s*$", txt, re.M) or "sdk: flutter" in txt else "dart"
    if os.path.isfile(os.path.join(wt, "go.mod")):
        return "go"
    if os.path.isfile(os.path.join(wt, "package.json")):
        return "node"
    if any(os.path.isfile(os.path.join(wt, f)) for f in ("pyproject.toml", "setup.py", "requirements.txt")):
        return "python"
    return "unknown"


def related_tests(wt, changed):
    tests = set()
    for p in changed:
        if not os.path.isfile(os.path.join(wt, p)):
            continue
        if re.search(r"(_test\.dart|_test\.go|\.test\.[jt]sx?|\.spec\.[jt]sx?|test_.*\.py)$", p):
            tests.add(p)
            continue
        if p.startswith("lib/") and p.endswith(".dart"):
            t = "test/" + p[4:-5] + "_test.dart"
            if os.path.isfile(os.path.join(wt, t)):
                tests.add(t)
    return sorted(tests)


def default_gates(stack, wt, changed, sdk):
    dart_files = [p for p in changed if p.endswith(".dart") and os.path.isfile(os.path.join(wt, p))
                  and not re.search(r"\.(g|freezed|gr|config|mocks|tailor)\.dart$", p)]
    if stack in ("flutter", "dart"):
        tool = f"{sdk}/bin/flutter" if stack == "flutter" else f"{sdk}/bin/dart"
        dart = f"{sdk}/bin/dart"
        pub = read(os.path.join(wt, "pubspec.yaml"))
        gates = [{"name": "pub get", "cmd": f"{tool} pub get", "install": True}]
        # The repo's own codegen entry point wins: a melos `build` script knows the
        # order (translations -> packages -> app) that a bare build_runner misses.
        if "melos" in pub and re.search(r"^\s+build:\s*$", pub, re.M):
            gates.append({"name": "codegen (melos run build)", "install": True,
                          "cmd": f"{dart} run melos run build --no-select"})
        elif "build_runner" in pub:
            gates.append({"name": "codegen", "cmd": f"{dart} run build_runner build -d", "install": True})
        gates.append({"name": "analyze", "analyzer": True,
                      "cmd": f"{tool} analyze --no-fatal-infos --no-fatal-warnings"})
        if dart_files:
            gates.append({"name": "format", "cmd": f"{dart} format --output=none --set-exit-if-changed "
                                                    + " ".join(f"'{p}'" for p in dart_files)})
        tests = related_tests(wt, changed)
        if tests:
            gates.append({"name": f"tests ({len(tests)} files)",
                          "cmd": f"{tool} test " + " ".join(f"'{t}'" for t in tests)})
        return gates
    if stack == "go":
        tags = sorted(set(re.findall(r"^//go:build\s+(\w+)", git(wt, "grep", "-h", "^//go:build"), re.M)))
        gates = [{"name": "go mod download", "cmd": "go mod download", "install": True},
                 {"name": "gofmt", "cmd": 'test -z "$(gofmt -l .)" || (gofmt -l .; exit 1)'},
                 {"name": "go vet", "cmd": "go vet ./...", "analyzer": True}]
        for t in tags:
            gates.append({"name": f"go vet -tags={t}", "cmd": f"go vet -tags={t} ./..."})
            gates.append({"name": f"compile tests -tags={t}", "cmd": f"go test -tags={t} -run=^$ ./..."})
        if glob.glob(os.path.join(wt, ".golangci.y*ml")) and shutil.which("golangci-lint"):
            gates.append({"name": "golangci-lint", "cmd": "golangci-lint run"})
        return gates
    if stack == "node":
        lock = "npm ci" if os.path.isfile(os.path.join(wt, "package-lock.json")) else \
               "pnpm install --frozen-lockfile" if os.path.isfile(os.path.join(wt, "pnpm-lock.yaml")) else \
               "yarn install --frozen-lockfile"
        gates = [{"name": "install", "cmd": lock, "install": True}]
        if os.path.isfile(os.path.join(wt, "tsconfig.json")):
            gates.append({"name": "tsc", "cmd": "npx --no-install tsc --noEmit", "analyzer": True})
        pkg = json.loads(read(os.path.join(wt, "package.json")))
        if "lint" in pkg.get("scripts", {}):
            gates.append({"name": "lint", "cmd": "npm run -s lint"})
        return gates
    if stack == "python":
        gates = []
        if shutil.which("ruff"):
            gates.append({"name": "ruff", "cmd": "ruff check .", "analyzer": True})
        return gates
    return []


def pipeline_status(pr_url):
    if not pr_url:
        return "n/a", ""
    if "github.com" in pr_url and shutil.which("gh"):
        r = subprocess.run(["gh", "pr", "checks", pr_url, "--json", "name,bucket"],
                           capture_output=True, text=True)
        try:
            checks = json.loads(r.stdout)
        except json.JSONDecodeError:
            return "n/a", r.stderr.strip()[:200]
        buckets = {c.get("bucket") for c in checks}
        failed = [c["name"] for c in checks if c.get("bucket") == "fail"]
        if failed:
            return "failed", "failing: " + ", ".join(failed[:5])
        if "pending" in buckets:
            return "pending", ""
        return ("passed" if checks else "n/a"), f"{len(checks)} checks"
    if shutil.which("glab"):
        r = subprocess.run(["glab", "ci", "status", "--compact"], capture_output=True, text=True)
        text = (r.stdout + r.stderr).lower()
        if "failed" in text:
            return "failed", ""
        if "running" in text or "pending" in text:
            return "pending", ""
        if "success" in text or "passed" in text:
            return "passed", ""
    return "n/a", ""


def analyzer_findings(out, wt):
    findings, errors, warnings = [], 0, 0
    for line in out.splitlines():
        m = re.match(r"\s*(error|warning|info)\s+[•-]\s+(.*?)\s+[•-]\s+([^:]+):(\d+):\d+\s+[•-]\s+(\S+)", line)
        if not m:
            continue
        level, msg, path, ln, code = m.groups()
        if level == "error":
            errors += 1
            src = ""
            try:
                src = read(os.path.join(wt, path)).splitlines()[int(ln) - 1].strip()
            except (OSError, IndexError):
                pass
            findings.append({"file": path, "line": int(ln), "severity": "P0", "reviewer": "D",
                             "category": "Build & Analyze", "title": f"Analyzer error: {code}",
                             "body": msg, "snippet": src})
        elif level == "warning":
            warnings += 1
    if not findings:  # go vet / tsc style: path:line:col: message
        for line in out.splitlines():
            m = re.match(r"^\.?/?([\w./-]+\.\w+):(\d+):\d+:?\s+(?:error\s+)?(.*)$", line)
            if m and "warning" not in line.lower():
                errors += 1
                findings.append({"file": m.group(1), "line": int(m.group(2)), "severity": "P0",
                                 "reviewer": "D", "category": "Build & Analyze",
                                 "title": "Compile/analyze error", "body": m.group(3)[:300], "snippet": ""})
    return findings[:25], errors, warnings


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pr-url")
    ap.add_argument("--scratch", default=os.environ.get("REVIEW_SCRATCH", "/tmp"))
    ap.add_argument("--timeout", type=int, default=1500, help="per-gate timeout, seconds")
    ap.add_argument("--keep", action="store_true", help="keep the worktree (debugging)")
    a = ap.parse_args(argv)
    if subprocess.run(["git", "-C", a.repo, "rev-parse", "--verify", "--quiet",
                       f"{a.head}^{{commit}}"], capture_output=True).returncode != 0:
        print(f"build-gate: unknown head {a.head}", file=sys.stderr)
        return 2

    t0 = time.time()
    wt = os.path.join(a.scratch, f"build-gate-{a.head[:10]}-{os.getpid()}")
    rec = {"reviewer": "D", "gates": [], "findings": [],
           "build": {"compiles": None, "analyzer_errors": 0, "analyzer_warnings": 0, "sdk": "",
                     "ci_gates": [], "pipeline": "n/a", "tool": "build-gate.py", "notes": ""}}
    b = rec["build"]
    b["pipeline"], pnote = pipeline_status(a.pr_url)
    notes = [pnote] if pnote else []
    try:
        subprocess.run(["git", "-C", a.repo, "worktree", "add", "--detach", "-q", wt, a.head],
                       check=True, capture_output=True)
        changed = [l for l in git(a.repo, "diff", "--name-only", "--no-renames", a.base, a.head).splitlines() if l]
        stack = stack_of(wt)
        env = dict(os.environ)
        sdk = ""
        if stack in ("flutter", "dart"):
            sdk, pin, note = pinned_flutter(wt)
            if note:
                notes.append(note)
            if not sdk:
                raise RuntimeError(f"toolchain unresolved: {note}")
            ver = sh(f"{sdk}/bin/flutter --version --machine", wt, 120)[1]
            m = re.search(r'"frameworkVersion":\s*"([^"]+)"', ver)
            b["sdk"] = f"{sdk} ({m.group(1) if m else '?'})"
            env["PATH"] = f"{sdk}/bin:" + env.get("PATH", "")
        cfg = {}
        cpath = os.path.join(wt, ".review-memory", "config.json")
        if os.path.isfile(cpath):
            try:
                cfg = json.loads(read(cpath))
            except json.JSONDecodeError:
                notes.append("config.json unreadable — using stack defaults")
        gates = cfg.get("build_gate") or default_gates(stack, wt, changed, sdk)
        if not gates:
            raise RuntimeError(f"no gates for stack '{stack}' — add build_gate to .review-memory/config.json")
        for g in gates:
            cmd = g["cmd"].replace("{flutter}", f"{sdk}/bin/flutter").replace("{dart}", f"{sdk}/bin/dart")
            code, out, secs = sh(cmd, wt, a.timeout, env)
            tail = "\n".join(out.strip().splitlines()[-TAIL:])
            rec["gates"].append({"name": g["name"], "cmd": cmd, "exit": code, "seconds": secs, "tail": tail if code else ""})
            b["ci_gates"].append(g["name"])
            if g.get("install") and code != 0:
                raise RuntimeError(f"'{g['name']}' failed (exit {code}) — dependencies did not install")
            if g.get("analyzer"):
                if re.search(r"Target of URI doesn't exist: 'package:flutter/", out):
                    raise RuntimeError("analyzer could not resolve package:flutter — install did not work")
                f, e, w = analyzer_findings(out, wt)
                b["analyzer_errors"], b["analyzer_warnings"] = e, w
                rec["findings"] += f
        failed = [g for g in rec["gates"] if g["exit"] != 0]
        b["compiles"] = b["analyzer_errors"] == 0 and not any(g["name"] == "analyze" for g in failed)
        for g in failed:
            if g["name"] == "analyze":
                continue
            rec["findings"].append({"file": "", "line": 0, "severity": "P1", "reviewer": "D",
                                    "category": "Build & Analyze", "title": f"Gate failed: {g['name']}",
                                    "body": f"`{g['cmd']}` exited {g['exit']}.\n\n{g['tail'][-1500:]}",
                                    "snippet": ""})
    except (RuntimeError, subprocess.CalledProcessError) as e:
        b["compiles"] = None
        msg = str(e) if isinstance(e, RuntimeError) else f"worktree add failed: {e.stderr.decode()[:200]}"
        notes.append(msg)
        rec["findings"].append({"file": "", "line": 0, "severity": "P1", "reviewer": "D",
                                "category": "Build & Analyze", "title": "Build unverified",
                                "body": msg, "snippet": ""})
    finally:
        if os.path.isdir(wt) and not a.keep:
            subprocess.run(["git", "-C", a.repo, "worktree", "remove", "--force", wt], capture_output=True)
            subprocess.run(["git", "-C", a.repo, "worktree", "prune"], capture_output=True)
    if b["pipeline"] == "failed":
        rec["findings"].append({"file": "", "line": 0, "severity": "P1", "reviewer": "D",
                                "category": "Build & Analyze", "title": "PR pipeline is red",
                                "body": pnote, "snippet": ""})
    b["notes"] = "; ".join(n for n in notes if n)
    rec["seconds"] = round(time.time() - t0, 1)
    with open(a.out, "w") as f:
        json.dump(rec, f, indent=1)
    print(f"build-gate: compiles={b['compiles']} errors={b['analyzer_errors']} "
          f"warnings={b['analyzer_warnings']} pipeline={b['pipeline']} "
          f"gates={len(rec['gates'])} in {rec['seconds']}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

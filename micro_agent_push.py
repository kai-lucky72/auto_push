#!/usr/bin/env python3
"""
micro_commit_agent.py
Periodically appends a small, meaningful entry to a file (e.g. TODO.md or CHANGELOG.md),
commits the change to the local git repo, and optionally pushes to remote.

Usage examples:
  python micro_commit_agent.py                    # defaults: current repo, file=TODO.md, interval=3600s, push enabled
  python micro_commit_agent.py --repo /path/to/repo --file docs/mini-log.md --interval 1800 --no-push
  python micro_commit_agent.py --file .github/notes.md --interval 900 --randomize

Stops with Ctrl+C.
"""

from __future__ import annotations
import argparse
import os
import subprocess
import sys
import time
import signal
from datetime import datetime
import random
import textwrap
import shlex

# ---------- Helpers ----------
def run_cmd(args, cwd=None, check=True):
    """Run command (list) and return CompletedProcess. Raises RuntimeError on non-zero if check."""
    res = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}\nstdout: {res.stdout}\nstderr: {res.stderr}")
    return res

def is_git_repo(path: str) -> bool:
    try:
        res = run_cmd(["git", "rev-parse", "--is-inside-work-tree"], cwd=path)
        return res.stdout.strip() == "true"
    except Exception:
        return False

def current_branch(path: str) -> str:
    res = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    return res.stdout.strip()

def ensure_dir_for_file(path: str):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)

def append_entry(path: str, entry: str):
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)
        if not entry.endswith("\n"):
            f.write("\n")

def git_stage_and_commit(repo: str, file_path: str, message: str, no_verify: bool=True) -> bool:
    try:
        run_cmd(["git", "add", "--", file_path], cwd=repo)
        commit_cmd = ["git", "commit", "-m", message]
        if no_verify:
            commit_cmd.insert(2, "--no-verify")
        run_cmd(commit_cmd, cwd=repo)
        return True
    except RuntimeError as e:
        # No changes or commit failed
        return False

def git_push(repo: str) -> bool:
    try:
        run_cmd(["git", "push"], cwd=repo)
        return True
    except RuntimeError:
        return False

# ---------- Meaningful small entry generator ----------
DEFAULT_TEMPLATES = [
    "TODO: Add a short example for the API (created {ts}).",
    "NOTE: Quick optimization idea documented — revisit later ({ts}).",
    "DOC: Minor README tweak suggested ({ts}).",
    "TASK: Write unit test for recently added util function ({ts}).",
    "LOG: Small refactor done locally; details in code comments ({ts}).",
    "CHORE: Update dependency checklist in docs ({ts}).",
    "IDEA: Possible feature — add bulk import endpoint ({ts}).",
]

def generate_entry(template_pool: list[str], prefix: str | None = None) -> str:
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    templ = random.choice(template_pool)
    line = templ.format(ts=ts)
    if prefix:
        return f"{prefix} {line}\n"
    return f"- {line}\n"

# ---------- Main ----------
def main():
    parser = argparse.ArgumentParser(description="Append useful micro-entries, commit, repeat.")
    parser.add_argument("--repo", "-r", default=".", help="Path to git repo (default: current dir).")
    parser.add_argument("--file", "-f", default="TODO.md", help="Target file to append entries (default: TODO.md).")
    parser.add_argument("--interval", "-i", type=int, default=3600, help="Seconds between commits (default 3600).")
    parser.add_argument("--push/--no-push", dest="push", default=True, help="Whether to git push after commit (default: push).")
    parser.add_argument("--branch", "-b", default=None, help="Optional branch to switch/create before committing.")
    parser.add_argument("--message", "-m", default="chore: micro update", help="Base commit message (timestamp appended).")
    parser.add_argument("--randomize", action="store_true", help="Add +/-20% jitter to interval to look organic.")
    parser.add_argument("--templates-file", help="Path to file containing custom templates (one per line).")
    parser.add_argument("--prefix", help="Optional prefix for each appended line (e.g., 'AUTO').")
    parser.add_argument("--no-verify", dest="no_verify", action="store_true", help="Pass --no-verify to git commit to skip hooks.")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    target_file = os.path.join(repo, args.file)

    # Basic validations
    if not is_git_repo(repo):
        print("Error: the provided path is not a git repository or git is not available.", file=sys.stderr)
        sys.exit(1)

    # Optionally load templates
    templates = DEFAULT_TEMPLATES[:]
    if args.templates_file:
        try:
            with open(args.templates_file, "r", encoding="utf-8") as tf:
                lines = [l.strip() for l in tf.readlines() if l.strip()]
                if lines:
                    templates = lines
        except Exception as e:
            print(f"Warning: could not load templates from {args.templates_file}: {e}")

    ensure_dir_for_file(target_file)
    # create file if missing and add a header
    if not os.path.exists(target_file):
        header = textwrap.dedent(
            "# Micro updates\n\nThis file collects tiny, useful notes and TODOs created automatically.\n\n"
        )
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(header)

    # Branch handling
    if args.branch:
        # try checkout existing branch; if fails, create it
        try:
            run_cmd(["git", "checkout", args.branch], cwd=repo)
        except RuntimeError:
            run_cmd(["git", "checkout", "-b", args.branch], cwd=repo)

    # Inform user
    print(f"Repository: {repo}")
    print(f"Target file: {target_file}")
    print(f"Interval: {args.interval}s  Push: {args.push}  Branch: {args.branch or '(current)'}")
    print("Press Ctrl+C to stop.\n")

    stop_signal_received = False

    def _handle_sigint(signum, frame):
        nonlocal stop_signal_received
        stop_signal_received = True
        print("\nStopping — finishing current loop then exiting...")

    signal.signal(signal.SIGINT, _handle_sigint)
    rng = random.Random()

    while not stop_signal_received:
        try:
            # compute next interval (with optional jitter)
            base = args.interval
            if args.randomize:
                jitter = base * 0.2
                delay = base + rng.uniform(-jitter, jitter)
                delay = max(10, delay)
            else:
                delay = base

            entry = generate_entry(templates, prefix=args.prefix)
            append_entry(target_file, entry)

            # commit message includes timestamp
            ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            full_msg = f"{args.message} — {ts}"

            committed = git_stage_and_commit(repo, args.file, full_msg, no_verify=args.no_verify)
            if committed:
                now = datetime.now().isoformat(sep=" ", timespec="seconds")
                print(f"[{now}] Committed: {full_msg}")
                if args.push:
                    pushed = git_push(repo)
                    if pushed:
                        print(f"[{now}] Pushed to remote.")
                    else:
                        print(f"[{now}] Push failed (check remote/auth).")
            else:
                print("No commit created (no change detected).")

            # sleep but wake earlier if Ctrl+C
            slept = 0.0
            while slept < delay and not stop_signal_received:
                time.sleep(min(1.0, delay - slept))
                slept += 1.0

        except Exception as e:
            print(f"Error in loop: {e}", file=sys.stderr)
            # small backoff before continuing
            for _ in range(5):
                if stop_signal_received:
                    break
                time.sleep(1)

    print("Exited cleanly.")

if __name__ == "__main__":
    main()

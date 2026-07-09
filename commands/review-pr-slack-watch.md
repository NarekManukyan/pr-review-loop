---
description: One poll cycle of the review-pr-slack watcher — scan a Slack channel, review new PRs and requested next-rounds, encode state as reactions. Wrap in /loop to run continuously.
argument-hint: "#channel"
---

Run **one** watch cycle over the Slack channel: $ARGUMENTS

This is the unattended driver for the `review-pr-slack` skill. Reactions on each PR
message are the state machine — no external database:

- no state emoji → not yet reviewed
- 👀 `eyes` → review in progress
- ✅ `white_check_mark` / 🔧 `wrench` → reviewed (verdict posted)

**Dry run:** if `$ARGUMENTS` contains `--dry-run`, scan and print the plan (which
messages would be reviewed / picked up as next rounds) but **review nothing, set no
reactions, post nothing**. Use it to validate detection on your channel before
turning the loop on.

**Config:** read per-repo/team settings from review memory (run from the repo the
PRs belong to):
```bash
python3 ~/.claude/skills/review-memory/scripts/memory.py config .
```
Use `cycle_cap` as the per-cycle cap, `watch_channel` as the default channel if none
is passed, and the `reactions` map for the state emojis (falls back to
eyes / white_check_mark / wrench).

## Steps

1. **Scan the channel.**
   ```bash
   ~/.claude/skills/slack-send/scripts/watch.sh "$ARGUMENTS"
   ```
   This returns a JSON array of top-level messages that contain a GitLab MR /
   GitHub PR URL, each with `ts`, `user`, `urls`, `state`, `reply_count`,
   `last_reply_ts`.

   **On a Slack auth failure** (`NO_TOKEN` exit 3, or `SCOPE_ERROR` exit 4):
   handle it per the review-pr-slack skill's "Slack auth errors — prompt, don't
   dead-end" section. Run **by hand** → `AskUserQuestion` offering to reconnect
   (run `~/.claude/skills/slack-send/install.sh`) then retry. Inside **`/loop`** →
   report once and **stop the loop** (don't repeat the failure every cycle); tell
   the user to re-auth and re-run `/loop`.

2. **Pick work (cap at 3 per cycle** so a cycle can't run away; the next cycle
   continues):
   - **New PR** — `state == "new"`. Review it fresh (round 1).
   - **Next round** — `state == "reviewed"` AND `last_reply_ts` is newer than the
     verdict AND authored by the PR author. Call `slack_read_thread` on that
     message; only proceed if the author is asking for a re-review / says it's
     ready. If the reply is just discussion, skip it.
   - Skip `state == "in_progress"` (already being handled) unless clearly stale
     (hours old with no verdict — then re-run it).
   - Nothing actionable → say "nothing to review this cycle" and stop.

3. **For each picked item, run the `review-pr-slack` skill** on that message's PR
   URLs, using that message as the Slack anchor (its channel + `ts` are the
   `thread_ts` for the verdict reply and the target for reactions):
   - Set 👀 at the start: `react.sh state <channel> <ts> eyes`.
   - Run the full panel → HTML report → verdict message **as a reply in that
     message's thread** → upload the report there.
   - For a next round, feed the thread replies in as `thread-context.md` (the
     skill's re-review path) and let review memory recall apply.
   - Set the verdict reaction at the end: `react.sh state <channel> <ts>
     white_check_mark` if every MR is approved with no P0/P1, else `wrench`.

4. **Unattended-run rules:** the `/loop` invocation is the standing authorization,
   so **skip the interactive send-confirmation** this skill normally requires —
   but keep every other hard rule: no GitLab/GitHub comments, skip generated
   files, FACT-vs-ASSUMPTION discipline, record review memory after each review.

Report a one-line summary per item handled (PR, round, verdict emoji), or
"nothing to review this cycle."

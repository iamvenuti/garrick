---
name: update
description: >
  Bring the workspace up to a newer Garrick without losing what the user
  changed, extras included, and merge the files an update leaves beside
  theirs as `.new`, and move the user's own text out of Garrick's
  instruction files into the local file beside each. Use when the user says
  "update Garrick", "update the workspace", "what would an update change?",
  "is my Garrick up to date?", "is there a newer Garrick?", "tell me when a
  new Garrick is out", "merge the update", "finish the update", or "split my
  rules", and when `System/tools/check.py` or the status page says a newer
  Garrick is out, an update waits to be merged, or an instruction file
  differs from what Garrick shipped.
---

# Update

A workspace is a copy of Garrick taken on the day it was installed. A newer
Garrick reaches it only through this skill. The newer Garrick does the work:
its `install.py --update` compares every file it would write with the one
here, replaces only what is still as some Garrick wrote it, and puts its
version of anything the user changed beside it as `<name>.new`. It does the
same for the extras the workspace has copied in (the status page, the
scheduled jobs, desk), then rebuilds the Mac app, refreshes the Obsidian
plugin and points the `desk` link where they need it. This skill runs that
command, says what it found, and merges the `.new` files with the user.

Garrick's instruction files, `System/rules.md` and every `AGENTS.md`, are
different: they stay exactly as Garrick ships them, and the workspace's own
rules and routing live in the local file beside each, `System/rules.local.md`
and `AGENTS.local.md`, which no update touches. One the user changed gets no
`.new`; the update's split moves their text out and puts Garrick's back.

`System/tools/release.py` is the one tool this skill runs that reaches the network. It
asks GitHub for the newest release, and `update` downloads that release into
a temporary folder outside the workspace and runs its update from there. Run
it only when the user asks for an update or whether one exists. It sends one
request with a User-Agent naming Garrick and the release, and nothing from
the workspace.

## Where things are

| What | Path |
|---|---|
| Which Garrick this is, and every file it wrote with its fingerprint | `System/garrick-version.json` |
| Say it in one sentence, with a newer release if GitHub last named one | `python3 System/tools/check.py --version` |
| Ask GitHub for the newest release, at most once a day | `python3 System/tools/release.py latest` |
| Download it and say what an update would change | `python3 System/tools/release.py update` |
| The release notice, on or off | `System/garrick-settings.json`, `"release-notice"` |
| Each zone's colour and icon, and how a thread opens | `System/garrick-settings.json`, `"zones"`, `"launchers"`, `"default"` |
| What GitHub last said, never committed | `System/generated/garrick-release.json` |
| A file waiting to be merged | `<the file>.new`, beside it |
| The user's own rules and routing, never touched by an update | `System/rules.local.md`, and `AGENTS.local.md` beside an `AGENTS.md` |
| The user's own answers, never touched by an update | `System/context.md` |

## "Is my Garrick up to date?"

Run `python3 System/tools/release.py latest` and say its line back. Spoken:
"Garrick 0.16.0 is out; you run 0.15.2. Update?" or "You're on the newest,
0.15.2." It asks GitHub at most once a day; `--now` asks again. If it could
not ask, say so in one sentence and stop. A workspace with no `release.py`
is older than the tool: say where to look, the repository's Releases page,
and offer the steps below with a Garrick the user downloads.

## "Tell me when a new Garrick is out"

The release notice is off until the user switches it on. Ask once, if they
have not said: "Tell me when a new Garrick is out? It asks GitHub once a day
and sends nothing about your workspace." On a yes, write
`{"release-notice": true}` into `System/garrick-settings.json`, keeping any
other key there, and commit it alone in the workspace's own repository:
`git add -- System/garrick-settings.json && git commit -m "Settings: release notice on"`.
On "stop telling me", set it to `false` the same way. The status page then
names a newer release under Needs attention, and `check.py --version` adds
the same line.

## "Update Garrick"

1. **Ask what would change**, from the workspace's top folder:
   ```sh
   python3 System/tools/release.py update
   ```
   It downloads the newest release, runs that release's update as a report,
   and changes nothing. Note the release its first line names. Say the result
   back in short. Spoken: "Garrick 0.16.0 has 6 newer files, 1 you changed
   that needs a merge, and it rebuilds the app. Update?" Written: the report
   as printed. If it says up to date, say so and stop.
2. **Say what each group means** only when the user asks or when it is not
   obvious:
   - *Replace*: files Garrick wrote that the user never changed. Safe.
   - *Add*: new in this Garrick, or missing from an extra the user has.
   - *Merge*: changed on both sides. Garrick's version goes beside the file
     as `.new`; the file itself is not touched.
   - *Split*: one of Garrick's instruction files that the user changed. Left
     as it is, with no `.new`, until the split below moves their text out.
   - *Yours*: a starting file the user has filled in, such as a `Todo.md`.
     Left alone for good.
   - *Removed by you*: put back only if the user names it.
   - *Retired*: Garrick no longer ships it. Never deleted by the update; ask
     before deleting it yourself.
   - *Then*: what the extras need once their files are written: rebuild
     the Mac app, refresh the Obsidian plugin, point the `desk` link. Or a
     step that is the user's, such as a zone guard run from an older copy.
3. **Apply it on a yes**, naming the release the report was for, so a newer
   one out meanwhile is not taken unseen:
   ```sh
   python3 System/tools/release.py update --tag v0.16.0 --apply
   ```
   Or only what the user picked, the paths exactly as the report gave them:
   `--apply --only "System/tools/check.py,System/status/status.py"`.
   Each repository gets one commit, `Garrick: update to <version>`, holding
   the `.new` files too, so `git revert` undoes it. Say what it printed, in
   short, the steps it took after the files included. If it skipped a file
   because of changes not committed, say which and stop: those changes are
   the user's or another session's, and are never committed for them.
   When it replaced `System/rules.md` or an `AGENTS.md`, say what changed
   in it, one line per rule, from `git show --format= <the commit it printed>
   -- System/rules.md` in the repository that holds it: it is how the
   assistant behaves.
4. **Merge the `.new` files**, next section, now or whenever the user wants.
5. **Split the instruction files** the report listed under *Split*, in the
   section after that, now or whenever the user wants.

**From a Garrick the user has already**, an unzipped download or a clone
after `git pull`, or for a workspace with no `release.py`: ask where it is
unless the user said ("Where is the newer Garrick? The folder you unzipped,
or your clone."). It is the folder holding `install.py` and `update.py`.
Refuse a folder without both, the workspace itself, and any folder inside
the workspace. Then steps 1 and 3 run
`python3 "<newer Garrick>/install.py" --update .`, with `--apply` and
`--only` as above. A workspace that follows `main` ahead of its release
always updates this way: `release.py` refuses a release older than the one
the workspace runs.

## Merge a `.new` file

Do one file at a time, and never more than the user has agreed to.

1. **Find Garrick's version the file last took in**, the base. It is the
   later of two commits, in the repository that holds the file: the last one
   in which Garrick wrote the file itself, and the last one that removed a
   `.new` beside it, a merge or a `.new` the user turned down.
   ```sh
   git log -1 --format=%H -E --grep='^Garrick: (workspace created|update to |.+ created$)' -- "<file>"
   git log -1 --format=%H --diff-filter=D -- "<file>.new"
   ```
   If only one prints a commit, that is the base commit. If both do, the
   later one is: `git merge-base --is-ancestor <first> <second>` succeeds
   when the second is later. Then, with paths from the repository's top:
   ```sh
   git show "<Garrick's commit>:<file>" > "<file>.base"        # when the base is Garrick's own write
   git show "<removing commit>^:<file>.new" > "<file>.base"     # when it is a removed .new
   ```
   A `.new` the update wrote since and that was never merged does not count:
   the base stays before it, so its changes are offered along with the newer
   ones.
2. **Merge mechanically**, keeping the user's changes and Garrick's together:
   ```sh
   git merge-file -p --diff3 "<file>" "<file>.base" "<file>.new" > "<file>.merged"
   ```
   Exit code 0 means no conflict.
3. **Show the user what Garrick changed**, not the whole file: one line per
   change, from the difference between `.base` and `.new`.
4. **Resolve each conflict with the user.** A conflict is a passage both
   sides changed. Offer the two versions and a suggestion; the user decides.
   Never resolve one silently in Garrick's favour.
5. **On a yes**, put the merged text in place of the file, delete `.base` and
   `.merged`, remove the `.new` with `git rm`, and commit the file and the
   removal together, nothing else: `Merged Garrick's update into <file>`. The
   message does not start with `Garrick:`, so step 1 never takes the user's
   merge for Garrick's version, and the removal is what step 1 finds next
   time. If the user turns the update down instead, `git rm` the `.new` and
   commit that alone.

If the file has no commit by Garrick (a workspace older than its history),
there is no base: show the differences between the file and `.new` and merge
by hand with the user.

## Split an instruction file

The user's text in `System/rules.md` or an `AGENTS.md` moves to the local
file beside it, and Garrick's file goes back to exactly as shipped. Do it
after the update itself, so the split compares with the newest Garrick.

1. **Ask what would move**, with the same release as the update:
   ```sh
   python3 System/tools/release.py update --tag v0.16.0 --split
   ```
   Or `python3 "<newer Garrick>/install.py" --update . --split`. For each
   file it names the base, the Garrick version the file grew from; the
   passages the user added, which move under the same heading in the local
   file; and, numbered, the passages where the user changed or removed
   Garrick's own text. Those cannot move on their own. `--json` gives the
   same, for going through them.
2. **Say it back short.** Spoken: "Your rules had four lines of your own;
   they move to your rules file. Two passages to settle: you changed
   Garrick's line on what needs asking, and removed the one on estimates.
   Split?"
3. **Apply it on a yes**, with `--apply`, or for one file with
   `--apply --only System/rules.md`. Each repository gets one commit; a
   `.new` an earlier update left beside the file goes in it too, since
   Garrick's file is as shipped now. Every line of the user's that is not
   Garrick's ends up in the local file: what was not placed under a
   heading waits under *From your earlier <name>, to review*, and holds
   until it is settled.
4. **Settle the passages one at a time**, never more than one per turn, in
   the order the review section numbers them. Read Garrick's line from its
   file, by the opening words the passage quotes, and the user's version;
   recommend one, and let the user decide:
   - *Keep theirs*: move their text under its heading above the review
     section, and say in it what it replaces: "Instead of Garrick's ..."
   - *Take Garrick's*: delete the passage.
   - *Removed* passages: to keep Garrick's line out, write in the local file
     that it does not hold here, in the user's words; to accept it, delete
     the passage.
   After each, commit the local file alone: `Rules: settled <what, short>`.
   When none is left, delete the review heading and its paragraph, and
   commit. The check warns until then.

Never put the user's text back into Garrick's file, and never edit Garrick's
file to settle a passage: the local file wins where the two differ.

## Never

- Never edit `System/context.md` or the version stamp by hand. Only the
  update command writes the stamp.
- Never merge the user's text into `System/rules.md` or an `AGENTS.md`:
  it goes in the local file beside it.
- Never delete a file the update calls retired, or put back one the user
  removed, without being asked.
- Never edit a `.new` file: the update committed it as Garrick wrote it. Never
  leave a half-merged file in place: either the merge the user approved, or
  the file as it was.
- Never run `install.py --update` from a Garrick inside the workspace, and
  never point it at a folder that is not the user's workspace.
  `release.py update` downloads outside it for you.
- Never switch the release notice on, or run `release.py`, unless the user
  asked for an update, whether one exists, or the notice itself.

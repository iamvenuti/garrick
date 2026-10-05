---
name: update
description: >
  Bring the workspace up to a newer Garrick without losing what the user
  changed, and merge the files an update leaves beside theirs as `.new`. Use
  when the user says "update Garrick", "update the workspace", "what would an
  update change?", "is my Garrick up to date?", "merge the update", or "finish
  the update", and when `System/tools/check.py` reports an update to merge.
---

# Update

A workspace is a copy of Garrick taken on the day it was installed. A newer
Garrick reaches it only through this skill. The newer Garrick does the work:
its `install.py --update` compares every file it would write with the one
here, replaces only what is still as some Garrick wrote it, and puts its
version of anything the user changed beside it as `<name>.new`. This skill
runs that command, says what it found, and merges the `.new` files with the
user.

It never downloads Garrick. The user fetches the newer one themselves: a
download from the repository's Releases page, unzipped anywhere, or a clone
after `git pull`. If they ask whether there is a newer Garrick, say where to
look; open the Releases page only if they ask you to, and send nothing from
the workspace with that request.

## Where things are

| What | Path |
|---|---|
| Which Garrick this is, and every file it wrote with its fingerprint | `System/garrick-version.json` |
| Say it in one sentence | `python3 System/tools/check.py --version` |
| A file waiting to be merged | `<the file>.new`, beside it |
| The user's own answers, never touched by an update | `System/context.md` |

## "Update Garrick"

1. **Find the newer Garrick.** Ask where it is unless the user said: "Where is
   the newer Garrick? The folder you unzipped, or your clone." It is the
   folder holding `install.py` and `update.py`. Refuse a folder without both,
   and the workspace itself.
2. **Ask it what would change**, from the workspace's top folder:
   ```sh
   python3 "<newer Garrick>/install.py" --update .
   ```
   This changes nothing. Say the result back in short. Spoken: "Garrick has 6
   newer files, 1 you changed that needs a merge. Update?" Written: the report
   as printed. If it says up to date, say so and stop.
3. **Say what each group means** only when the user asks or when it is not
   obvious:
   - *Replace*: files Garrick wrote that the user never changed. Safe.
   - *Add*: new in this Garrick.
   - *Merge*: changed on both sides. Garrick's version goes beside the file
     as `.new`; the file itself is not touched.
   - *Yours*: a starting file the user has filled in, such as a `Todo.md`.
     Left alone for good.
   - *Removed by you*: put back only if the user names it.
   - *Retired*: Garrick no longer ships it. Never deleted by the update; ask
     before deleting it yourself.
4. **Apply it on a yes.** Everything listed:
   ```sh
   python3 "<newer Garrick>/install.py" --update . --apply
   ```
   Or only what the user picked, the paths exactly as the report gave them:
   `--apply --only "System/tools/check.py,Wikis/Knowledge/raw/.gitkeep"`.
   Each repository gets one commit, `Garrick: update to <version>`, so
   `git revert` undoes it. Say what it printed, in short. If it skipped a
   file because of changes not committed, say which and stop: those changes
   are the user's or another session's, and are never committed for them.
5. **Merge the `.new` files**, next section, now or whenever the user wants.

## Merge a `.new` file

Do one file at a time, and never more than the user has agreed to.

1. **Find Garrick's last version of the file**, the base: the last commit in
   which Garrick wrote it, in the repository that holds it.
   ```sh
   git log -1 --format=%H -E --grep='^Garrick: (workspace created|update to |.+ created$)' -- "<file>"
   git show "<that commit>:<file, from the repository's top>" > "<file>.base"
   ```
2. **Merge mechanically**, keeping the user's changes and Garrick's together:
   ```sh
   git merge-file -p --diff3 "<file>" "<file>.base" "<file>.new" > "<file>.merged"
   ```
   Exit code 0 means no conflict.
3. **Show the user what Garrick changed**, not the whole file: one line per
   change, from the difference between `.base` and `.new`. For
   `System/rules.md` read each changed rule aloud or in full: it is how their
   assistant behaves.
4. **Resolve each conflict with the user.** A conflict is a passage both
   sides changed. Offer the two versions and a suggestion; the user decides.
   Never resolve one silently in Garrick's favour.
5. **On a yes**, put the merged text in place of the file, delete `.base`,
   `.merged` and `.new`, and commit the file alone: `Merged Garrick's update
   into <file>`. The message does not start with `Garrick:`, so step 1 never
   takes the user's merge for Garrick's version.

If the file has no commit by Garrick (a workspace older than its history),
there is no base: show the differences between the file and `.new` and merge
by hand with the user.

## Never

- Never edit `System/context.md` or the version stamp by hand. Only the
  update command writes the stamp.
- Never delete a file the update calls retired, or put back one the user
  removed, without being asked.
- Never commit a `.new` file, and never leave a half-merged file in place:
  either the merge the user approved, or the file as it was.
- Never run the update from inside the workspace's own copy of anything, and
  never point it at a folder that is not the user's workspace.

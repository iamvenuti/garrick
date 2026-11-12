# Correct

Read after `SKILL.md`: the dispatcher's *Resolving a name* and *Listening mode* apply.

## The rules behind this request

These are the rules in `System/rules.md` that this request carries out, word for word.

- **"That's wrong, it's Y"** stops the old value everywhere, not only where it was heard. `System/tools/correct.py` lists every live copy, in memory, `System/context.md`, hubs, thread notes, `Todo.md` and the wikis, and on one yes fixes them all, one commit per repository. Live files keep only the new value, with no trail of the old: git holds it. A raw record is never edited; the page resting on it is marked `corrected:` or `superseded:`.

## Correct: "that's wrong, it's Y"

A wrong value is seldom in one place. An address, an account, a name or a
path one session wrote down, the next ones read as fact: in a memory entry,
in `System/context.md`, a Resume here block, a `Todo.md` line, a meeting
page. Fixing the copy in front of you leaves the others to be read again
tomorrow. When the user says "that's wrong, it's Y", "no, it's Y" or
"correct X to Y", about something written down:

1. **Settle the two values**: the wrong one as it is written, and the right
   one as the user gave it. A heard name is resolved first, as under
   *Resolving a name*. When it is not clear which written value they mean,
   ask.
2. **List every live copy**, which changes nothing:
   ```sh
   python3 System/tools/correct.py --old "<X>" --new "<Y>"
   ```
   It searches the memory entries in the folders `memory` names in
   `System/garrick-checks.json`, `System/context.md`, every hub and thread
   note, each zone's `Todo.md` and the pages of both wikis, and lists each
   file and line. A raw record that holds the old value is listed too, with
   the pages that rest on it.
3. **Say what it found, and ask once.** "Five places have the old address:
   two memory entries, the Acme pricing note, a Todo line and a meeting
   page. Fix them all?" A hit that is right where it is, such as a heard form
   in Aliases, which is meant to be misspelt, is named and left out with
   `--leave <path>`.
4. **On the yes, apply**, with the reason in a few words when the user gave
   one:
   ```sh
   python3 System/tools/correct.py --old "<X>" --new "<Y>" --apply --why "<why>"
   ```
   It writes Y in place of X in every file listed, re-reading each first;
   marks each page that rests on a raw record holding X with `corrected:` (its own text fixed) or `superseded:`
   and one line at its end, since the record itself is never edited;
   rebuilds the Meetings index, and the status page where there is one; and
   commits once per repository, the files it changed and nothing else. A
   memory entry outside the workspace is changed and not committed.
5. **A memory entry whose only source was inbound** now rests on the user's
   word: add `user` to its `source:`.
6. **Report** how many files changed and each commit, and anything left
   uncommitted or refused. The walls check runs on each repository's change
   before it is committed, hook or no hook; where it refused one, that
   repository's files were put back as they were, and nothing there
   changed. The refusal names the check and the paths, and says which
   cause it was: the correction would have crossed a wall; a page's
   frontmatter is not plain key: value lines, or the page is a symbolic
   link, which is its form and no wall; the check did not finish, so run
   it again later; or a file another session has staged there failed the
   check, not this correction. Say the cause it gave, and only the wall
   sentence for a wall.

Never leave a trail of the old value: no "was X", no "not X". Live files
say what is true now, and git holds what was.

The `nurture` skill shares this tool: a correction given during a nurture
pass goes through `nurture.py correct`, which calls `correct.py` and records
it in the day's report.

Spoken: "Fixed in five places, three commits. The meeting page now says its
record has been corrected."

Written: the files changed, the commits, and anything left over.

# The wall check

Read after `SKILL.md`. `wrap.md` and `lifecycle.md` repeat this text, so a wrap or a finish needs no other read.

## The wall check

Run this whenever a wrap, a finish or a new thread would put anything from the
Meetings wiki into a thread note, a hub or a deliverable: quoted, paraphrased,
summarised, counted or linked. Material from earlier in the session counts. The
Knowledge wiki needs no check: it carries nobody's confidence.

1. **The project's zone.** The thread's zone is its folder under `Zones/`.
2. **Each meeting page's frontmatter.** Read `zone`. Missing, unknown or more
   than one: the page is unfinished and stays out. Say that a meeting page is
   missing its zone, and offer to fill it in with the user. `parties` is an
   index and is never asked for.
3. **Zone.** The meeting's `zone` differs from the thread's zone and is a
   walled zone: it stays out, unless the user asked for that meeting in this
   thread in this request. An open zone's pages may be used.
4. **Walls.** A meeting of another walled zone stays out entirely: not quoted, not paraphrased, not summarised, not
   linked, not mentioned as having happened. A wall holds for the whole page,
   even when the other zone said little.
5. **People.** A person page used on its own gets the same check: its zone
   against the project's zone.
6. **What passes** goes in as the least that serves: link the meeting page, and
   quote only where the wording is the point.
7. **Say that a wall held something back, in the words the rule gives, and
   nothing more.** "A wall holds some material back from this project, so I
   have not used it. Nothing was written." No title, date, party, person,
   subject or count, even if asked in the same breath. A question put straight
   to the Meetings wiki ("what did Theo say?") is a different request; its
   answer stays in the conversation and is never written here.
8. **Material the user dictates** into a thread that belongs to another walled
   zone: ask once before writing it. "That sounds like Home material, and Home
   is walled off from Work. Write it anyway?"
9. **Can't tell** whether a wall applies: ask.

**The same check runs again before every commit, whenever git runs the
hook.** Each zone's pre-commit hook runs
`System/tools/check.py --staged --walls-only` on the files being committed. A
link, embed or path to a file of another walled zone, a link to a Meetings
page of another walled zone, or a whole file copied from one, stops the commit, with one line naming the file and the
wall.
When it refuses:

- **Take the material out** of that file and commit again. Tell the user a wall
  held something back, as in step 7, and nothing more.
- **Never commit with `--no-verify`** unless the user explicitly asks for it,
  in this request. Yes once is not yes next time.
- **If the refusal looks wrong** (a link to a file of an open zone,
  say), tell the user which file and which wall, name the command that lets
  that one refusal through once (`python3 System/tools/check.py allow <path>
  <id>`; run without an id it lists them; the report prints that command first), and stop. Only the user
  writes an allowance, in a terminal. Never write
  one yourself, and never touch `System/walls-allowed.json`.

Git skips the hook when its `core.hooksPath` setting sends commits past it,
and then nothing checks the walls at commit time. `check.py` warns when that
is so: tell the user what it says, and until it is fixed treat this
procedure as the only check.

The wall is between zones, not between the user and their own memory. It
decides what is written into a project, never what the user may know.

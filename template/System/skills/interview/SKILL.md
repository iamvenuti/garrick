---
name: interview
description: >
  Interview the user one question at a time about what they do, for whom,
  and whose confidences they hold, keep a record as it goes, then propose
  the first parties, walls, projects, threads and open actions, and set them
  up only on a yes. The opening move in a new workspace, and useful again
  when a new side of work starts. Use when the user says "interview me",
  "get to know me", "ask me about my work", "help me set up my workspace",
  or "where do I start".
---

# Interview

Typing folder names is the slow way to start. A short interview, one question
at a time, gives you more to work with than an afternoon of setup, and leaves
a record behind. This skill asks, writes down and proposes. It creates nothing
until the user says yes.

What makes it a Garrick interview is the second question: whose confidences
the user holds, and which of them must never meet in writing. Everything else
in the workspace leans on that answer.

Everything here works spoken or typed. Ask for the ear when the user is
listening, as *Listening mode* in the `threads` skill describes: one short
question per turn, nothing read out as a list.

## Where things are

All paths are relative to the workspace root.

| What | Path |
|---|---|
| The interview record | `System/interviews/YYMMDD - <Topic>.md` |
| Me, Zones, Parties, Walls, People, Aliases | `System/context.md` |
| The zones | the folders under `Zones/` |
| New zones, projects and threads | `System/tools/scaffold.py`, as the `threads` skill's *New zone* and *New* procedures run it |
| Open actions | `Zones/<Zone>/Todo.md` |

## Before the first question

1. **Read what the installer already knows**: `System/context.md` and the
   folders under `Zones/`. Do not ask for any of it again. Say it back in one
   sentence and ask whether it still holds: "You're an independent advisor
   with Work and Personal zones, and two parties so far, Acme and Birch. Still
   right?"
2. **Settle the topic.** If the user named one ("interview me about the Birch
   work"), that is the topic. Otherwise it is "Getting started".
3. **Start the record**: `System/interviews/YYMMDD - <Topic>.md`, today's date,
   with this header, and save it before asking anything:
   ```markdown
   # Interview: <Topic>

   Started <date>. Questions and answers in the user's words, in order. The
   proposal and what was set up follow at the end.
   ```
   The record lives in `System/` because it describes the user, as
   `System/context.md` does, not one zone.

## The questions

Ask them in this order, one per turn, and wait for the answer. Skip one the
installer already answered; confirm it instead.

1. **What you do, and for whom.** In a sentence or two.
2. **Whose confidences you hold.** Every organisation or person who tells you
   things they would not want the others to see: clients, an employer's
   projects, a board you sit on, a friend's business. For each one, what it
   is and which zone it belongs to. Then ask about pairs, by name: "Would Acme
   mind Birch seeing your notes, or the other way round?" A yes is a wall.
   Inside one employer, two internal projects can be parties too, with a
   wall between them.
3. **The five things you do every week.** Recurring work, not projects.
4. **Who you owe something right now**, what it is, and by when.
5. **Where your files and notes live today.** Folders, mail, apps, paper.
6. **What you keep forgetting.** The thing that slips when the week gets full.

Then once: "Anything else I should know before I propose a setup?"

**Push back on a vague answer**, once, with something specific to answer:

- "Clients, mostly." → "Name the two you spent most time on last month."
- "Lots of things." → "Which one would hurt most if it slipped?"
- "It depends." → "Take last Tuesday. What did you actually do?"

Never more than two follow-ups on one question. If it is still vague, write
down that it is, and move on.

## Keep the record as you go

After every answer, re-read the record and append:

```markdown
## <n>. <the question, as you asked it>

<the answer, in the user's words, with dictation noise cleaned up and nothing else changed>
```

Follow-ups go under the same heading. Save after every answer, so stopping at
any point loses nothing.

**Who and what kind, never what a party said in confidence.** The record
sits in `System/`, where any project can read it, on either side of any wall.
If an answer carries a party's numbers, plans or words, write who and what
kind only ("Birch shared its launch figures with me"), and tell the user you
did. No check reads the record, so this rule is all that guards it. And the
wall check does not count the record as wording every side shares: it still
refuses a project note that repeats a walled meeting, whatever the record
says. Never write a password, an account number or any other secret.

## "Stop", "that's enough", "propose it"

Said during the interview, these end the questions. Write the proposal at the
end of the record under `## Proposal`, then show it.

1. **Parties** to add to `System/context.md`: name, what it is, zone, tag, and
   mail domains if the user gave them. Check each tag is one lowercase word.
2. **Walls**: each pair, and why. Mark any wall you inferred rather than
   heard, and ask about it by name. Never add a wall the user did not confirm,
   and never leave out one they asked for.
3. **People and aliases** heard during the interview.
4. **Projects and first threads**, zone by zone: the project, its party, its
   first thread. Every name must be sayable: no dates, codes or punctuation
   (a year as a word of its own is fine), and no two siblings that sound
   alike. Offer a spoken version of any that is not.
5. **Open actions** for each zone's `Todo.md`, from question 4.
6. **Ways in**: for each place files live today, the inbox it would feed.
   Advice only: nothing is connected or moved.
7. **Recurring work** from question 3 that could later run on a schedule.
   Advice only.
8. **What I still don't know**: every gap, as a short list. This is the part
   the user most needs to read.

A zone the answers need but the workspace does not have: propose it, with
what it holds. On a yes it is made first, through the `threads` skill's
*New zone* procedure.

Spoken: "I'd set up three projects in Work and one in Personal, with four
parties and one wall, between Acme and Birch. The thing I still need most is
who owns the Cobalt contract. Shall I set it up?"

Written: the whole proposal, as it stands in the record, and the record's
path.

## On a yes

The user may accept all of it, part of it, or change it first. Apply only what
was accepted, in this order. Every commit stages its files by name, never
`git add -A`: the record waits unfinished in the root's repository until
step 6, and another session may have changes of its own in any repository.

1. **Zones**, if the proposal adds any, one at a time through the `threads`
   skill's *New zone* procedure, before anything names them.
2. **Parties, Walls, People, Aliases.** Re-read `System/context.md` right
   before editing it, then add the rows. Commit it alone in the workspace
   root's repository:
   ```sh
   git add -- System/context.md
   git commit -m "Interview: four parties, one wall"
   ```
3. **Projects and threads**, through the scaffolding script, one at a time, as
   the `threads` skill's *New* procedure says. When it refuses a name, relay
   the reason and offer a fix. Each is committed in its zone as that
   procedure says, by name.
4. **Open actions.** Re-read each zone's `Todo.md` and append under `## Inbox`
   as `- [ ] [[<Thread>]]: <action> 📅 <YYYY-MM-DD>`, in the format the
   list's header gives: the thread just set up for it, or `<Party>: ` with
   the party or person when no thread fits, and a date only when one was
   given. Commit each
   zone's list in its own repository:
   ```sh
   git -C "Zones/<Zone>" add -- Todo.md
   git -C "Zones/<Zone>" commit -m "Interview: open actions"
   ```
5. **Run the check**: `python3 System/tools/check.py`. Explain any problem in
   plain words. The threads just made start with the template's resume
   points: offer the `setup` skill's *Fill in my resume points* for them.
6. **Close the record**: add `## Set up` with what was created and the commit
   hashes, then commit it on its own in the workspace root's repository:
   ```sh
   git add -- "System/interviews/YYMMDD - <Topic>.md"
   git commit -m "Interview: <Topic>, set up"
   ```

Never push. That leaves the machine and needs its own yes.

Spoken: "Set up: four parties, one wall, four projects. Say 'what's open' to
see them, or 'open' and a project's name to start."

## What this skill does not do

- **It creates nothing before a yes**, and only what the yes covered.
- **It asks one question at a time**, never a form.
- **It never records what a party said in confidence**, only who and what kind.
- **It never guesses a wall.** An inferred wall is proposed and asked about.
- **It makes a zone only through the `threads` skill's *New zone***, and
  only on a yes. It does not move, copy or connect the user's existing files
  and accounts.
- **It never pushes, sends or shares.**

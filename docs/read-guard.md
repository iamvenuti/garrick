# The read guard

## What it is

Walls already stop your assistant from writing one zone's material into another. The read guard does the same for reading. In a session for one project, it stops the assistant from opening notes, meetings and mail that sit behind another wall. It also checks what a mail or calendar service hands back, and takes out the messages that belong behind another wall.

It is optional, and it starts by only watching. You turn it on in Garrick.app: open Settings, then Walls, then *Read guard*, and choose **Watch only** or **On**. Choosing either adds the read guard to your assistant's settings on this computer, and **Off** takes it out again. Nothing in this page needs a terminal. [The hooks page](../extras/hooks/README.md) has the registration by hand, for a computer without the app.

| Choice | What happens |
|---|---|
| **Off** | Nothing runs. This is how Garrick ships. |
| **Watch only** | Every read goes through. The guard keeps a list of what it would have stopped. |
| **On** | A read across a wall is stopped, or you are asked, as *Across a wall* says. |

*Across a wall* is **Refuse** (stop every such read, with no question) or **Ask me** (ask you each time, so you can allow one read for one session). *Mail and calendar tools* lists the services whose results are checked, and *Tools with nothing to check* lists those Garrick leaves alone and does not warn about.

## One read

![One read. A session opened in a project has that project's zone as its scope. The assistant asks to read a note. The read guard asks the wall rules which zone owns the note. If the note is in the same zone, or in an open zone, the read goes through. If it is in another walled zone, what happens depends on the choice. Under Watch only, the read goes through and is noted in the log. Under On with Refuse, the read is stopped and the assistant is told the wall sentence. Under On with Ask me, you get a yes or no question, and a yes lets that one read through for that session.](assets/one-read.png)

A session opened in a project has that project's zone as its scope. A session opened at the workspace root, or in `System/`, keeps full read.

When the assistant asks to read a note, Garrick finds the zone that owns it. The same zone, or an open zone: the read goes through. Another walled zone: it depends on your choice.

- Under **Watch only**, the read goes through and is written to the log.
- Under **On** with **Refuse**, the read is stopped. The assistant is told the wall sentence, which names nothing: no party, no page, no count.
- Under **On** with **Ask me**, you get a yes-or-no prompt. A yes lets that one read through, for that session. Claude Code asks in its own permission prompt. Codex cannot ask: it refuses once, and lets the same read through when the assistant tries it again.

A search over a whole wiki, or over a folder that holds several zones, is stopped when the guard is On, with a pointer to the Recall search, which keeps to what the project may read.

## A mail search

![A mail search. The assistant, in a session for one project, searches a mail service. The service returns a list of messages, and the read guard checks the list before the assistant sees it. For each message it matches the addresses against the list of parties and gets the zone of each. It takes out the messages that belong behind another wall. The assistant sees the rest of the list, and the wall sentence once, with no count, if anything was taken out.](assets/a-mail-search.png)

A mail or calendar search can return messages from every part of your life in one list. Before your assistant sees the list, Garrick matches each message's addresses against your list of parties, as the `intake` skill matches a mail, and takes out what belongs behind another wall. The assistant sees the rest, and the wall sentence once if anything was taken out, with no count. Your own addresses and personal webmail decide nothing. A message that no party claims has no zone, so the guard treats it as behind a wall.

This works in Claude Code. Codex cannot have a tool's result replaced, so the mail and calendar rows do not apply to it: Settings says so, and only the instructions keep its mail results apart. Add a tool to *Mail and calendar tools* when you connect a new mail or calendar service. Garrick names a tool your sessions used that is on neither list, so you can place it.

If Garrick cannot read the list of parties, or the part of Garrick that matches addresses is missing, the filter cannot tell which message belongs where. Settings says so on the *Read guard* row. While the guard is **On**, every result from a listed tool is taken out and the wall sentence stands alone. Under **Watch only**, nothing is taken out and the log notes that it could not decide.

## The first week

Start with **Watch only** and use Garrick as you always do. Under the choice, Settings says what the log holds for the last seven days: "In the last 7 days it would have stopped N reads". If sessions of more than one zone are in the log, it says it once for each zone, never as one sum. *Show* opens the list.

The list shows, for each read, when it happened, which tool made it and what the guard would have done. It shows nothing about what was read: the log keeps a hash, never a path, a party or a title, on purpose. So read it against your own week. A read at a time you were asking the assistant to work across zones is a read you needed.

- **The list holds nothing you needed.** Choose **On**. Those reads are stopped from then on.
- **The list holds reads you needed, because you asked for work across zones.** Choose **On** with **Ask me**. It asks you each time, so you can allow one read for one session.
- **The list is empty.** Either nothing crossed a wall, or the guard was not running: check that the choice shows Watch only, and that you opened a new session after choosing it. In Codex, a hook does not run until you trust it: run `/hooks` and trust the read guard, and do it again after each change you make in Settings.

## What it does not cover

The read guard narrows a gap. It does not close it, so do not rely on it for more than it does.

- **Shell commands it cannot follow.** It reads the plain path words in a command. A command with a variable, a substitution or an unbalanced quote is allowed and noted as unread. A command that changes folder first is read as best it can be.
- **Codex.** It is checked on its shell commands only, not on mail and calendar results, and it cannot ask you: it refuses once. It also skips a hook until you trust it in `/hooks`, and again after any change to it.
- **Tools that are not on the list.** Only the tools on *Mail and calendar tools* are filtered.
- **What a name says.** A client's name typed into a note of another zone is not caught. The guard decides by where a file is, not by what it says.
- **A broken guard.** An error while it checks a read lets that read through, and the log says so. An error while it filters a mail result removes the result when the guard is On, even when Garrick's own tools cannot be loaded: it then reads the setting from the settings file itself. A settings file that is there and does not read counts as On for the mail and calendar check, and Settings shows On with a line that says the file does not read. Two limits remain. A hook that runs past its time limit is stopped by the assistant, and then the result goes through. And when no workspace is found from the folder the session was opened in, the guard cannot tell what to protect, so the result goes through.
- **Scheduled jobs.** They are logged and never refused, since nobody is there to ask.

[What is enforced](enforced.md#the-read-guard) has the technical detail.

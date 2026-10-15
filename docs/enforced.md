# What is enforced, and what is asked

Some of Garrick's protections are code: a script that refuses, whatever the assistant intends. The rest are rules the assistant is asked to follow, and they hold only as well as it follows them. This page says which is which, so you can judge each one for what it is.

## The table

| Protection | How it holds | Where |
|---|---|---|
| A commit of a project file that links to a meeting across a declared wall, names a party, person or alias from the far side, or repeats eight words in a row held only there | **Code refuses.** Not complete: see [the known gaps](#the-wall-checks-known-gaps) | The pre-commit hook in each zone, and in any git repository inside a project, runs `System/tools/check.py --staged --walls-only`. See [What the check covers](principles.md#what-the-check-covers) |
| A commit that links to, or repeats eight words from, a meeting page with no zone or parties yet | **Code refuses** | The same hook |
| A commit of anything waiting in a zone's `Inbox/` or in `Wikis/Meetings/raw/inbox/` | **Code refuses** | The same hook |
| A status page request carrying a field its verb does not declare | **Code refuses**, naming the field | `page_action.py` in the status extra, checking `DECLARED` in `System/tools/operations.py`. Without `operations.py` in the workspace nothing is validated |
| Parking a thread already parked, waking one already active, or changing a Todo line that has changed since the page was built | **Code refuses** | The precheck in `System/tools/operations.py`, applied by `scaffold.py park` and `wake`, and by `page_action.py` |
| A project, thread or zone name that is not a name, is the same folder as a sibling or sounds like one; a zone name that cannot be said aloud; a project called `Inbox` | **Code refuses**, with one line saying why | `System/tools/scaffold.py`. A project or thread name that does not say how it is said is made, and you are asked for its `spoken:` form |
| A project whose party tag `System/context.md` does not carry; a party whose name two parties share; a tag that breaks the tag rule; a wall naming a tag that is not a party | **Code refuses** | `System/tools/scaffold.py project` and `scaffold.py party` |
| Renaming or deleting while the zone has uncommitted changes in the way, something staged, a merge under way, or a cmux tab mid-turn in the folder; a delete whose `--confirm` does not name the thing exactly | **Code refuses**. Without `--confirm`, delete only lists what would go | `System/tools/scaffold.py rename` and `delete` |
| A scheduled job sending, sharing, deleting, publishing, reaching the web or editing `System/` | **Code refuses**, for Claude: every unattended call loads the deny list, and a list that has lost a core entry stops the call. Codex has no deny list; a job allowed only reading tools runs read-only | `extras/jobs/headless-settings.json`, loaded by `extras/jobs/agent.py`. See [Scheduled jobs](extras/scheduled-jobs.md#what-an-unattended-assistant-may-do) |
| An edit to a file outside the project the session was opened in | **Code stops it once**, if you installed the optional zone guard. A reminder, not a gate: in Codex a second attempt goes through, and a shell command that writes a file is not covered. The Meetings wiki is not stopped at all, from any session, because filing a conversation authorises the writes it needs | `extras/hooks/zone_guard.py`. See [the zone guard](../extras/hooks/README.md) |
| Which commands the assistant runs without asking | **The assistant's permissions**, which Garrick can set at install: its own tools except `release.py`, and git's `status`, `diff`, `log`, `add` and `commit`, and nothing that pushes, pulls or deletes. Anything else is asked by the assistant's own prompt | `.claude/settings.json` in the workspace, written by `install.py`. See [The commands it asks to approve](first-steps.md#the-commands-it-asks-to-approve) |
| A git setting that skips the hooks, a missing hook, a `CLAUDE.md` that hides `AGENTS.md`, a committed page from `System/generated/`, a meeting page naming both sides of a wall, a raw record changed after filing | **Code reports**, and stops nothing | `System/tools/check.py`, run by hand, by the status page or on a schedule. See [The check](commands.md#the-check) |
| Adding a party: a new row in `System/context.md`, your own file | **Code writes, on a question.** `scaffold.py party` writes the row and leaves the commit to you. What authorises it is the skill asking you once first, not a mechanism | `System/tools/scaffold.py party`, run by the `threads` and `meetings` skills |
| Reading the Walls table before using a meeting in a project, and leaving walled material out, paraphrase and summary included, saying only that something was held back | **Asked** | [Zones and walls](../template/System/rules.md#zones-and-walls) in `System/rules.md` |
| Asking before anything leaves the machine: sending, posting, sharing, publishing, every time | **Asked** | [Autonomy](../template/System/rules.md#autonomy) |
| Asking before anything that cannot be undone: deleting, rewriting git history, overwriting a file nothing else holds | **Asked** | [Autonomy](../template/System/rules.md#autonomy) |
| Never guessing a zone, a party or a project, and never across a wall: asking in one line instead | **Asked** | [Autonomy](../template/System/rules.md#autonomy) and [Ways in](../template/System/rules.md#ways-in) |
| Asking before writing outside the project the session was opened in | **Asked**, with the zone guard as an optional reminder | [Autonomy](../template/System/rules.md#autonomy) |
| Taking a mail's parties from its addresses only when confirmed, and never from personal webmail or your own addresses | **Asked** | [Ways in](../template/System/rules.md#ways-in) |
| Never skipping the wall check with `git commit --no-verify` unless you ask | **Asked** | [Zones and walls](../template/System/rules.md#zones-and-walls) |
| Never editing anything in a wiki's `raw/` | **Asked**; the check reports a raw record that changed | [Files](../template/System/rules.md#files) |
| Never printing, writing or committing a secret | **Asked** | [Secrets](../template/System/rules.md#secrets) |
| Rewriting a thread's Resume here block at the end of a session that produced a decision or a deliverable | **Asked**; the check warns about a block still holding the template's prompts | [Threads](../template/System/rules.md#threads) |

Everything else in `System/rules.md`, and in your `System/rules.local.md`, is asked in the same way.

## The wall check's known gaps

The wall check catches specific signs of material crossing a declared wall. It does not catch everything, and two gaps are known and open:

- **A person who is a party, and also on the near side as themselves.** A one-to-one client can be a party, tagged with their surname, and also take part in a walled project as themselves, with a People row under each party. The People row clears their full name, but not the party's tag: the tag is one of the party's name forms, and here it is the surname, so a note that names them is still refused. The refusal does not say that the tag, not the name, matched. Issue [#98](https://github.com/iamvenuti/garrick/issues/98); a proposed fix is in review as [#100](https://github.com/iamvenuti/garrick/pull/100).
- **A party whose tag is an ordinary word.** A tag such as `anchor` or `delta` is a name form too, so once a wall is declared against that party, every note on the near side that uses the word in its ordinary sense is refused. No near-side name contains the tag, so the fix proposed for the first gap does not reach it. In practice the wall cannot be declared without refusing ordinary notes, and a wall left out of the table holds nothing back. Until this is settled, give such a party a tag that is not a common word before you declare its wall. Described in [a comment on #98](https://github.com/iamvenuti/garrick/issues/98#issuecomment-6174966795).

Beyond these, the check has limits by design: a clean paraphrase, wording moved rather than copied, the contents of Word, PowerPoint and PDF files, chat replies and anything sent are outside what it reads. [What the check covers](principles.md#what-the-check-covers) sets them out. A clean result means the implemented checks found nothing, not that nothing crossed.

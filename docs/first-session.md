# Your first useful session

The aim is to leave with a brief you can use and a next action you can find tomorrow. Use either the desktop app or your terminal assistant, opened on your **own Garrick workspace**. No Obsidian, cmux, mail connection or recorder is needed.

## Optional: let it interview you first

If you would rather be asked than decide where to start, say:

> Interview me.

The assistant asks one question at a time: what you do and for whom, whose confidences you hold and which of them must never meet in writing, the five things you do every week, who you owe something right now, where your files live today, and what you keep forgetting. It pushes back on vague answers and keeps a record in `System/interviews/` as it goes. Say "stop" when you have said enough. It then proposes parties, walls, projects, first threads and open actions, lists what it still does not know, and sets up only what you say yes to. Allow twenty minutes. Afterwards, pick one of the projects it made for step 1.

## 1. Pick one piece of work

Choose a real project and one question you need answered. Keep the first session small. For example:

> Create a project called Supplier Review in Work, for the party acme, with a thread called Next Call. Ask me for any missing details, one question at a time.

Replace those names with your own. The assistant can add a missing party to your context and ask which existing parties need a wall. If the work belongs in a zone you don't have yet, ask for that first: "add a zone called Garden, for the house and the garden." A party can represent an internal project as well as a company. Two internal projects need distinct tags and an explicit wall if their information must stay apart.

## 2. Give it one conversation

Use a short email, transcript or notes from a call that you are allowed to process with this assistant. A few sentences you type yourself are enough. Paste them with:

> File these as notes of a conversation in Work for acme. The call was on [date]. Ask if anything is unclear. [Paste notes.]

Or save an email as `.eml` in `Zones/Work/Inbox/`, or a text transcript in `Wikis/Meetings/raw/inbox/`, and say “process the inbox”. There is no need to connect your mailbox yet.

Confirm the source, date and parties when asked. These labels let Garrick apply walls you have already declared; labelling a meeting does not create a new wall. Read the filed summary against the original and correct mistakes now.

## 3. Get something useful back

> Open Supplier Review, Next Call. Prepare a short brief for this project from the conversation I just filed: what was decided, what I owe them, and what to ask next. Save the brief in this project's Deliverables. Show which source you used. Do not send it.

Check the brief against the source. The assistant should apply the declared walls before drafting. Its commit check catches only certain kinds of leakage; you still review the content before sharing it.

## 4. Save where you stand

> The next action is [your actual next action], due [date]. Wrap Next Call, and run the workspace check. Explain any problem in plain language.

The assistant updates the resume note and saves changes to the appropriate local git repositories. It may ask you to approve commands; [the commands it asks to approve](first-steps.md#the-commands-it-asks-to-approve) says what each one does and how to allow them once. “Commit” here means saving local history; Garrick's rules require separate approval to publish or send.

## 5. Open a fresh chat and resume

Select the same Garrick folder in a new app chat, or start a new terminal session there. Say:

> Open Supplier Review, Next Call. What do I need to do next?

It should answer from the saved note without asking you to retell the conversation. If it cannot, ask it to check the workspace instructions and resume note before importing more material.

Tomorrow, return for that next action. Once this is useful, add another project or an [optional tool](extras/index.md).

## Try the wall with fictional data

Use the separate `~/Garrick-demo` workspace for this exercise, never your real one. If it is not built yet, build it in Terminal from the folder Garrick came in, `~/Downloads/garrick-main` for the ZIP:

```sh
cd ~/Downloads/garrick-main
python3 examples/demo/build.py --target ~/Garrick-demo
```

For a clone, start with `cd ~/garrick-source` instead. Then open `~/Garrick-demo` in a separate app chat or terminal session.

1. Say “Open Birch Entry, Carrier Choice.”
2. Say “Prep me for Cobalt for this Birch project. Apply the walls before drafting.” The intended result uses the Birch-side call and says some material was held back, without revealing the Acme call's contents.
3. Ask “Which party pairs have a wall declared?” It should identify the configured Acme/Birch pair. It should not claim that every separate project has a wall.

This checks how your assistant follows the rules in one example. It is not proof against every leak. [Principles](principles.md#what-the-check-covers) describes the deterministic check and its limits. Return to your own workspace when done.

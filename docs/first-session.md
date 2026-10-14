# Your first useful session

The aim is to leave with a brief you can use and a next action you can find tomorrow. Use either the desktop app or your terminal assistant, opened on your **own Garrick workspace**. No Obsidian, cmux, mail connection or recorder is needed. Nothing has to be set up first.

## 1. Say what you need to prepare

Not what Garrick should create. What you actually need, in your own words:

> Help me prepare my next supplier call.

The assistant reads your context file, matches the organisation you named against the parties, people and aliases you already have, and looks for a project that is already theirs. Where it finds one, it asks nothing and gets on with it.

Where the organisation is new to the workspace, there is one question, and it is the only one:

> Acme Corp isn't in your workspace yet. Shall I add it as a party in Work, which means its confidences are yours to keep, and start a Supplier call thread for it?

With more than one zone that could take it, the same question names the alternative, so one answer settles both. One yes covers the row in `System/context.md`, the short tag that goes with it, the project and its first thread. You are never asked to invent a tag or a thread name: the tag comes from the name you said, and the project and thread are named from your own words. Mail domains, people, further walls and any connected account wait until something needs them.

Two things it will not decide for you, and both are the point rather than a nuisance:

- **Two of your parties share a name**, which happens when one organisation deals with you in two capacities. The name alone cannot say which, so it asks: "Two of your parties are called Acme Corp: the supplier in Work, and the research client in Consulting. Which one is this call with?"
- **The same organisation in a second capacity.** It asks whether the two should be kept apart in writing. A yes adds the wall; without one, the workspace check keeps warning you, because a shared name can otherwise carry one capacity's material into the other's.

If the work belongs in a zone you don't have yet, ask for that first: "add a zone called Garden, for the house and the garden." A party can stand for an internal project as well as a company.

### Or let it interview you first

If you would rather set the whole workspace up before doing anything with it, say:

> Interview me.

The assistant asks one question at a time: what you do and for whom, whose confidences you hold and which of them must never meet in writing, the five things you do every week, who you owe something right now, where your files live today, and what you keep forgetting. It pushes back on vague answers and keeps a record in `System/interviews/` as it goes. Say "stop" when you have said enough. It then proposes parties, walls, projects, first threads and open actions, lists what it still does not know, and sets up only what you say yes to. Allow twenty minutes. Afterwards, pick one of the projects it made and carry on from step 2.

## 2. Give it one conversation

Use a short email, transcript or notes from a call that you are allowed to process with this assistant. A few sentences you type yourself are enough. Paste them with:

> File these as notes of my call with Acme Corp, on [date]. Ask if anything is unclear. [Paste notes.]

Or save an email as `.eml` in `Zones/Work/Inbox/`, or a text transcript in `Wikis/Meetings/raw/inbox/`, and say “process the inbox”. There is no need to connect your mailbox yet.

Confirm the source, date and parties when asked. These labels let Garrick apply walls you have already declared; labelling a meeting does not create a new wall. Read the filed summary against the original and correct mistakes now.

## 3. Get something useful back

> Prepare a short brief for the supplier call from the conversation I just filed: what was decided, what I owe them, and what to ask next. Show which source you used. Do not send it.

The brief goes into the thread note, which is the one place the next session looks: your words under *The ask*, the brief under *State of play*, and the *Resume here* table filled in, with the filed page linked as its source and the one thing due as the next action. That action is also a line in your zone's `Todo.md`. A separate file in the project's `Deliverables/` is offered rather than written: ask for it if you want one.

Check the brief against the source. The assistant applies the walls you have declared before drafting, and says that something was held back without saying what. Its commit check catches only certain kinds of leakage; you still review the content before sharing it.

## 4. Save where you stand

> The next action is [your actual next action], due [date]. Wrap it, and run the workspace check. Explain any problem in plain language.

The assistant updates the resume note and saves changes to the appropriate local git repositories. It may ask you to approve commands; [the commands it asks to approve](first-steps.md#the-commands-it-asks-to-approve) says what each one does and how to allow them once. “Commit” here means saving local history; Garrick's rules require separate approval to publish or send.

## 5. Open a fresh chat and resume

Select the same Garrick folder in a new app chat, or start a new terminal session there. Say:

> Open the supplier call thread. What do I need to do next?

Step 1 told you what the project and thread were called, and either name finds it. It should answer from the saved note without asking you to retell the conversation. If it cannot, ask it to check the workspace instructions and resume note before importing more material.

Tomorrow, return for that next action. Once this is useful, add another project or an [optional tool](extras/index.md).

## Try the wall with fictional data

Use the separate `~/Garrick-demo` workspace for this exercise, never your real one. If it is not built yet, build it in Terminal from the folder Garrick came in, `~/Downloads/garrick` for the download:

```sh
cd ~/Downloads/garrick
python3 examples/demo/build.py --target ~/Garrick-demo
```

For a clone, start with `cd ~/garrick-source` instead. Then open `~/Garrick-demo` in a separate app chat or terminal session.

1. Say “Open Birch Entry, Carrier Choice.”
2. Say “Prep me for Cobalt for this Birch project. Apply the walls before drafting.” The intended result uses the Birch-side call and says some material was held back, without revealing the Acme call's contents.
3. Ask “Which party pairs have a wall declared?” It should identify the configured Acme/Birch pair. It should not claim that every separate project has a wall.

This checks how your assistant follows the rules in one example. It is not proof against every leak. [Principles](principles.md#what-the-check-covers) describes the deterministic check and its limits. Return to your own workspace when done.

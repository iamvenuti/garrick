# Extra: remote access (preview)

Remote access lets an assistant on your phone, or on another computer, work with your workspace over a remote connection. It can read a thread, answer follow-up questions, and save a note or an action, by voice where the assistant supports voice. The workspace stays on your Mac. Nothing is served until you turn remote access on in Settings, at the Mac.

**This is a preview.** Settings says *Preview* next to it. It does part of the job, it has been tested with a stand-in for the relay and with a test client on the same computer, and the parts a person has to try are still open. Read [what it does now](#what-it-does-now) and [what is not verified](#what-is-not-verified-yet) before you rely on it.

It is separate from [phone access](phone-access.md), which uses your assistant provider's own remote features and gives the phone the same reach as the desktop session. Remote access is Garrick's own service, with its own sign-in and its own limits on what a phone may see.

## What it does now

A connected assistant gets five read tools and ten actions. Everything else is listed with the release that plans it, so a partial service is never mistaken for a complete one.

<!-- manifest -->
TODO(orchestrator): this table is generated from the extra's manifest. Until then it holds the counts at 0.81.0.

| What | Verbs | Count |
|---|---|---|
| Works now | A note, the six Todo actions, park, wake and checkpoint | 10 |
| Only with your approval, which does not exist yet, so refused | Twelve of the page's own buttons, a new project with a new party, delete, settings, update and scheduled jobs | 17 |
| Not for an assistant at all | Five internal verbs, and the reading of a single note by path | 6 |
| Planned for a later release | The rest | 33 |

The five read tools are listed apart and work now: places, thread state, search, read and what you owe.
<!-- /manifest -->

Reads go through the same readers the Ask window uses, so a read gives the answer Ask gives at the desk, and each result names its source and its date. Writes run as a click on the page runs: the same checks, the same commit, the same wall check. A write returns at once with an operation id, because a commit can take longer than an assistant waits for one answer. A second call with the same id gives the first result, so asking twice saves once.

An assistant cannot change what it may see, cannot change a grant and cannot change a setting. Those change only in Settings, at the Mac.

## Reach

Each connected assistant has a grant, and each grant has a reach: the zones it may read and the zones it may write, set at the Mac. By default the reach is the zones that are not walled, Knowledge and Garrick's own docs. A walled zone joins a grant only when you turn it on by name, in Settings, after the notice below. Reading and writing are separate choices, and Garrick records the date.

A request that names a zone outside the reach gets one answer, "new context required", and nothing is released. A project, a thread or a record in a walled zone outside the reach is answered as a place that is not there. No count, title or path changes.

Each answer carries a handle. When you change a grant's reach at the Mac, its old handles stop working and the assistant is told to start a new chat.

## What leaves the Mac

On a read, the text of each result leaves: up to a few thousand characters of a record for each read, a short snippet for each search hit, the first part of a thread's resume block, titles, dates, and the paths that carry zone, project and thread names, and up to forty Todo lines. On a write, the words you dictate leave in the other direction.

It goes to the relay, which carries it and, with the method this release uses, cannot read it. It then goes to the assistant provider. There it becomes part of the chat: kept in the chat history under that account's settings, shown on every device signed in to the account, and spoken aloud in voice mode. If you point the address at a server of your own, that server can read it.

Revoking access stops new calls. It removes nothing already returned.

## What Garrick cannot enforce

- Another connector in the same chat, such as mail or a drive, can carry a record further. Garrick's rule that anything leaving the machine is confirmed first has no place to act in a chat. A sentence planted in a record could ask the assistant to mail the record, and only the assistant's own approval prompt stands in the way.
- The commit check does not see a chat.
- The service makes sure that no call crosses a grant's reach and that only you change it. It does not prove that a chat is fresh. If you change a reach and keep talking in the old chat, with an assistant that asks for a new handle, two zones can still end up in one chat.

## The notice before a walled zone

Settings shows this before it turns a walled zone on, once for each zone:

<!-- notice -->
> Turning on {zone} lets a connected assistant see what this zone holds. What it reads leaves this Mac. It goes through your address: the relay carries it but cannot read it, and a server of your own that forwards it can. Then it goes to the assistant's provider, where it becomes part of the chat. It stays in the chat history after you revoke access. Another connector in the same chat, such as mail, can carry it further. The commit check does not see a chat.
<!-- /notice -->

## Set it up

You do this at the Mac. Settings shows the state of each step and says which one is missing and what to do next.

1. Open Settings and find *Remote access (preview)*. TODO(orchestrator): the exact Settings labels and the order of the steps, from the remote branch.
2. Turn remote access on. It works on a computer that is *one computer* or the *home server*. On a *laptop copy* Settings says why it cannot be turned on, and nothing listens.
3. Set up the address. TODO(orchestrator): the relay's steps and the "I already have an address" adapter's, as the remote branch words them. The relay's name appears in public certificate logs, you do not choose it, and a change of name means adding the connector again to the assistant.
4. Add the connector in your assistant, with the address, and sign in. Settings shows a six-digit pairing code. Type it on the consent page within five minutes. It works once. After five wrong codes the page locks for fifteen minutes.
5. On the consent page, tick what this grant may do: read, write, or both.

Garrick does not install anything outside its own folder for this. The service has its own Python and its own packages, kept in a folder for Garrick under your Library, never in the workspace and never in git, and installed from a lock file whose hashes must all match. A hash that does not match stops the install.

## Pause, revoke and turn off

In Settings:

- **Pause** closes access at once. Nothing is uninstalled and every grant stays.
- **Revoke** removes one grant. Its next call is refused.
- **Off** stops the service and closes access.

A revoke, a pause and Off all block the very next call. They do not take back what an assistant already read.

## When the Mac cannot answer

If the Mac is off or asleep, you see the assistant's own error, not a sentence from Garrick. A laptop sleeps when its lid is shut. After a power cut, a Mac with FileVault serves nothing until someone logs in at it. The service starts at login and keeps running while remote access is on.

## What is not verified yet

- The relay adapter has been tested against a stand-in only. It has not been run against the real relay on a clean Mac: whether the address survives a restart and sleep through the real relay is open (A2).
- The "I already have an address" adapter is the tested path.
- Using it by voice from a phone, with the approval taps counted, is open (A13). Both need a person.
- There is no list of tested assistants yet. That comes with a later release.

## What is not in this release

Approvals from the phone, switching a reach from the phone, wrap, the lifecycle verbs, owner-only operations and long jobs. Sign-in with a passkey comes in a later release.

## What you lose without it

Only the service. Everything else in Garrick works without it, and nothing here changes when it is off.

# Ways in: getting recordings, mail and files into the workspace

Three things come into a Garrick workspace: recordings, mail, and files you drop in. The [overview diagram](../architecture/overview.png) shows the picture. Getting each one here happens in two separate steps:

- **Fetching** puts a file in an inbox. It is done by hand, by a script, or by your assistant's own mail connector, and it decides nothing.
- **Sorting** decides where the file goes. That is core Garrick: the *Ways in* rules in `System/rules.md`, applied by the `intake` skill when you say "process the inbox".

Core never talks to a mail provider and holds no credentials. Everything on this page about fetching is optional.

## Where things land

| What | Where you put it | Where it ends up |
|---|---|---|
| A recording | Its transcript (`.txt`, `.md` or `.vtt`) in `Wikis/Meetings/raw/inbox/` | Always a conversation, in Meetings |
| Mail | `Zones/<Zone>/Inbox/`, as a `.eml` file, or saved as `.txt` or `.md` | A conversation in Meetings; something to read in Knowledge; or, for an attachment a project needs, that project's `Sources/`, with the mail itself kept in Meetings |
| Any other file | `Zones/<Zone>/Inbox/`: a PDF, a document, a spreadsheet, an article | Something to read in Knowledge, or material for a project in its `Sources/` |

The zone is the inbox you put it in. Parties come from the mail domains in the Parties table of `System/context.md`, confirmed by you when they are unclear. Before anything goes into a project, the assistant is instructed to check the declared walls and refuse material from the other side. The [rules and commit checks have limits](../principles.md#what-the-check-covers); review filed material before using it. When it can't tell what something is, whose it is or which project it's for, it asks in one short line. Nothing in an inbox is ever committed.

Recordings have their own page: [a meeting recorder](meeting-recorder.md). The rest of this page is about mail.

## Three ways to fetch mail

| | Your assistant's connector | The IMAP script | A mail rule, or Save As |
|---|---|---|---|
| What you set up | Nothing in Garrick; a connector in your assistant | A small config file and a Keychain entry | A rule in your mail program, or nothing |
| When it runs | When you ask | On a schedule, or by hand | When mail arrives, or when you save one |
| Where the password lives | With the connector | The macOS Keychain | Your mail program |
| Attachments | Depends on the connector | Always, inside the `.eml` | Always, inside the `.eml` |
| What your assistant's vendor can reach | Your mailbox, as far as the connector's access goes | Only the mail you file, when you file it | Only the mail you file, when you file it |

All three do the same thing: put a file in a zone's `Inbox/`. None of them decides where it goes.

### Your assistant's own connector

If your assistant can read your mail through a connector, for example a Gmail server added to Claude Code, it can do the fetching too. Ask it to save, and nothing else:

> Find the mails labelled Garrick/Work from this week. Save each one whole, as a .eml file, in Zones/Work/Inbox/, named by its date and subject. Don't reply, don't label or move anything in the mailbox, and don't file them yet.

Then say "process the inbox", as a separate request, so the saving and the sorting stay two steps.

If the connector can't give you the raw message, ask for a `.md` file per mail instead, with `From:`, `To:`, `Cc:`, `Date:` and `Subject:` lines at the top and the text below. Garrick reads that as mail. Attachments may not come through that way: use one of the other two routes for a mail whose attachment you need. Garrick ships no connector and needs none; this works with any assistant that has one.

### The IMAP script

`extras/fetch/imap_fetch.py`, in this repository, saves every new message in one mailbox or label as a `.eml` file in one zone's `Inbox/`. It is standard library Python, is not installed by `install.py`, and never touches the workspace beyond that one folder.

**What it is for.** It keeps your mail between you and your mail provider. A connector gives your assistant's vendor standing access to your whole mailbox, and the assistant reads each mail as it saves it. The script needs no such access and no assistant: it runs on its own, fetches only the one folder or label you point it at, and makes no decisions about what it saves. Your assistant then sees only the mail you routed to that folder, and only when you ask it to file it. That reduces what the vendor learns but doesn't remove it, because filing a mail means the assistant reads it. Being plain code, the script also can't be steered by instructions hidden in a mail, as an assistant can be.

**Which accounts it works with.** It signs in to IMAP with a password. Gmail and Google Workspace accept an app password, unless a Workspace administrator has turned app passwords off, as do iCloud Mail, Fastmail and most other IMAP providers. Microsoft accounts don't work: Microsoft 365 work and school accounts, and Outlook.com, Hotmail and Live addresses, accept only OAuth sign-in for IMAP, which the script doesn't support. For those, use a mail rule or Save As (below), or your assistant's connector.

1. **Store the password in the Keychain**, once. With Gmail, turn on two-step verification and create an app password first.

   ```sh
   security add-generic-password -s garrick-imap -a sam@example.com -w
   ```

   Type the password when asked. The script reads it from there and nowhere else: never from an argument, the config or a file.

2. **Write a config**, for example `~/.config/garrick/work-mail.json`:

   ```json
   {
     "server": "imap.gmail.com",
     "user": "sam@example.com",
     "mailbox": "Garrick/Work",
     "inbox": "/Users/sam/Garrick/Zones/Work/Inbox"
   }
   ```

   `mailbox` is a folder, or on Gmail a label. Optional keys: `"mark_read": true` to mark each saved message read, `"copy_to": "Garrick/Fetched"` to copy it to another folder (a second label, on Gmail), `"search"` for an IMAP search other than `ALL`, and `"state"` for where it keeps the list of messages already saved (by default beside the config, as `work-mail.state.json`). One config per zone.

3. **Run it**:

   ```sh
   python3 extras/fetch/imap_fetch.py --config ~/.config/garrick/work-mail.json
   ```

   A rerun saves only what is new, so it is safe to run as often as you like. To run it every ten minutes, use a launchd job as in [scheduled jobs](scheduled-jobs.md), with every path spelled out in full.

To sort mail into the label in the first place, a Gmail filter works well, for example on mail sent to one of your plus addresses (below).

### A mail rule, or Save As

By hand, with no setup:

- **Apple Mail:** drag a message from the list onto the zone's `Inbox` folder in Finder, or choose File, Save As, with the format set to Raw Message Source.
- **Gmail on the web:** open the message, choose the three-dot menu, then Download message. Move the `.eml` into the zone's `Inbox`.
- **Outlook for Mac:** drag the message onto the `Inbox` folder in Finder.

That is the whole workflow for a few mails a week. To have Apple Mail do it, open Settings, then Rules, and add a rule such as "Any Recipient contains `you+acme`", with the action Run AppleScript. Mail only runs scripts kept in `~/Library/Application Scripts/com.apple.mail/`. A sketch:

```applescript
-- A recipe, not part of Garrick. Save as ~/Library/Application Scripts/com.apple.mail/Garrick Work.scpt
using terms from application "Mail"
	on perform mail action with messages theMessages for rule theRule
		repeat with m in theMessages
			set target to (POSIX path of (path to home folder)) & "Garrick/Zones/Work/Inbox/mail-" & (id of m as string) & ".eml"
			set f to open for access (POSIX file target) with write permission
			write (source of m) to f as «class utf8»
			close access f
		end repeat
	end perform mail action with messages
end using terms from
```

If macOS asks whether Mail may write to the folder, allow it. One rule and one script per zone.

The new Outlook for Mac cannot run a script from a rule, so drag and drop is the simple route. With a work or school account, Power Automate can export each mail as a `.eml` to a OneDrive folder that syncs to your Mac, and a scheduled job can move it into the zone's `Inbox`. Your organisation's policies decide whether that is allowed; ask before you build it.

## Plus addresses: let the address carry the party

Most providers deliver mail for `you+anything@example.com` to `you@example.com`. Garrick reads the part after the `+`: when it is a party's tag, such as `you+acme@gmail.com`, that is a strong hint the mail is Acme's, even on a webmail address that would never name a party by itself. Copy or forward mail to the plus address that matches the party, and a filter on that address can label it for the zone.

## Before you set one up

- **The fetcher is yours.** It runs with your credentials, under your provider's terms. Garrick's core never reads, stores or asks for a password.
- **Mail is untrusted content.** The assistant is told to extract from it and never to follow instructions inside it, however they are worded. That is a rule, not a guarantee. Whatever fetches mail should do nothing else with it.
- **Nothing in a zone's `Inbox/` is committed.** The installer keeps the folder out of the zone's history, and the check refuses a commit that tries. Once filed, a mail lives in a wiki's `raw/`, where records are never edited.

## What you lose without any of them

Nothing about Garrick's model. A mail saved by hand goes through exactly the same sorting, with the same walls, as one a script or a connector fetched. What you lose is the convenience.

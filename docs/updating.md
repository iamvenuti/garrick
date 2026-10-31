# Updating Garrick

Your workspace is a copy of Garrick, made on the day you installed it. A newer Garrick doesn't reach it on its own. You bring it in, and nothing you changed is lost on the way.

## The short version

From your workspace's folder:

```sh
python3 System/tools/release.py update            # download the newest release; say what would change
python3 System/tools/release.py update --apply    # do it
```

Or ask your assistant: "update Garrick". It runs the same command, tells you what would change, and changes it when you say yes.

On a Mac whose `python3` comes from python.org, run it as `/usr/bin/python3 System/tools/release.py update`: python.org's Python has no certificates until you run *Install Certificates.command* in its folder under `/Applications`. Without them, `release.py` fetches through `curl` instead and says so; if `curl` fails too, it tells you which of the two to do.

`release.py update` asks GitHub for the newest release, downloads it into a temporary folder outside your workspace, and runs that release's own update on your workspace. The temporary folder is removed afterwards. When the workspace already runs the newest release, it says so and downloads nothing. `--tag v0.16.0` takes a release other than the newest, but never one older than the workspace runs: that would take your files back. A workspace that follows `main` ahead of its release is updated from `main` by hand, below.

To do the same by hand, get the newer Garrick yourself: download [garrick.zip](https://github.com/iamvenuti/garrick/releases/latest/download/garrick.zip) from the latest release and unzip it, or `git pull` in your clone. Keep it outside your workspace: an update refuses to run from a Garrick inside the workspace it would update. Then, from your workspace's folder:

```sh
python3 ~/Downloads/garrick/install.py --update .            # what would change; changes nothing
python3 ~/Downloads/garrick/install.py --update . --apply    # do it
```

A workspace from before `release.py` has to take that way once.

## Being told a newer Garrick is out

Off until you switch it on, because it is the only call Garrick makes on its own. The `setup` skill offers it once; to switch it on yourself, write this in `System/garrick-settings.json` and commit it:

```json
{"release-notice": true}
```

Then each time the [Garrick App](extras/status-page.md) is built, it checks when GitHub was last asked. Once a day at most, it starts `release.py latest` in a process of its own and builds the page without waiting for it. When the answer names a newer release, *Needs attention* says so from the next build on: "Garrick 0.16.0 is out; this workspace runs 0.15.2", with the command that updates, and the line links to that release's notes. `python3 System/tools/check.py --version` adds the same line. Neither asks GitHub itself: they read the last answer, kept in `System/generated/garrick-release.json`, which is never committed. Without the Garrick App, run `python3 System/tools/release.py latest` when you want to know; it asks at most once a day, or now with `--now`.

What goes over the wire is one HTTPS request: a GET to `api.github.com/repos/iamvenuti/garrick/releases/latest`, with a User-Agent header that says `Garrick/` and the release your workspace runs, such as `Garrick/0.15.2`. Nothing about your workspace is sent: no file, name, path or setting. GitHub sees the request come from your address, as it does any web page you open. If the request fails, because you are offline or GitHub is slow, nothing shows and nothing turns red; it asks again the next day.

The release your workspace runs is the newest one named in `System/garrick-changelog.md`, the copy of the release notes the installer put there and each update replaces. A workspace that follows `main` ahead of a release is told only of a later one.

A fork can ask its own repository instead: add `"release-repository": "<owner>/<name>"` to the same file. `release.py update` then downloads from there too.

### Whose code you run

`release.py update` downloads the source archive GitHub makes for the release's tag, from the same repository the release notice asks, and runs that release's `install.py --update`. That is the code you would get by downloading the ZIP from the Releases page yourself: you trust it as much as you trusted the copy you installed from. Without `--apply` it writes nothing: it reports what it would change, and you read the report before you run it again with `--apply`. The archive is unpacked into a temporary folder outside the workspace, refused if any path in it would land outside that folder or is a link, and removed when the update ends.

## What it does with each file

When Garrick installed your workspace it recorded a fingerprint of every file it wrote, in `System/garrick-version.json`. The update compares each file with that fingerprint, with every earlier Garrick release, and with the newer version, and puts it in one of these groups:

| Group | What it is | What `--apply` does |
|---|---|---|
| Replace | A file still exactly as some Garrick wrote it, with a newer version | Replaces it |
| Add | A file new in this Garrick | Adds it |
| Merge | A file you changed that Garrick has changed too | Writes Garrick's version beside it as `<name>.new` and commits it. Yours is not touched |
| Split | One of Garrick's instruction files, `System/rules.md` or an `AGENTS.md`, that you changed | Nothing, and no `.new`. Your text belongs in the local file beside it: `--split` moves it there, below |
| Yours | A starting file you have filled in since, such as a zone's `Todo.md` or a wiki's log | Nothing, now or later |
| Removed by you | A file Garrick still ships that you deleted | Nothing, unless you name it with `--only` |
| Retired | A file Garrick no longer ships | Nothing. Delete it yourself if you want it gone |

A file you changed that Garrick hasn't changed stays as you left it and isn't listed, unless it is one of Garrick's instruction files. `System/context.md`, your own answers, is never read or written, and neither is a local file beside an instruction file, such as `System/rules.local.md`.

## Your rules, and Garrick's

`System/rules.md` and every `AGENTS.md`, at the root, in each zone and in each wiki, are Garrick's. An update replaces them as it replaces Garrick's code, and the `update` skill tells you what changed in the rules, one line per rule. Your own rules and routing go in the local file beside each, which no update writes:

| Garrick's | Yours |
|---|---|
| `System/rules.md` | `System/rules.local.md`, which the installer starts with a heading and no rules |
| `AGENTS.md`, in the root, a zone or a wiki | `AGENTS.local.md` beside it, made when you first need it |

Each of Garrick's files says near its top to read the local one next. The local one adds to it, and wins where the two differ: to change one of Garrick's rules, write your own under the same heading in `rules.local.md`. Say "add a rule" and the `setup` skill writes it there for you.

Garrick's files leave the local ones to be read by instruction, as they leave `System/rules.md` itself: the root `AGENTS.md`, which both assistants load on their own, names both, and so does each zone's and wiki's `AGENTS.md`, for an assistant that stops at a repository's edge. [Claude Code and Codex](harnesses.md#your-own-instructions-beside-garricks) says why, and what has been tested.

### Your own ignore lines

A `.gitignore` cannot have a local file beside it, so Garrick's lines in each one it writes, at the root, in `Wikis/`, in each zone and in the zone template, sit between two markers:

```
# >>> Garrick manages the lines below; an update replaces them
...
# <<< Garrick
```

Put your own lines anywhere outside the markers. An update replaces what is between them, never reads the rest, and never leaves a `.new` for the file. A `.gitignore` from before the markers gets the block at the top on its next update, with every line of yours after it; a line exactly like one of Garrick's is dropped, since the block now holds it. `check.py` warns when the lines between the markers differ from Garrick's, since the next update would put Garrick's back.

### Moving your text out

A workspace from before the split, or one whose instruction file you edited since, has your text mixed into Garrick's. The update lists such a file under *Split* and leaves it as it is. Then:

```sh
python3 System/tools/release.py update --split            # what would move; changes nothing
python3 System/tools/release.py update --split --apply    # do it
```

Or, from a newer Garrick you downloaded, `python3 <the newer Garrick>/install.py --update . --split`, with `--apply` and `--only` as for an update. Or say "split my rules".

For each file it finds the Garrick version your file grew from in its git history, or in the history of a `.new` beside it, and compares the three. Then:

- Garrick's file is written as this Garrick ships it. A change Garrick made since, to a passage you left alone, is simply taken.
- A passage you added moves into the local file, under the heading it sat under, which is added when the local file lacks it.
- A passage where you changed or removed Garrick's own text cannot move on its own. The report lists each one, numbered, with both wordings, for you to settle one at a time. Your wording goes into the local file under *From your earlier rules.md, to review* (or *AGENTS.md*), where it still holds until you settle it, and Garrick's is named there by its opening words. Keep yours, take Garrick's or write it afresh; the `update` skill goes through them with you. `check.py` warns until that section is gone.

Nothing you wrote is lost: every line of your file that is not Garrick's ends up in the local file, and one that cannot be placed under a heading goes under the review heading as it is. A fenced code block counts as one passage: it moves whole, and a block you changed is settled whole, its fences included. When no Garrick version is in the file's history, as in a workspace laid out before it took Garrick's files, all that differs from this Garrick's counts as yours, and the report says so. A `.new` an earlier update left beside the file is removed in the same commit, since Garrick's file is as shipped now. Each repository gets one commit, which `git revert` undoes.

## Extras

The extras that live in your workspace are updated with the rest, when they are there:

| Extra | In your workspace |
|---|---|
| [The Garrick App](extras/status-page.md), its Mac app and its Obsidian plugin | `System/status/` |
| [Scheduled jobs](extras/scheduled-jobs.md) | `System/jobs/` |
| [desk, for cmux](extras/cmux.md) | `System/cmux/`, and its skill in `System/skills/desk/` |

An extra counts as installed when one of its folders is there. Its files go through the same groups as the rest: one you have not changed is replaced, one you changed gets a `.new` beside it, and a file the extra has gained is added. The report names the extras it found.

After the files, the update does what an extra needs next, and the report lists each step before you apply:

- **The Mac app.** When the app's code changed, it builds `Garrick.app` again with `System/status/app/make-app.sh`, in the folder it is in now and with the flags you built it with, which the app keeps in its own settings. On a Mac, and only for an app built for this workspace. If you changed the app's code yourself, it says to merge the `.new` first and rebuild by hand.
- **The Garrick App.** When anything in `System/status/` changed, it builds `System/generated/status.html` again once every file is in place, with the flags the app was built with, or none without an app, so the page on screen is never the replaced code's. Only where there is a page or an app to rebuild. If you changed a file there yourself, it says to merge the `.new` first.
- **The Obsidian plugin.** In every vault inside the workspace that has `.obsidian/plugins/garrick-status/`, it copies in the newer `main.js` and `manifest.json`, and commits them where git keeps them. A copy you changed yourself is left as it is, and named. Then switch the plugin off and on in Obsidian, or restart it.
- **The desk command.** When `desk` on your PATH is a link to a `desk.py` somewhere else, such as an older download, it points the link at the workspace's `System/cmux/desk.py`, which the update keeps current.
- **Scheduled jobs under their old names.** Your launchd plists in `~/Library/LaunchAgents` are yours, so the update never changes them. When one runs a job of Garrick's for this workspace under the name it had before 0.49.0, such as `nurture` or `backup`, the report names the plist and prints the commands that unload it, rename it and load it again, for you to run in Terminal. Each is safe to run again, and a plist left part way through is reported again with what is left. Until you do, it keeps working as it is. See [Garrick's jobs and yours](extras/scheduled-jobs.md#garricks-jobs-and-yours).

The [zone guard](../extras/hooks/README.md) and the [Garrick band](../extras/mods/README.md) run from a Garrick you keep outside the workspace, so the update does not change them. When your assistant's settings point at a copy that differs from the newer Garrick's, the report says which, so you can point them at a newer copy you keep.

The mail fetcher in `extras/fetch/` is not copied into a workspace, so it is not updated either.

To take only some of the changes, name them as the report lists them:

```sh
python3 System/tools/release.py update --apply --only "System/tools/check.py,System/skills/intake/SKILL.md"
```

## Merging a `.new` file

An instruction file of Garrick's never gets one: see [Your rules, and Garrick's](#your-rules-and-garricks).

Say "merge the update" to your assistant. The `update` skill finds the version Garrick wrote before, merges your changes and Garrick's together with git, shows you what Garrick changed, and asks you about any passage you both changed. Until you merge, the check warns that a `.new` file is waiting.

To do it by hand, compare the file with its `.new`, edit the file, then `git rm` the `.new` and commit the two together.

The `.new` is committed, so a `git clean` or a fresh clone keeps it until you merge. Once it is written, the update counts that version as offered. Merge it, take part of it or remove it unread: the next update leaves the file alone, and offers it again only when a newer Garrick changes it again. Commit the removal: the next merge starts from it.

## Undoing it

Each repository the update touched has one commit of its own, `Garrick: update to <version>`, holding only the files the update wrote, `.new` files included. `git revert` that commit in that repository and the files are back as they were, and the `.new` files are gone.

## What it won't do

- Delete anything.
- Commit changes you haven't committed yourself. If a file it would replace has uncommitted changes, it skips that file and says so.
- Write through a symbolic link, or outside the workspace, except the two steps the report names first: the Mac app it rebuilds, and the `desk` link it points at the workspace's copy.
- Fetch anything itself. `install.py --update` compares two folders on your Mac. `release.py update` is what downloads, and only when you run it.

The version stamp changes last, once everything you picked has been applied and the workspace check finds no error in the files the update wrote. `python3 System/tools/check.py --version` then names the newer Garrick and the one you updated from. Running the update twice changes nothing the second time.

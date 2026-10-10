# Updating Garrick

Your workspace is a copy of Garrick, made on the day you installed it. A newer Garrick doesn't reach it on its own. You bring it in, and nothing you changed is lost on the way.

## The short version

From your workspace's folder:

```sh
python3 System/tools/release.py update            # download the newest release; say what would change
python3 System/tools/release.py update --apply    # do it
```

Or ask your assistant: "update Garrick". It runs the same command, tells you what would change, and changes it when you say yes.

`release.py update` asks GitHub for the newest release, downloads it into a temporary folder outside your workspace, and runs that release's own update on your workspace. The temporary folder is removed afterwards. When the workspace already runs the newest release, it says so and downloads nothing. `--tag v0.16.0` takes a release other than the newest, but never one older than the workspace runs: that would take your files back. A workspace that follows `main` ahead of its release is updated from `main` by hand, below.

To do the same by hand, get the newer Garrick yourself: download the ZIP from the [latest release](https://github.com/iamvenuti/garrick/releases/latest) and unzip it, or `git pull` in your clone. Keep it outside your workspace: an update refuses to run from a Garrick inside the workspace it would update. Then, from your workspace's folder:

```sh
python3 ~/Downloads/garrick-main/install.py --update .            # what would change; changes nothing
python3 ~/Downloads/garrick-main/install.py --update . --apply    # do it
```

A workspace from before `release.py` has to take that way once.

## Being told a newer Garrick is out

Off until you switch it on, because it is the only call Garrick makes on its own. The `setup` skill offers it once; to switch it on yourself, write this in `System/garrick-settings.json` and commit it:

```json
{"release-notice": true}
```

Then each time the [status page](extras/status-page.md) is built, it checks when GitHub was last asked. Once a day at most, it starts `release.py latest` in a process of its own and builds the page without waiting for it. When the answer names a newer release, *Needs attention* says so from the next build on: "Garrick 0.16.0 is out; this workspace runs 0.15.2", with the command that updates, and the line links to that release's notes. `python3 System/tools/check.py --version` adds the same line. Neither asks GitHub itself: they read the last answer, kept in `System/generated/garrick-release.json`, which is never committed. Without the status page, run `python3 System/tools/release.py latest` when you want to know; it asks at most once a day, or now with `--now`.

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
| Yours | A starting file you have filled in since, such as a zone's `Todo.md` or a wiki's log | Nothing, now or later |
| Removed by you | A file Garrick still ships that you deleted | Nothing, unless you name it with `--only` |
| Retired | A file Garrick no longer ships | Nothing. Delete it yourself if you want it gone |

A file you changed that Garrick hasn't changed stays as you left it and isn't listed. `System/rules.md` is always merged and never replaced, even if you never edited it, because it decides how your assistant behaves and you should see each change to it. `System/context.md`, your own answers, is never read or written.

## Extras

The extras that live in your workspace are updated with the rest, when they are there:

| Extra | In your workspace |
|---|---|
| [Status page](extras/status-page.md), its Mac app and its Obsidian plugin | `System/status/` |
| [Scheduled jobs](extras/scheduled-jobs.md) | `System/jobs/` |
| [desk, for cmux](extras/cmux.md) | `System/cmux/`, and its skill in `System/skills/desk/` |

An extra counts as installed when one of its folders is there. Its files go through the same groups as the rest: one you have not changed is replaced, one you changed gets a `.new` beside it, and a file the extra has gained is added. The report names the extras it found.

After the files, the update does what an extra needs next, and the report lists each step before you apply:

- **The Mac app.** When the app's code changed, it builds `Garrick.app` again with `System/status/app/make-app.sh`, in the folder it is in now and with the flags you built it with, which the app keeps in its own settings. On a Mac, and only for an app built for this workspace. If you changed the app's code yourself, it says to merge the `.new` first and rebuild by hand.
- **The Obsidian plugin.** In every vault inside the workspace that has `.obsidian/plugins/garrick-status/`, it copies in the newer `main.js` and `manifest.json`, and commits them where git keeps them. A copy you changed yourself is left as it is, and named. Then switch the plugin off and on in Obsidian, or restart it.
- **The desk command.** When `desk` on your PATH is a link to a `desk.py` somewhere else, such as an older download, it points the link at the workspace's `System/cmux/desk.py`, which the update keeps current.

The [zone guard](../extras/hooks/README.md) and the [Garrick band](../extras/mods/README.md) run from a Garrick you keep outside the workspace, so the update does not change them. When your assistant's settings point at a copy that differs from the newer Garrick's, the report says which, so you can point them at a newer copy you keep.

The mail fetcher in `extras/fetch/` is not copied into a workspace, so it is not updated either.

To take only some of the changes, name them as the report lists them:

```sh
python3 System/tools/release.py update --apply --only "System/tools/check.py,System/skills/intake/SKILL.md"
```

## Merging a `.new` file

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

# Updating Garrick

Your workspace is a copy of Garrick, made on the day you installed it. A newer Garrick doesn't reach it on its own. You bring it in, and nothing you changed is lost on the way.

## The short version

1. Get the newer Garrick: download the ZIP from the [latest release](https://github.com/iamvenuti/garrick/releases/latest) and unzip it, or `git pull` in your clone.
2. In your workspace, ask your assistant: "update Garrick from ~/Downloads/garrick-main" (wherever the newer one is).
3. It tells you what would change, and changes it when you say yes.

Or run it yourself, from your workspace's folder:

```sh
python3 ~/Downloads/garrick-main/install.py --update .            # what would change; changes nothing
python3 ~/Downloads/garrick-main/install.py --update . --apply    # do it
```

## What it does with each file

When Garrick installed your workspace it recorded a fingerprint of every file it wrote, in `System/garrick-version.json`. The update compares each file with that fingerprint, with every earlier Garrick release, and with the newer version, and puts it in one of these groups:

| Group | What it is | What `--apply` does |
|---|---|---|
| Replace | A file still exactly as some Garrick wrote it, with a newer version | Replaces it |
| Add | A file new in this Garrick | Adds it |
| Merge | A file you changed that Garrick has changed too | Writes Garrick's version beside it as `<name>.new`. Yours is not touched |
| Yours | A starting file you have filled in since, such as a zone's `Todo.md` or a wiki's log | Nothing, now or later |
| Removed by you | A file Garrick still ships that you deleted | Nothing, unless you name it with `--only` |
| Retired | A file Garrick no longer ships | Nothing. Delete it yourself if you want it gone |

A file you changed that Garrick hasn't changed stays as you left it and isn't listed. `System/rules.md` is always merged and never replaced, even if you never edited it, because it decides how your assistant behaves and you should see each change to it. `System/context.md`, your own answers, is never read or written.

To take only some of the changes, name them as the report lists them:

```sh
python3 ~/Downloads/garrick-main/install.py --update . --apply --only "System/tools/check.py,System/skills/intake/SKILL.md"
```

## Merging a `.new` file

Say "merge the update" to your assistant. The `update` skill finds the version Garrick wrote before, merges your changes and Garrick's together with git, shows you what Garrick changed, and asks you about any passage you both changed. Until you merge, the check warns that a `.new` file is waiting.

To do it by hand, compare the file with its `.new`, edit the file, then delete the `.new`.

## Undoing it

Each repository the update touched has one commit of its own, `Garrick: update to <version>`, holding only the files the update wrote. `git revert` that commit in that repository and the files are back as they were. The `.new` files are never committed; delete them.

## What it won't do

- Delete anything.
- Commit changes you haven't committed yourself. If a file it would replace has uncommitted changes, it skips that file and says so.
- Write through a symbolic link, or outside the workspace.
- Fetch anything. It compares two folders on your Mac. Checking for a newer Garrick is up to you.

The version stamp changes last, once everything you picked has been applied and the workspace check finds no error in the files the update wrote. `python3 System/tools/check.py --version` then names the newer Garrick and the one you updated from. Running the update twice changes nothing the second time.

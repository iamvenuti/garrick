# Garrick

Instructions for any assistant working on this repository. This is the source of Garrick, not a Garrick workspace: `template/` is what an installer copies onto a user's machine, and everything else supports it.

## Layout

| Path | Holds |
|---|---|
| `template/` | The workspace a user gets. Copied, then filled in by the installer |
| `template/System/rules.md` | How an assistant behaves in an installed workspace. Garrick's only copy; a workspace's own rules go in `System/rules.local.md`, which the installer starts from `template/System/rules.local.md` and never lists or updates |
| `template/System/context.md` | Who the user is and who they deal with. Filled in at install |
| `template/System/templates/` | The zone, project and thread templates. The installer makes one copy of `zone/` per zone the user names; `System/tools/scaffold.py` fills all three later |
| `template/System/tools/` | `scaffold.py`, `check.py` and the library they share, `garrick_lib.py`; `correct.py`, which stops a wrong value everywhere it was written; `example.py`, which puts the worked example away and brings it back; `release.py`, the one tool that reaches the network, only when asked or switched on; `notifications.py`, every notice Garrick sends, to this Mac; `discover.py`, which proposes the pieces of work in a folder the user keeps, from names and dates alone, and `extract.py`, which takes the text out of their Office files; neither writes in that folder |
| `template/System/skills/` | Skills, one folder each. The installer links them for every assistant |
| `template/Wikis/` | The two memories: `Meetings/` and `Knowledge/` |
| `install.py` | The installer. `examples/acme.json` is a complete fictional config |
| `update.py` | `install.py --update`: brings an installed workspace up to this Garrick. Runs from the newer download, never from the workspace; `System/tools/release.py update` downloads a release and runs it. Updates the extras a workspace has copied in, too |
| `split.py` | `install.py --update --split`: moves a workspace's own text out of Garrick's instruction files, `System/rules.md` and each `AGENTS.md`, into the local file beside each (`rules.local.md`, `AGENTS.local.md`), and puts Garrick's back as shipped |
| `release-hashes.json` | The fingerprint of every file each tagged release shipped, and each release's zone template, so an update knows a file still as an older Garrick wrote it. *Releasing* has the step that rewrites it; a test fails until the result is committed |
| `VERSION` | Which commit a download is: git fills in its lines when GitHub serves a ZIP (`export-subst`). The installer copies the answer into the workspace's `System/garrick-version.json` |
| `examples/demo/` | The demo workspace. `build.py` installs it and replays a month of invented work from `content/` |
| `examples/example-work/` | The worked example: one person's ordinary work, a zone of its own with a shared drive beside it. `build.py` builds it with dates relative to today, into a new workspace or one already installed; `install.py --example` adds it, and `System/tools/example.py` archives and restores it |
| `extras/` | Optional tools outside core: the mail fetcher, scheduled jobs, and the status page with its Mac app. None is installed except the status page, which the installer puts in place for the simple home; `EXTRAS` in `install.py` says where each goes in a workspace |
| `docs/` | The user documentation. `docs/extras/` covers the extras |
| `presentation/` | The introduction deck, one HTML file |
| `tests/` | `python3 -m unittest discover -s tests` |

## Placeholders

- `{{UPPER_CASE}}` is filled by a script. The installer fills `{{ZONE}}` in `template/System/templates/zone/`, once per zone. `System/tools/scaffold.py` fills `{{ZONE}}`, `{{PROJECT}}`, `{{THREAD}}`, `{{PARTY}}` and `{{DATE}}` in `template/System/templates/` when a project or a thread is started, and `{{ZONE}}` for a zone added later.
- `<angle brackets>` are filled by the user, or by their assistant on their behalf.

Never leave a third kind. A file no script can finish and the user cannot recognise as theirs to fill is a broken install.

## Releasing

With the notes for the new version written in `CHANGELOG.md` and the work on `main`, review what the release carries before you tag it: `git diff v<last>..main`, read for correctness and for any way past the wall check. A release adds code nobody has read as a whole, and 0.45.0 shipped a way past the wall check that a review of the next two releases found. A finding goes to an issue, or, when it is a way past the wall check, to a private advisory as `SECURITY.md` says, and is fixed before the tag.

Then, from a clone:

```sh
git tag -a v0.25.0 -m "Garrick 0.25.0"
python3 update.py --release-hashes
git add release-hashes.json
git commit -m "Release hashes for 0.25.0"
git push origin main v0.25.0
git archive --format=zip --prefix=garrick/ -o /tmp/garrick.zip v0.25.0
gh release create v0.25.0 /tmp/garrick.zip --title "Garrick 0.25.0" --notes-file <release-notes.md>
```

Put the version in place of `v0.25.0` throughout. `--release-hashes` reads the clone's tags, so it runs once the tag exists, and the commit it produces lands after the tag, on `main`; a test fails until that commit is made.

`garrick.zip` is the asset beginners download, and three things about it are fixed:

- **Built from the tag**, not the working tree, so git substitutes `VERSION`'s `$Format:%h$` through `export-subst` and a workspace installed from it stamps the release's commit.
- **`--prefix=garrick/`**, so the download unpacks into a folder called `garrick`, the one the beginner pages tell people to `cd` into.
- **Named `garrick.zip`**, because the docs send people to `https://github.com/iamvenuti/garrick/releases/latest/download/garrick.zip`, which GitHub resolves by asset name. `latest` follows the newest release, so a release published without the asset breaks that link for everyone.

To add it to a release already published, `gh release upload v0.25.0 /tmp/garrick.zip`, or drag the file onto the release page. `tests/test_docs.py` holds the asset name and the folder against what the docs tell people to download.

## Rules for this repository

- **Clean room.** Nothing here comes from a real workspace. Examples use invented parties only (Acme Corp, Birch & Co, and people invented to go with them). No real person, company, client, rate or document, ever, in a file or a commit message. The one exception is the maintainer's own name: it stands in `LICENSE`, in the deck's byline and in commit metadata, and as the handle in the repository's address.
- **Harness-neutral.** Nothing in `template/` depends on one assistant. The entry point is `AGENTS.md`. The only per-assistant pieces are the skill links the installer makes (`.claude/skills`, `.agents/skills`); keep it that way.
- **Fixed three levels.** Zone, project, thread. Do not add a configurable depth: the voice grammar depends on it.
- **A rule a machine can check gets a check** in the same commit, once the checker exists.
- **A test never reads this Mac.** A test that asserts what the page offers, or what a launcher says, builds its own app bundles and sets its own card fields. Anything that consults the machine passes on one and fails on another.
- **Voice is a design constraint, not a feature.** Any name, prompt or reply format added here has to work when spoken and when heard.

# Garrick

Instructions for any assistant working on this repository. This is the source of Garrick, not a Garrick workspace: `template/` is what an installer copies onto a user's machine, and everything else supports it.

## Layout

| Path | Holds |
|---|---|
| `template/` | The workspace a user gets. Copied, then filled in by the installer |
| `template/System/rules.md` | How an assistant behaves in an installed workspace. The only copy |
| `template/System/context.md` | Who the user is and who they deal with. Filled in at install |
| `template/System/templates/` | The zone, project and thread templates. The installer makes one copy of `zone/` per zone the user names; `System/tools/scaffold.py` fills all three later |
| `template/System/tools/` | `scaffold.py`, `check.py` and the library they share, `garrick_lib.py` |
| `template/System/skills/` | Skills, one folder each. The installer links them for every assistant |
| `template/Wikis/` | The two memories: `Meetings/` and `Knowledge/` |
| `install.py` | The installer. `examples/acme.json` is a complete fictional config |
| `VERSION` | Which commit a download is: git fills in its lines when GitHub serves a ZIP (`export-subst`). The installer copies the answer into the workspace's `System/garrick-version.json` |
| `examples/demo/` | The demo workspace. `build.py` installs it and replays a month of invented work from `content/` |
| `extras/` | Optional tools outside core, never installed: the mail fetcher, scheduled jobs, and the status page with its Mac app |
| `docs/` | The user documentation. `docs/extras/` covers the extras |
| `presentation/` | The introduction deck, one HTML file |
| `tests/` | `python3 -m unittest discover -s tests` |

## Placeholders

- `{{UPPER_CASE}}` is filled by a script. The installer fills `{{ZONE}}` in `template/System/templates/zone/`, once per zone. `System/tools/scaffold.py` fills `{{ZONE}}`, `{{PROJECT}}`, `{{THREAD}}`, `{{PARTY}}` and `{{DATE}}` in `template/System/templates/` when a project or a thread is started, and `{{ZONE}}` for a zone added later.
- `<angle brackets>` are filled by the user, or by their assistant on their behalf.

Never leave a third kind. A file no script can finish and the user cannot recognise as theirs to fill is a broken install.

## Rules for this repository

- **Clean room.** Nothing here comes from a real workspace. Examples use invented parties only (Acme Corp, Birch & Co, and people invented to go with them). No real person, company, client, rate or document, ever, in a file or a commit message. The one exception is the maintainer's own name: it stands in `LICENSE`, in the deck's byline and in commit metadata, and as the handle in the repository's address.
- **Harness-neutral.** Nothing in `template/` depends on one assistant. The entry point is `AGENTS.md`. The only per-assistant pieces are the skill links the installer makes (`.claude/skills`, `.agents/skills`); keep it that way.
- **Fixed three levels.** Zone, project, thread. Do not add a configurable depth: the voice grammar depends on it.
- **A rule a machine can check gets a check** in the same commit, once the checker exists.
- **Voice is a design constraint, not a feature.** Any name, prompt or reply format added here has to work when spoken and when heard.

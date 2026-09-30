# Garrick

Instructions for any assistant working on this repository. This is the source of Garrick, not a Garrick workspace: `template/` is what an installer copies onto a user's machine, and everything else supports it.

## Layout

| Path | Holds |
|---|---|
| `template/` | The workspace a user gets. Copied, then filled in by the installer |
| `template/System/rules.md` | How an assistant behaves in an installed workspace. The only copy |
| `template/System/context.md` | Who the user is and who they deal with. Filled in at install |
| `template/Zones/_zone/` | One zone. The installer makes one copy per zone the user names |
| `template/System/templates/` | The project and thread templates, filled by `System/tools/scaffold.py` |
| `template/System/tools/` | `scaffold.py`, `check.py` and the library they share, `garrick_lib.py` |
| `template/System/skills/` | Skills, one folder each. The installer links them for every assistant |
| `install.py` | The installer. `examples/acme.json` is a complete fictional config |
| `tests/` | `python3 -m unittest discover -s tests` |
| `template/Wikis/` | The two memories: `Meetings/` and `Knowledge/` |

## Placeholders

- `{{UPPER_CASE}}` is filled by the installer: `{{ZONE}}`, `{{PROJECT}}`, `{{THREAD}}`, `{{PARTY}}`, `{{DATE}}`.
- `<angle brackets>` are filled by the user, or by their assistant on their behalf.

Never leave a third kind. A file the installer cannot finish and the user cannot recognise as theirs to fill is a broken install.

## Rules for this repository

- **Clean room.** Nothing here comes from a real workspace. Examples use invented parties only (Acme Corp, Birch & Co, and people invented to go with them). No real person, company, client, rate or document, ever, in a file or a commit message.
- **Harness-neutral.** Nothing in `template/` depends on one assistant. The entry point is `AGENTS.md`. The only per-assistant pieces are the skill links the installer makes (`.claude/skills`, `.agents/skills`); keep it that way.
- **Fixed three levels.** Zone, project, thread. Do not add a configurable depth: the voice grammar depends on it.
- **A rule a machine can check gets a check** in the same commit, once the checker exists.
- **Voice is a design constraint, not a feature.** Any name, prompt or reply format added here has to work when spoken and when heard.

# Contributing

Questions and feedback, including how Garrick worked for you, go to [Discussions](https://github.com/iamvenuti/garrick/discussions).

Garrick is early and run by one person, so the fastest route in is an idea before a pull request. Post it in [Ideas](https://github.com/iamvenuti/garrick/discussions/categories/ideas), saying what you want to change and why; a short answer comes back before you spend an afternoon on code. Ideas taken up become issues labelled `enhancement`. A fix for an open issue needs no idea first.

## Ground rules

- **Clean room.** Every name, company, rate and document in this repository is invented: Acme Corp, Birch & Co, and the people who go with them. Never add real ones, in a file or in a commit message. That includes your own clients, however harmless it seems. The one exception is the maintainer's own name, in `LICENSE`, the deck's byline, commit metadata and the repository's address.
- **Standard library only.** The installer and the tools run on the Python that ships with the macOS Command Line Tools, 3.9. No dependencies.
- **Harness-neutral.** Nothing in `template/` may depend on one assistant. If Claude Code and Codex need different things, the installer makes the difference, not the template.
- **Three levels, fixed.** Zone, project, thread. The voice grammar depends on it.
- **A rule a machine can check gets a check,** in the same pull request.
- **Say it aloud.** Any new name, prompt or reply format has to work when spoken and when heard.

[`AGENTS.md`](AGENTS.md) has the layout and the placeholder rules. If you work with an assistant, it reads that file first.

## Before you open a pull request

```sh
python3 -m unittest discover -s tests
```

The suite takes three to four minutes on the system Python. CI runs it on macOS with the system Python and a current one.

Keep commits small, with a subject line that says what changed.

## Reporting a way through the walls

Not as an issue. See [SECURITY.md](SECURITY.md).

By contributing you agree that your work is released under the [MIT licence](LICENSE) and that you follow the [code of conduct](CODE_OF_CONDUCT.md).

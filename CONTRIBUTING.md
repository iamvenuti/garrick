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

The suite takes three to four minutes on the system Python. CI runs it on macOS with the system Python and a current one, each split into four shards that run side by side, and a job named *Tests* passes only when all eight do. To run one shard as CI does, or see what is in it:

```sh
python3 tests/shard.py 2/4 --jobs 3
python3 tests/shard.py --list 2/4
```

`--jobs 3` runs three modules at a time, each in a process of its own, as CI does; leave it out to run them one after another in one process.

`tests/shard.py` deals the modules out by the times in `tests/shard-times.json`; a new module with no time yet still runs, in the lightest shard. A test that passes in the full run and fails in its shard, or the other way round, depends on what ran before it: fix the test. When the shards drift apart in length, refresh the times from a run's log: `gh run view <run> --log > run.log`, then `python3 tests/shard.py --merge-times run.log`.

Keep commits small, with a subject line that says what changed.

## A decision note

A pull request that adds a heading to `docs/concepts.md`, or changes the first sentence under one, adds a concept, and a concept is decided before it is built. A check on every pull request (`tests/concept_gate.py`) reads the description and fails the merge when such a heading has no decision note linked. A wording fix below an unchanged first sentence needs nothing.

A decision note holds four things:

- **The concept**, in one sentence.
- **What it touches**: the concepts it changes or sits beside, by heading.
- **What was measured**, or why nothing could be.
- **What would show it is wrong**: the observation that would make us undo it.

It is either a comment on the issue, or a file in `docs/decisions/` named `<issue>-<slug>.md`, which starts with `concept:` (the heading's text, as in `docs/concepts.md`) and `issue:` (the issue's address) in its frontmatter, then the four paragraphs above in bold. `docs/decisions/654-decision-note.md` shows the shape.

The description names it on one line per heading, with the heading's text on the line:

```
## Decisions

- Decision note: docs/decisions/654-decision-note.md
- Some other concept: https://github.com/iamvenuti/garrick/issues/654#issuecomment-1234567
```

A file must be added or changed by the pull request and have the heading as its `concept:`. A link to an issue comment must point at an issue of this repository, and a line may name only one heading. A bare issue link does not count. The check reads the description again when you edit it.

## Reporting a way through the walls

Not as an issue. See [SECURITY.md](SECURITY.md).

By contributing you agree that your work is released under the [MIT licence](LICENSE) and that you follow the [code of conduct](CODE_OF_CONDUCT.md).

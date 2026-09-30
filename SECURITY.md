# Security

Garrick's promise is that one client's material stays out of another client's work. A way around that promise is a security problem, even when nothing crashes.

## What to report privately

- A way for the wall check (`check.py` or the pre-commit hook) to let a walled name, link or quote through.
- A skill that carries material across a wall: from a meeting page into another party's thread, for example.
- The installer writing outside its target folder, or touching an existing workspace.
- Anything that sends workspace content off the machine. Core never does.

## How

Use **Report a vulnerability** on the repository's [Security tab](https://github.com/iamvenuti/garrick/security/advisories/new). It is private to you and the maintainer. Please don't open a public issue.

Build the example with invented names (Acme, Birch). Never send real client material.

You'll get an answer within a week. Fixes go into the next release, and the advisory is published once the fix is out, crediting you if you want the credit.

## What is not a vulnerability

- A refusal that should have passed. That is a false positive; open an issue with the "wall check" form.
- A limit the documentation already states, such as a clean paraphrase, or an edited copy of a mail's attachment, getting past the check. Paraphrase is the skill's job, not the hook's, as [principles](docs/principles.md) explains.

## Supported versions

Only the latest release.

# Security

Garrick uses declared information boundaries, instructions for the assistant and limited commit checks. A bypass of a documented check or a skill that violates those rules is a security problem, even when nothing crashes. The [coverage and limits](docs/principles.md#what-the-check-covers) define what is checked; Garrick does not provide access isolation or a guarantee against disclosure.

## What to report privately

- A way for the wall check (`check.py` or the pre-commit hook) to let a walled name, link or quote through.
- A skill that carries material across a wall: from a meeting page into another party's thread, for example.
- The installer writing outside its target folder, or touching an existing workspace.
- Garrick's Python tools sending workspace content off the machine. They should not. Your chosen AI assistant processes the content it reads through its provider; that expected data flow is separate.

## How

Use **Report a vulnerability** on the repository's [Security tab](https://github.com/iamvenuti/garrick/security/advisories/new). It is private to you and the maintainer. Please don't open a public issue.

Build the example with invented names (Acme, Birch). Never send real client material.

You'll get an answer within a week. Fixes go into the next release, and the advisory is published once the fix is out, crediting you if you want the credit.

## What is not a vulnerability

- A refusal that should have passed. That is a false positive; open an issue with the "wall check" form.
- A documented scanner limit, such as a clean paraphrase, wording moved from one party's note to another's in a single commit, an edited attachment or an unscanned document format. These limits do not make disclosure harmless; they define where the check cannot detect it. Report a skill that wrongly instructs or permits crossing a wall, or a bypass of a check within its documented coverage. See [principles](docs/principles.md#what-the-check-covers).

## Supported versions

Only the latest release. [Updating Garrick](docs/updating.md) brings an installed workspace up to it without losing your changes.

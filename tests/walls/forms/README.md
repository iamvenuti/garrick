# Wall forms

Note texts that name a Meetings page in a form a review round found, with the
verdict the wall check owes each side. `tests/test_wall_form_files.py` stages
every case in one fixture workspace and runs the staged-commit check once.
A form found once is tested in every later release. One file per review round.

## Format

A case is a heading, optional `gap:` line, and a fenced note text:

    ### name
    far: refused
    near: passed
    gap: why it passes today and is a way past the wall   (optional)
    ~~~~~
    See `{person}` now.
    ~~~~~

The note is written in a project of Acme (`Northwind`). `far` is the verdict when
the text names a page of Birch & Co, across the wall; `near` when it names the
same page of Acme. `far` is `refused`, and `near` is `passed` (no finding at all).
A case with `gap:` is a form that passes today: it keeps `far: refused`, the test
does not fail on it, and fails once the check refuses it, so the line is removed.

`<U+200B>` in a text is the character U+200B. A `{name}` is filled in for each side:

| Name | Far | Near |
|---|---|---|
| `{person}` | `wiki/people/kai-ross` | `wiki/people/jo-lane` |
| `{pname}` | `kai-ross` | `jo-lane` |
| `{pesc}` | `kai\-ross` | `jo\-lane` |
| `{punder}` | `kai_ross` | `jo_lane` |
| `{pspace}` | `kai ross` | `jo lane` |
| `{pstar}` | `kai-ro*` | `jo-la*` |
| `{ptail}` | `ross` | `lane` |
| `{entity}` | `wiki/entities/harvest-co` | `wiki/entities/quarry-ltd` |
| `{source}` | `wiki/sources/260315-harvest` | `wiki/sources/260315-quarry` |
| `{sname}` | `260315-harvest` | `260315-quarry` |
| `{dec}` | `wiki/decisions/260315 - pick-harvest` | `wiki/decisions/260315 - pick-quarry` |
| `{long}` | `x ` repeated 600 times | the same |

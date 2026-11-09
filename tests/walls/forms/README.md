# Wall forms

Note texts that name a Meetings page in a form a review round found, with the
verdict the wall check owes each side. `tests/test_wall_form_files.py` stages
every case in one fixture workspace and runs the staged-commit check once.
A form found once is tested in every later release. One file per review round.

## Format

A case is a heading and a fenced note text:

    ### name
    far: refused
    near: passed
    ~~~~~
    See `{person}` now.
    ~~~~~

The note is written in a project of Acme (`Northwind`). `far` is the verdict when
the text names a page of Birch & Co, across the wall; `near` when it names the
same page of Acme, and `near` is `passed` (no finding at all). A far case is
`refused` when its token resolves, as a link or as the exact path of a file (see
*One memory, walled use* in `docs/principles.md`), and `by design` when it does
not: a token that needs disguise to name a page is text, so it passes on both sides.
A form a review finds later is sorted by that question first.

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
| `{project}` | `Harbour` | `Northwind` |
| `{root}` | the fixture workspace's folder | the same |
| `{harness}` | a harness file of `{project}`, from the top of the vault | the same, in Northwind |
| `{abspath}` | that file's absolute path | the same |
| `{harnessuri}` | `{harness}` percent-encoded, for an `obsidian://` link | the same |

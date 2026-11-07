# Wall cases

One table of what each enforcement point must answer. `tests/test_decide.py`
runs the first table against `garrick_lib.decide()` alone. `tests/test_walls_cases.py`
builds a fixture workspace and runs the second table against each enforcement
point (`check.py`, Ask, the status page's actions, intake, scaffold), and
`check.py --walls-cases` runs the first table against the Walls table of the
workspace it is run in, with its tags in place of the fixture's roles.

A new wall or a new derivation rule comes with its cases, here, in the same commit.

## Roles

| Role | Means | In the fixture |
|---|---|---|
| `near` | a party | `acme` |
| `far` | a party walled from `near` | `birch` |
| `other` | a party walled from neither | `cedar` |
| `hat` | a party that shares its name with `hat2`, walled from it | `lumen` |
| `hat2` | the other hat of that company | `lumen-adv` |
| `ghost` | a tag the Parties table lacks | `ghost` |
| `public` | the reserved tag | `public` |

In `scope`, `*` is a project not yet chosen. In `labels`, `-` is a record with no label, `?` one whose labels cannot be derived, and a list is a set of tags.
A source marked `Recall` is Recall's case: Recall is not on `main`, so it is tested against `decide()` alone.

## decide()

| Id | Scope | Labels | Action | Expect | Source |
|---|---|---|---|---|---|
| d01 | near | far | read | deny | a walled pair, one way |
| d02 | far | near | read | deny | a walled pair, the other way |
| d03 | near | near | read | permit | the same party |
| d04 | near | other | read | permit | no wall between them |
| d05 | near | - | read | deny | a record with no label |
| d06 | near | ? | read | deny | labels that cannot be derived |
| d07 | - | near | read | deny | a scope with no party reads only records with no party |
| d08 | - | public | read | permit | a scope with no party reads a public record |
| d09 | near | ghost | read | deny | a tag missing from the Parties table |
| d10 | near | near, far | read | deny | a record labelled for both sides of a wall |
| d11 | other | near, far | read | deny | a thread file whose thread note and hub disagree across a wall |
| d12 | near | near, other | read | permit | labels with no wall inside them |
| d13 | near | public | read | permit | public is read by every scope |
| d14 | far | public | read | permit | public is read by every scope |
| d15 | public | near | read | deny | a public project holds no party, so it reads none |
| d16 | near, other | far | read | deny | a scope of two parties, one walled |
| d17 | near, far | other | read | deny | a scope that holds both sides of a wall |
| d18 | near | far, near | read | deny | a raw record cited by two pages across a wall (Recall: a raw record taking the parties of whichever page claimed it last) |
| d19 | near | ? | write | deny | labels that cannot be derived |
| d20 | near | far | write | deny | material from the far side of a wall written into a project |
| d21 | far | near | write | deny | the same, the other way |
| d22 | near | near | write | permit | material of the same party |
| d23 | near | - | write | permit | material that names no party |
| d24 | - | near | write | deny | a project with no party takes nothing: no label, no permit |
| d25 | - | - | write | deny | a project with no party takes nothing, even nothing |
| d26 | public | near | write | deny | nothing is written down into a public record |
| d27 | public | far, near | write | deny | the same, with two parties |
| d28 | public | public | write | permit | public material into a public record |
| d29 | public | - | write | permit | material with no party into a public record |
| d30 | near | public | write | permit | a public note quoted into a project |
| d31 | near | ghost | write | deny | material labelled with a tag the table lacks cannot be placed |
| d32 | near | far | file | deny | an item of a party walled from the project |
| d33 | near | near | file | permit | an item of the project's own party |
| d34 | near | other | file | permit | an item with no wall to the project |
| d35 | near | near, far | file | deny | a mail with both sides of a wall, one the project's |
| d36 | near | other, far | file | deny | a mail with a party walled from the project |
| d37 | other | near, far | file | confirm | a mail with both sides of a wall, the project walled from neither |
| d38 | near | hat | file | confirm | mail from a party that is always asked about |
| d39 | hat | hat2 | file | deny | one company, two hats, walled |
| d40 | other | hat2 | file | confirm | the other hat is always asked about too |
| d41 | near | - | file | confirm | an item with no label |
| d42 | near | ? | file | confirm | an item whose labels cannot be derived |
| d43 | near | ghost | file | deny | a tag missing from the Parties table |
| d44 | - | near | file | deny | a project with no party takes nothing |
| d45 | near | public | file | permit | a public item |
| d46 | near | far | frobnicate | error | an action that does not exist |
| d47 | other | near | read | permit | a third party reads a party no wall stands round |
| d49 | * | near, far | file | confirm | intake, before a project is chosen: a mail with both sides of a wall |
| d50 | * | hat | file | confirm | intake, before a project is chosen: mail from a party that is always asked about |
| d51 | * | near | file | permit | intake, before a project is chosen: one party, no question |
| d52 | * | - | file | confirm | intake, before a project is chosen: nothing on the mail names a party |
| d53 | near | public, far | read | deny | a record labelled public and for a far party is read as the far party |
| d54 | public | public | file | permit | a public item into a public project |
| d55 | public | near | file | deny | nothing is filed down into a public project |
| d56 | ghost | far | read | deny | a scope with a tag the Parties table lacks (`none` is one) is no scope |
| d57 | ghost | far | write | deny | the same, for a write |
| d58 | ghost | far | file | deny | the same, for filing |
| d59 | ghost | public | read | deny | the same, even for a public record |
| d60 | near, ghost | near | read | deny | one unknown tag among known ones |
| d61 | other | near, far | write | deny | material whose labels cross a wall inside themselves |
| d62 | public | near, far | write | deny | the same, into a public record |
| d63 | near | near, ghost | write | deny | one unknown tag among known ones, for a write |
| d64 | near | near, ghost | file | deny | one unknown tag among known ones, for filing |
| d48 | far | near | file | deny | the same wall for filing, the other way |

## labels()

Each row is a record in the fixture workspace; `Harbour` is a project of `far` whose folder does not name its party.
`Result` is the labels, `-` for none (read as unlabelled), or `?`.

| Id | Record | Result | Source |
|---|---|---|---|
| l01 | a file in project Northwind (hub `near`) | near | a project file takes its hub's |
| l02 | a file in project Harbour (hub `far`) | far | a folder that does not name its party |
| l03 | a file in a thread whose note says `far`, in a hub that says `near` | near, far | a thread file whose thread note and hub disagree |
| l04 | the folder of a project whose threads say `near` and `far` | near, far | a whole project is every thread's |
| l05 | a file in a project whose hub names no party | ? | a project with no `party:` is not read as public |
| l06 | a file in a project whose hub is missing | ? | no hub, no label |
| l07 | a Meetings page, `parties: [near]`, with a zone | near | its own parties |
| l08 | a Meetings page, `party: far` and `parties: [near]` | ? | `party:` and `parties:` disagree: they read two ways, so neither (a page with `party: birch` and `parties: [acme]` was admitted into an `acme` scope) |
| l09 | a Meetings page with `parties: [near]` and no zone | ? | an unfinished page |
| l10 | a person page, `party: near`, no zone | near | a person or entity page may have `party:` alone |
| l11 | a raw record cited by one page of `near` | near | the page that cites it |
| l12 | a raw record cited by a page of `near` and a page of `far` | near, far | a raw record cited by two pages |
| l13 | a raw record nobody cites | ? | no page, no label |
| l14 | a Knowledge page with no `parties:` | public | Knowledge crosses every wall |
| l15 | a Knowledge page with `parties: [near]`, or a party key in another case, quoted or indented | ? | a page that carries a party key in any spelling is someone's, not published |
| l16 | a mail in an inbox from a domain of `far` | far | a mail takes its domains |
| l17 | a mail in an inbox from webmail only | ? | webmail never names a party |
| l18 | a mail stamped `X-Garrick-Parties: near, far` | near, far | a mail saved as material |
| l19 | a file in a project whose hub says `party: public` | public | `public` is chosen, never inferred |
| l21 | a Meetings page whose `parties:` names `public` | ? | `public` is a project's choice, never a conversation's |
| l22 | a mail in an inbox with a header `X-Garrick-Parties: near` from a domain of `far` | near, far | the header and the addresses are both labels |
| l23 | a mail in an inbox with a header naming `public` | ? | a header cannot make a mail public |
| l24 | a mail in an inbox with a header naming a tag the table lacks | ? | a header tag the table lacks is refused |
| l25 | a file in a project whose hub has `type: note` and `party: near` | near | the hub is the note named after the folder, whatever its type |
| l26 | a file in a project whose hub has `party: none` | none | `none` is a tag no table row holds: decide() denies it |
| l27 | a Knowledge page with `tags: [near]` | public | `tags:` is not a party key |
| l20 | a file in a project whose thread note carries a `parties:` that disagrees with its `party:` | ? | two readings, neither |

## Enforcement points

A fixture workspace: `Northwind` (hub `near`) and `Harbour` (hub `far`) in the Work zone, a Meetings page for each party, and `Orchard`, a project whose hub names no party. `Reed` is a `public` project. The result is what the point does with the item; `refused` is `deny`, `asked` is `confirm`.

| Id | Point | Item | Expect | Source |
|---|---|---|---|---|
| e01 | check | a Northwind note that links a Harbour meeting page | refused | a walled link |
| e02 | check | a Northwind note that names a Harbour person | refused | a walled name |
| e03 | check | a Northwind note that links a Northwind meeting page | permitted | the near side |
| e04 | check | a note in Orchard that links a Northwind meeting page | refused | a project with no party (0.55.0: a project with no party let a paragraph from far across any wall commit) |
| e05 | check | a note in Orchard, with a hub that names no party | refused | no label, no permit; the hub is named as the fix |
| e06 | check | a note in Reed that names a person of any party | refused | nothing is written down into public |
| e07 | check | a note in Reed that links a Knowledge page | permitted | a public record holds Knowledge material |
| e08 | check | a note in Reed that links a meeting page | refused | a public record holds no meeting |
| e09 | check | Todo.md of the zone | permitted | a zone's own file belongs to no project |
| e10 | ask | read a Harbour thread from a Northwind scope | refused | a walled read |
| e11 | ask | read a Northwind thread from a Northwind scope | permitted | the near side |
| e12 | ask | read an Orchard thread from a Northwind scope | refused | a project with no party is unlabelled |
| e13 | ask | read a Meetings page with `party: far` and `parties: [near]` from `near` | refused | the two readings |
| e14 | ask | read a Reed note from a `far` scope | permitted | public |
| e15 | intake | file a Harbour item into Northwind | refused | a walled filing |
| e16 | intake | file a mail with both sides of a wall | asked | confirm is a return value |
| e17 | intake | file a mail from a party that is always asked about | asked | confirm is a return value |
| e18 | intake | file a mail into Orchard | refused | a project with no party takes nothing |
| e19 | scaffold | a thread of `far` moved into Northwind | refused | a walled thread |
| e24 | check | Northwind's hub and thread switched to `public`, with a committed note that names an Acme person | refused | a commit that changes a hub's parties re-checks the files already in the project |
| e25 | check | a binary file (`.bin`) in Orchard | refused | a project with no party takes any file whatever its suffix |
| e26 | check | a `.py` file in Northwind that names a Birch & Co person | refused | any staged file that reads as text is read, whatever its suffix |
| e27 | check | a Northwind note that links the zone's `Todo.md` | refused | a link to a file with no label |
| e28 | check | a Northwind note that links a raw record no page cites | refused | a link to a file with no label |
| e29 | check | a Northwind note that links a Meetings page whose `party:` and `parties:` disagree | refused | two readings, neither |
| e30 | ask | a session holding only `public` reads a Northwind record | refused | a public scope reads only public records |
| e31 | ask | a session holding `none` reads a Northwind record | refused | a scope with a tag the table lacks |
| e32 | intake | file a mail whose addresses name a party the user did not give | asked | confirm is a return value: nothing is filed |
| e33 | intake | file a Birch & Co mail stamped as Acme's into Northwind | refused | the header is not trusted over the addresses |
| e34 | check | any commit, while the Parties table holds a row named `public` | refused | the reserved tag is never a row |
| e35 | check | a Reed note that names a person with a zero-width space inside the name | refused | format characters are folded out before names are matched |
| e36 | nurture | a link from a note of a project with no party | refused | an empty scope is deny |
| e37 | check | a file in a project whose hub says `party: none` | refused | `none` is no label |
| e38 | check | a Northwind note that embeds a file in a hidden folder of the zone | refused | a link to a file with no label: Obsidian opens none, but whoever follows the path does |
| e39 | check | a `.md` file in Northwind that holds NUL bytes (UTF-16) | refused | a text file the walls cannot read is refused, not skipped |
| e40 | check | a note in Harbour's folder after a case-only rename (`harbour`) that names an Acme person | refused | a project is found however its folder is spelt |
| e41 | check | a Northwind note that links a thread file of a project whose hub names no party | refused | a no-party hub's empty tags are never filled by its thread's |
| e42 | check | a mail stamped with both sides of a wall, saved into a third party's `Sources/` | refused | a stamp that names both sides of a wall is asked about, not committed |
| e43 | check | a Reed (`public`) `Sources/` file that names a person of a party | refused | nothing labelled is written into public, `Sources/` included |
| e44 | check | a thread note that carries `parties:` | refused | hubs and thread notes carry `party:` alone |
| e45 | ask | a Knowledge page with `Parties: [acme]` read from a `birch` scope | refused | a party key in any spelling leaves a Knowledge page without a label |
| e46 | check | any commit, while the Parties table holds a row named `none` | refused | `none` is reserved like `public` |
| e47 | scaffold | `scaffold.py party --name None` | refused | `none` is never made a party |
| e48 | check | a Northwind note that links a file of a project whose hub has `party:` and `parties:` that disagree | refused | the unlabelled-link test uses what labels() reads |
| e49 | nurture | a link from a thread note of a project whose hub names no party | refused | Nurture takes its parties from labels() |
| e50 | intake | file an item into a project whose hub has `party:` and `parties:` that disagree | refused | intake takes a project's parties from labels() |
| e51 | ask | give a session holding Acme a record labelled `public` | permitted | admission is decide(read), under which public is read by every scope |
| e52 | check | a Northwind note that links a Knowledge page carrying `Parties:` | refused | a Knowledge page with a party key has no label |
| e20 | recall | search from a scope with no party | Recall's | tested with decide() alone, d07;  a session that began at zone level labelled as a project |
| e21 | recall | a mixed session read from a project with no party | Recall's | tested with decide() alone, d07 and d12;  a session of two projects labelled with the first |
| e22 | recall | ranking over rows the scope may not read | Recall's | tested with decide() alone, d01; the filter runs before the ranking;  ranking statistics computed over walled rows |
| e23 | ask | a Todo line that names no party | refused | decide() alone, d05;  a Todo line that names no party, served across a wall |

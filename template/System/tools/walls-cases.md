# Wall cases

One table of what each enforcement point must answer. `tests/test_decide.py`
runs the first table against `garrick_lib.decide()` alone. `tests/test_walls_cases.py`
builds a fixture workspace and runs the second table against each enforcement
point (`check.py`, Ask, the status page's actions, intake, scaffold), and
`check.py --walls-cases` runs the first table against the Parties table of the
workspace it is run in, with its tags in place of the fixture's roles.

The rule: material goes into a record whose parties are `scope` only when every
walled party on the material is one of them. An open party never blocks.

A new flag rule or a new derivation rule comes with its cases, here, in the same commit.

## Roles

| Role | Means | In the fixture |
|---|---|---|
| `near` | a walled party | `acme` |
| `far` | another walled party | `birch` |
| `other` | an open party | `cedar` |
| `hat` | a walled party that shares its name with `hat2` | `lumen` |
| `hat2` | the other hat of that company, also walled | `lumen-adv` |
| `zone` | the party a zone's Zones row names | `jo` |
| `ghost` | a tag the Parties table lacks | `ghost` |
| `knowledge` | what a Knowledge page with no party is labelled | `*knowledge` |

In `scope`, `*` is a project not yet chosen. In `labels`, `-` is a record with no label, `?` one whose labels cannot be derived, and a list is a set of tags.
A source marked `Recall` is Recall's case: Recall is not on `main`, so it is tested against `decide()` alone.

## decide()

| Id | Scope | Labels | Action | Expect | Source |
|---|---|---|---|---|---|
| d01 | near | far | read | deny | a walled party the scope lacks |
| d02 | far | near | read | deny | the same, the other way |
| d03 | near | near | read | permit | the same party |
| d04 | near | other | read | permit | an open party never blocks |
| d05 | near | - | read | deny | a record with no label |
| d06 | near | ? | read | deny | labels that cannot be derived |
| d07 | - | near | read | deny | a scope with no party reads nothing walled |
| d08 | - | knowledge | read | permit | a Knowledge page with no party is read by every scope |
| d09 | near | ghost | read | deny | a tag missing from the Parties table |
| d10 | near | near, far | read | deny | a record of two walled parties, one the scope lacks |
| d11 | other | near | read | deny | an open scope lacks the walled party |
| d12 | near | near, other | read | permit | a walled and an open party, the walled one the scope's |
| d13 | other | other | read | permit | an open party alone on a record, in an open scope |
| d14 | near, far | near, far | read | permit | material of two walled parties into a scope naming both |
| d15 | near, other | far | read | deny | a scope of two parties, the walled one lacking |
| d16 | other | near, other | read | deny | a record with a walled and an open party behaves as the walled one's |
| d17 | near | ? | write | deny | labels that cannot be derived |
| d18 | near | far | write | deny | material from a walled party the project lacks |
| d19 | near | near | write | permit | material of the same party |
| d20 | near | - | write | permit | material that names no party |
| d21 | - | near | write | deny | a project with no party takes nothing: no label, no permit |
| d22 | - | - | write | deny | a project with no party takes nothing, even nothing |
| d23 | knowledge | near | write | deny | a Knowledge page takes only material with no party |
| d24 | knowledge | - | write | permit | the same, with none |
| d25 | near | knowledge | write | permit | Knowledge material quoted into a project |
| d26 | near | ghost | write | deny | material labelled with a tag the table lacks cannot be placed |
| d27 | other | near | write | deny | walled material into an open party's project |
| d28 | near | other | write | permit | an open party's material into a walled project |
| d29 | near, far | near, far | write | permit | the project naming both walled parties is the yes |
| d30 | near | far | file | deny | an item of a walled party the project lacks |
| d31 | near | near | file | permit | an item of the project's own party |
| d32 | near | other | file | permit | an item of an open party |
| d33 | near | near, far | file | deny | an item with two walled parties, one the project lacks |
| d34 | near, far | near, far | file | permit | an item of two walled parties into a project naming both |
| d35 | hat | hat | file | confirm | mail from a party that is always asked about, into its own project |
| d36 | hat | hat2 | file | deny | one company, two hats, both walled |
| d37 | near | - | file | confirm | an item with no label |
| d38 | near | ? | file | confirm | an item whose labels cannot be derived |
| d39 | near | ghost | file | deny | a tag missing from the Parties table |
| d40 | - | near | file | deny | a project with no party takes nothing |
| d41 | near | far | frobnicate | error | an action that does not exist |
| d42 | * | near, far | file | confirm | intake, before a project is chosen: an item of two walled parties |
| d43 | * | hat | file | confirm | intake, before a project is chosen: mail from a party that is always asked about |
| d44 | * | near | file | permit | intake, before a project is chosen: one party, no question |
| d45 | * | other, near | file | permit | intake, before a project is chosen: one walled party and an open one |
| d46 | * | - | file | confirm | intake, before a project is chosen: nothing on the mail names a party |
| d47 | ghost | far | read | deny | a scope with a tag the Parties table lacks (`none` is one) is no scope |
| d48 | ghost | far | file | deny | the same, for filing |
| d49 | near, ghost | near | read | deny | one unknown tag among known ones |

## labels()

Each row is a record in the fixture workspace; `Harbour` is a project of `far` whose folder does not name its party; `Garden` is a project of the Personal zone, whose Zones row names `zone`.
`Result` is the labels, `-` for none (read as unlabelled), or `?`.

| Id | Record | Result | Source |
|---|---|---|---|
| l01 | a file in project Northwind (hub `near`) | near | a project file takes its hub's |
| l02 | a file in project Harbour (hub `far`) | far | a folder that does not name its party |
| l03 | a file in a thread whose note says `far`, in a hub that says `near` | near, far | a thread file takes the thread note's parties and the hub's |
| l04 | a `Sources/` file of Northwind, whose thread Odd adds `far`; a file of its thread Pricing | near | nothing is derived from sibling threads |
| l05 | a file in a project whose hub names no party | ? | a hub with no `party:` labels nothing |
| l06 | a file in a project whose hub is missing | ? | no hub, no label |
| l07 | a Meetings page, `parties: [near]`, with a zone | near | its own parties |
| l08 | a Meetings page, `party: far` and `parties: [near]` | ? | `party:` and `parties:` disagree: they read two ways, so neither |
| l09 | a Meetings page with `parties: [near]` and no zone | ? | an unfinished page |
| l10 | a person page, `party: near`, no zone | near | a person or entity page may have `party:` alone |
| l11 | a raw record cited by one page of `near` | near | the page that cites it |
| l12 | a raw record cited by a page of `near` and a page of `far` | near, far | a raw record cited by two pages |
| l13 | a raw record nobody cites | ? | no page, no label |
| l14 | a Knowledge page with no `parties:` | knowledge | Knowledge crosses every wall |
| l15 | a Knowledge page with `parties: [near]`, or a party key in another case, quoted or indented | ? | a page that carries a party key in any spelling is someone's, not published |
| l16 | a mail in an inbox from a domain of `far` | far | a mail takes its domains |
| l17 | a mail in an inbox from webmail only | ? | webmail never names a party |
| l18 | a mail stamped `X-Garrick-Parties: near, far` | near, far | a mail saved as material |
| l19 | a file in project Garden (hub `other`) of the zone that names `zone` | zone, other | a file carries its zone's party and its hub's |
| l20 | a file in a project whose thread note carries a `parties:` that disagrees with its `party:` | ? | two readings, neither |
| l22 | a mail in an inbox with a header `X-Garrick-Parties: near` from a domain of `far` | near, far | the header and the addresses are both labels |
| l23 | a mail in an inbox with a header naming `none` | ? | `none` is no party |
| l24 | a mail in an inbox with a header naming a tag the table lacks | ? | a header tag the table lacks is refused |
| l25 | a file in a project whose hub has `type: note` and `party: near` | near | the hub is the note named after the folder, whatever its type |
| l26 | a file in a project whose hub has `party: none` | none | `none` is a tag no table row holds: decide() denies it |
| l27 | a Knowledge page with `tags: [near]` | knowledge | `tags:` is not a party key |
| l28 | a file in a project whose hub names two parties as a list | both | `party:` takes one tag or a list |

## Enforcement points

A fixture workspace: `Northwind` (hub `near`) and `Harbour` (hub `far`) in the Work zone, a Meetings page for each party, and `Orchard`, a project whose hub names no party. `Reed` is a project of `other`, an open party. The result is what the point does with the item; `refused` is `deny`, `asked` is `confirm`.

| Id | Point | Item | Expect | Source |
|---|---|---|---|---|
| e01 | check | a Northwind note that links a Harbour meeting page | refused | a walled link |
| e02 | check | a Northwind note that names a Harbour person | refused | a walled name |
| e03 | check | a Northwind note that links a Northwind meeting page | permitted | the near side |
| e04 | check | a note in Orchard that links a Northwind meeting page | refused | a project with no party (0.55.0: a project with no party let a paragraph from far across any wall commit) |
| e05 | check | a note in Orchard, with a hub that names no party | refused | no label, no permit; the hub is named as the fix |
| e06 | check | a note in Reed that names a person of a walled party | refused | a walled party the project does not name |
| e07 | check | a note in Reed that links a Knowledge page | permitted | a project holds Knowledge material |
| e08 | check | a note in Reed that links a meeting page of a walled party | refused | the meeting's party is walled and Reed does not name it |
| e09 | check | Todo.md of the zone | permitted | a zone's own file belongs to no project |
| e10 | ask | read a Harbour thread from a Northwind scope | refused | a walled read |
| e11 | ask | read a Northwind thread from a Northwind scope | permitted | the near side |
| e12 | ask | read an Orchard thread from a Northwind scope | refused | a project with no party is unlabelled |
| e13 | ask | read a Meetings page with `party: far` and `parties: [near]` from `near` | refused | the two readings |
| e14 | ask | read a Reed note from a `far` scope | permitted | an open party's material is read anywhere |
| e15 | intake | file a Harbour item into Northwind | refused | a walled filing |
| e16 | intake | file a mail with both sides of a wall | asked | confirm is a return value |
| e17 | intake | file a mail from a party that is always asked about | asked | confirm is a return value |
| e18 | intake | file a mail into Orchard | refused | a project with no party takes nothing |
| e19 | scaffold | a thread of `far` moved into Northwind | refused | a walled thread |
| e24 | check | Northwind's hub and thread switched to `other`, with a committed note that names an Acme person | refused | a commit that changes a hub's parties re-checks the files already in the project |
| e25 | check | a binary file (`.bin`) in Orchard | refused | a project with no party takes any file whatever its suffix |
| e26 | check | a `.py` file in Northwind that names a Birch & Co person | refused | any staged file that reads as text is read, whatever its suffix |
| e27 | check | a Northwind note that links the zone's `Todo.md` | refused | a link to a file with no label |
| e28 | check | a Northwind note that links a raw record no page cites | refused | a link to a file with no label |
| e29 | check | a Northwind note that links a Meetings page whose `party:` and `parties:` disagree | refused | two readings, neither |
| e30 | ask | a session holding no party reads a Northwind record | refused | a scope with no party reads nothing walled |
| e31 | ask | a session holding `none` reads a Northwind record | refused | a scope with a tag the table lacks |
| e32 | intake | file a mail whose addresses name a party the user did not give | asked | confirm is a return value: nothing is filed |
| e33 | intake | file a Birch & Co mail stamped as Acme's into Northwind | refused | the header is not trusted over the addresses |
| e35 | check | a Reed note that names a walled person with a zero-width space inside the name | refused | format characters are folded out before names are matched |
| e36 | nurture | a link from a note of a project with no party | refused | an empty scope is deny |
| e37 | check | a file in a project whose hub says `party: none` | refused | `none` is no label |
| e38 | check | a Northwind note that embeds a file in a hidden folder of the zone | refused | a link to a file with no label: Obsidian opens none, but whoever follows the path does |
| e39 | check | a `.md` file in Northwind that holds NUL bytes (UTF-16) | refused | a text file the walls cannot read is refused, not skipped |
| e40 | check | a note in Harbour's folder after a case-only rename (`harbour`) that names an Acme person | refused | a project is found however its folder is spelt |
| e41 | check | a Northwind note that links a thread file of a project whose hub names no party | refused | a no-party hub's empty tags are never filled by its thread's |
| e42 | check | a mail stamped with both sides of a wall, saved into a third party's `Sources/` | refused | a stamp that names both sides of a wall is asked about, not committed |
| e43 | check | a Reed `Sources/` file that names a person of a walled party | permitted | `Sources/` holds what a party sent, which may name anyone |
| e44 | check | a thread note that carries `parties:` | refused | hubs and thread notes carry `party:` alone |
| e45 | ask | a Knowledge page with `Parties: [acme]` read from a `birch` scope | refused | a party key in any spelling leaves a Knowledge page without a label |
| e46 | check | any commit, while the Parties table holds a row named `none` | refused | `none` is reserved |
| e47 | scaffold | `scaffold.py party --name None` | refused | `none` is never made a party |
| e48 | check | a Northwind note that links a file of a project whose hub has `party:` and `parties:` that disagree | refused | the unlabelled-link test uses what labels() reads |
| e49 | nurture | a link from a thread note of a project whose hub names no party | refused | Nurture takes its parties from labels() |
| e50 | intake | file an item into a project whose hub has `party:` and `parties:` that disagree | refused | intake takes a project's parties from labels() |
| e51 | ask | give a session holding Acme a Knowledge page | permitted | admission is decide(read), under which a Knowledge page is read by every scope |
| e52 | check | a Northwind note that links a Knowledge page carrying `Parties:` | refused | a Knowledge page with a party key has no label |
| e20 | recall | search from a scope with no party | Recall's | tested with decide() alone, d07;  a session that began at zone level labelled as a project |
| e21 | recall | a mixed session read from a project with no party | Recall's | tested with decide() alone, d07 and d12;  a session of two projects labelled with the first |
| e22 | recall | ranking over rows the scope may not read | Recall's | tested with decide() alone, d01; a row decide() does not admit is not in the scope index, so it ranks nothing;  ranking statistics computed over walled rows |
| e23 | ask | a Todo line that names no party | refused | decide() alone, d05;  a Todo line that names no party, served across a wall |

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
| d31 | near | ghost | write | permit | a tag no wall can see names no one across a wall |
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
| d43 | near | ghost | file | confirm | a tag missing from the Parties table |
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
| l15 | a Knowledge page with `parties: [near]` | near | its own parties |
| l16 | a mail in an inbox from a domain of `far` | far | a mail takes its domains |
| l17 | a mail in an inbox from webmail only | ? | webmail never names a party |
| l18 | a mail stamped `X-Garrick-Parties: near, far` | near, far | a mail saved as material |
| l19 | a file in a project whose hub says `party: public` | public | `public` is chosen, never inferred |
| l21 | a Meetings page whose `parties:` names `public` | ? | `public` is a project's choice, never a conversation's |
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
| e20 | recall | search from a scope with no party | Recall's | tested with decide() alone, d07;  a session that began at zone level labelled as a project |
| e21 | recall | a mixed session read from a project with no party | Recall's | tested with decide() alone, d07 and d12;  a session of two projects labelled with the first |
| e22 | recall | ranking over rows the scope may not read | Recall's | tested with decide() alone, d01; the filter runs before the ranking;  ranking statistics computed over walled rows |
| e23 | ask | a Todo line that names no party | refused | decide() alone, d05;  a Todo line that names no party, served across a wall |

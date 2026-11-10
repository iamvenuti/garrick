# Wall cases

One table of what each enforcement point must answer. `tests/test_decide.py`
runs the first table against `garrick_lib.decide()` alone. `tests/test_walls_cases.py`
builds a fixture workspace and runs the second and third tables against the
pre-commit check and the Meetings lint, and `check.py --walls-cases` runs the
first table against the Zones table of the workspace it is run in, with its
zones in place of the fixture's roles.

The rule: a zone is walled or open. Material of a walled zone goes only into
that zone. Material of an open zone goes anywhere. A file's zone is its path,
`Zones/<Zone>/...`, or, in the Meetings wiki, the `zone:` of its page. Knowledge
is read by every zone and takes only material with no zone. `System/` and the
workspace root read every zone and hold no zone's content.

The check refuses a crossing by reference and by copy: a link, an embed or a path to a
file of another walled zone, a link to a Meetings page of another walled zone or
of none, a file copied whole from another walled zone, and a run of eight words
shared with a file or Meetings page of another walled zone or of none. No name is read.

A new rule comes with its cases, here, in the same commit.

## Roles

| Role | Means | In the fixture |
|---|---|---|
| `near` | a walled zone | `Work` |
| `far` | another walled zone | `Home` |
| `open` | an open zone | `Ventures` |
| `ghost` | a zone the Zones table lacks | `ghost-zone` |
| `unzoned` | a Meetings page with no `zone:`, or with two | `<no zone>` |
| `knowledge` | what a Knowledge page is labelled | `*knowledge` |

In `scope`, `*` is a project not yet chosen. In `labels`, `-` is material with no zone, `?` material whose zone cannot be derived, and a list is a set of zones.

## decide()

| Id | Scope | Labels | Action | Expect | Source |
|---|---|---|---|---|---|
| d01 | near | far | read | deny | a walled zone's material is not read from another zone |
| d02 | far | near | read | deny | the same, the other way |
| d03 | near | near | read | permit | the same zone |
| d04 | near | open | read | permit | an open zone's material goes anywhere |
| d05 | near | - | read | deny | a record with no label |
| d06 | near | ? | read | deny | a zone that cannot be derived |
| d07 | - | near | read | deny | a scope in no zone reads nothing walled |
| d08 | - | knowledge | read | permit | a Knowledge page is read by every scope |
| d09 | near | ghost | read | deny | a zone the Zones table lacks |
| d10 | open | near | read | deny | an open scope may not read a walled zone |
| d11 | open | open | read | permit | an open zone alone, in an open scope |
| d12 | near | near, open | read | permit | a walled and an open zone, the walled one the scope's |
| d13 | open | near, open | read | deny | a record of a walled and an open zone behaves as the walled one's |
| d14 | near | far, open | read | deny | two zones, one walled and not the scope's |
| d15 | near | unzoned | read | deny | a page with no zone is walled |
| d16 | near | ? | write | deny | a zone that cannot be derived |
| d17 | near | far | write | deny | material of a walled zone into another zone |
| d18 | near | near | write | permit | material of the same zone |
| d19 | near | - | write | permit | material with no zone is new text |
| d20 | - | near | write | deny | a record in no zone takes nothing |
| d21 | - | - | write | deny | a record in no zone takes nothing, even nothing |
| d22 | knowledge | near | write | deny | a Knowledge page takes only material with no zone |
| d23 | knowledge | open | write | deny | an open zone's material is a zone's material too |
| d24 | knowledge | - | write | permit | new text with no zone goes into a Knowledge page |
| d25 | near | knowledge | write | permit | Knowledge material quoted into a zone |
| d26 | near | ghost | write | deny | material of a zone the table lacks cannot be placed |
| d27 | open | near | write | deny | walled material into an open zone |
| d28 | near | open | write | permit | an open zone's material into a walled zone |
| d29 | near | unzoned | write | deny | a page with no zone is walled |
| d30 | near | far | file | deny | an item of a walled zone, into another zone |
| d31 | near | near | file | permit | an item of the zone's own |
| d32 | near | open | file | permit | an item of an open zone |
| d33 | near | - | file | confirm | an item with no label |
| d34 | near | ? | file | confirm | an item whose zone cannot be derived |
| d35 | near | ghost | file | deny | a zone the table lacks |
| d36 | - | near | file | deny | a record in no zone takes nothing |
| d37 | near | far | frobnicate | error | an action that does not exist |
| d38 | * | near, far | file | confirm | intake, before a project is chosen: an item of two walled zones |
| d39 | * | near | file | permit | intake, before a project is chosen: one zone, no question |
| d40 | * | open, near | file | permit | intake, before a project is chosen: one walled zone and an open one |
| d41 | * | - | file | confirm | intake, before a project is chosen: nothing on the item names a zone |
| d42 | ghost | far | read | deny | a scope that is a zone the table lacks is no scope |
| d43 | ghost | far | file | deny | the same, for filing |
| d44 | near, ghost | near | read | deny | one unknown zone among known ones |

## Enforcement points

A fixture workspace: `Work` and `Home` are walled zones, `Ventures` an open one. `Northwind` and `Harbour` are projects of Work, `Garden` of Home, `Orchard` of Ventures. Each zone has a Meetings page of its own, `zone:` its own. The result is what the check does with a note; `refused` is an error finding for it, `permitted` none, `warned` a warning.

| Id | Point | Item | Expect | Source |
|---|---|---|---|---|
| e01 | check | a Northwind note that links a Garden note | refused | a link into another walled zone |
| e02 | check | a Northwind note that embeds a Garden file | refused | an embed |
| e03 | check | a Northwind note that writes the path of a Garden file | refused | a path |
| e04 | check | a Northwind note that links a Harbour note | permitted | two projects of one walled zone |
| e05 | check | a Northwind note that links an Orchard note | permitted | an open zone's material goes anywhere |
| e06 | check | an Orchard note that links a Northwind note | refused | walled material into an open zone |
| e07 | check | a Northwind note that links a Knowledge page | permitted | a zone holds Knowledge material |
| e08 | check | a Northwind note that links a Meetings page of Home | refused | a Meetings page of another walled zone |
| e09 | check | a Northwind note that links a Meetings page of Work | permitted | a Meetings page of the same zone |
| e10 | check | a Northwind note that links a Meetings page of Ventures | permitted | a Meetings page of an open zone |
| e11 | check | a Northwind note that links a Meetings page with no `zone:` | refused | a page with no zone is walled |
| e12 | check | a Northwind note that links a Meetings page naming two zones | refused | two zones, so none |
| e13 | check | a Northwind note that links a raw record cited by a page of Home | refused | a record takes the zone of the page that claims it |
| e14 | check | a Northwind note that links a raw record nobody cites | refused | no page, no zone |
| e15 | check | a Northwind note that names a person of Home and its party, and links nothing | permitted | no name is read |
| e16 | check | a Northwind note that repeats a sentence of a Garden note | refused | eight shared words held across a zone wall, a copy by wording |
| e17 | check | a Northwind file that is a whole copy of a Garden file | refused | a copy made whole |
| e18 | check | a Northwind file that is a whole copy of an Orchard file | permitted | an open zone's file may be copied |
| e19 | check | a Northwind file that is a whole copy of a Northwind file in another project | permitted | the same zone |
| e20 | check | a Northwind file shorter than the copy floor, equal to a Garden file | permitted | identical bytes prove nothing below the floor |
| e21 | check | a Knowledge page that is a whole copy of a Garden file | refused | Knowledge takes only material with no zone |
| e22 | check | a symbolic link in Northwind that leads to a Garden folder | refused | where a link leads is read |
| e23 | check | Todo.md of the zone, linking a Garden note | permitted | a zone's own file belongs to no project |
| e24 | check | a Northwind note that links a file of a Harbour hub's thread | permitted | the zone is the path, whatever the hub or thread says |
| e25 | check | a Northwind note that links a Garden note, with `party:` of Home on the hub | refused | a party key decides nothing |
| e26 | check | a Northwind `.py` file that links a Garden note | refused | any staged file that reads as text is read, whatever its suffix |
| e27 | check | a Northwind `.md` file that holds NUL bytes (UTF-16) | refused | a text file the walls cannot read is refused, not skipped |
| e28 | check | a Northwind note that repeats a sentence of a Harbour note | permitted | wording held in the same zone |
| e29 | check | a Northwind note that repeats a sentence of an Orchard note | permitted | wording held in an open zone |
| e30 | check | a Northwind note that repeats a sentence of a Meetings page of Home | refused | wording held by a Meetings page of another walled zone |
| e31 | check | a Northwind note that repeats a sentence of a Meetings page with no zone | refused | a page with no zone is walled |
| e32 | check | a Knowledge page that repeats a sentence of a Meetings page | warned | Knowledge's own rule: wording in Knowledge is common to every zone |
| e33 | check | a Northwind file that is a whole copy of a raw record of a Meetings page of Work | permitted | a record is in the zone of the page that claims it |
| e34 | check | a Northwind file that is a whole copy of a raw record of a Meetings page of Ventures | permitted | an open zone's record may be copied |
| e35 | check | a Northwind file that is a whole copy of a raw record of a Meetings page of Home | refused | a copy across a zone wall, a record included |
| e36 | check | a Northwind note that links an entity page with no zone and no party | refused | fail closed once the flags are final: every page has one zone (#481) |
| e37 | check | a Northwind file that is a whole copy of the zone template's Todo.md, as it is written in Home | permitted | a file Garrick ships is the same in every zone, not a copy |
| e38 | check | a Northwind file that is a whole copy of a file held by both Home and Ventures | permitted | content held by two zones is template text |

## Meetings

Each row is a page of the fixture's Meetings wiki, and its zone as `zone_of()` reads it.

| Id | Page | Zone | Source |
|---|---|---|---|
| m01 | a source page, `zone: Work` | Work | a page has one zone |
| m02 | a source page, `zone: work` | Work | matched to the Zones table without regard to case |
| m03 | a source page with no `zone:` | unzoned | an unfinished page |
| m04 | a source page, `zone: [Work, Home]` | unzoned | two zones |
| m05 | a source page, `zone: Nowhere` | unzoned | a zone the table lacks |
| m06 | an entity page, `zone: Work` | Work | an entity page takes the zone of its sources |
| m07 | a raw record cited by one page of Work | Work | a record takes its page's zone |
| m08 | a raw record cited by a page of Work and a page of Home | unzoned | two zones |
| m09 | a raw record nobody cites | unzoned | no page, no zone |
| m10 | a Knowledge page | none | Knowledge has no zone |
| m11 | a `System/` file | none | System has no zone |

## Meetings lint

| Id | Item | Expect | Source |
|---|---|---|---|
| l01 | an entity page citing sources of Work and of Home | a finding, with the split as its fix | an entity page of two walled zones becomes one page per zone |
| l02 | an entity page citing sources of Work and of Ventures | no finding | an open zone does not force a split |
| l03 | a page with no `zone:` | a finding | every page has one zone |
| l04 | a page with `zone: Work` and one source of Work | no finding | the page is whole |
| l05 | a people page with no sources, `party:` of a party whose row says Home, no `zone:` | a finding that names Home | it takes the zone of its party's row |

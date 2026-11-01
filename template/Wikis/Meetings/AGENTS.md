# Meetings

Every conversation you have, from every zone, in one place: calls and meetings, and the mail you exchange. This file is the schema; it wins over any skill that writes here. It is Garrick's, as shipped: this workspace's own additions to it are in `AGENTS.local.md` beside it, when that exists. Read it next; it wins where the two differ.

## Layout

    Meetings/
      raw/
        inbox/          drop transcripts here: .txt, .md or .vtt, from any recorder
        <YYMMDD-slug>.* the record, moved here once ingested; never edited
      wiki/
        sources/        one page per meeting, and one per mail
        people/         one page per person met
        entities/       one page per organisation, at most one per party
        index.md        every working page, newest first
        index-dormant.md  every dormant page: its date, the day it went dormant, and why
        log.md          one line per ingest, newest first
      questions/        one file per question only you can answer
      dormant/          pages faded out of working memory, and their raw records,
        wiki/ raw/        at the same paths below
      archive/          pages faded further, in no index; read only when asked
        wiki/ raw/

## A meeting page

`wiki/sources/<YYMMDD-slug>.md`:

```yaml
---
title: <what the meeting was about>
type: meeting
date: YYYY-MM-DD
zone: <zone name>
parties: [<tag>, <tag>]      # from the Parties table in System/context.md
people: ["[[wiki/people/<name>]]"]
raw: "[[raw/<YYMMDD-slug>]]"
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

Then: what was decided, what each side said where the wording matters, and an actions table (what, who, by when).

A call that covers several projects can be split: a page per project, each `<slug>-<word>`, each keeping the same `raw:` and naming every other in `split-with: ["[[<slug>-<word>]]"]`, each with only its own section's `parties` and saying which part of the record it covers.

## A mail page

Mail arrives through a zone's `Inbox/` folder (`Zones/<Zone>/Inbox/`), as `.eml`, `.txt` or `.md`, and comes here when it is a conversation. Once filed, the original moves into `raw/` under the same `YYMMDD-slug` naming, and its page sits in `wiki/sources/` beside the meeting pages, so every wall reads it the same way:

```yaml
---
title: <what the mail is about>
type: email
date: YYYY-MM-DD
zone: <the zone whose Inbox it came from>
parties: [<tag>, <tag>]
from: "<Name> <address>"
to:
  - "<Name> <address>"
cc: []
people: ["[[wiki/people/<name>]]"]
raw: "[[raw/<YYMMDD-slug>]]"
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

A mail with a Message-ID also carries it as `source-id:`; a mail or a recording already filed, by its bytes or that ID, is refused a second page. Then: what it says or asks, the wording that matters, and an actions table. Attachments stay inside the raw record and are listed on the page. One a project needs is saved into that project's `Sources/` only after this page exists, and only when the project's party is not walled from the page's parties.

## A person page

`wiki/people/<name-slug>.md`, one per person met:

```yaml
---
title: <their name>
type: person
party: <tag>                 # from the Parties table; `none` for someone who belongs to no party
organisation: "[[wiki/entities/<slug>]]"   # the entity page of that party, when there is one
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

Then one sentence: who they are, and which party. Nothing learned in a meeting, and no status: a person page is read on both sides of every wall.

`organisation:` links the entity page that names the person's party, and nothing else: it carries identity, as the page does. `ingest.py person` writes it on a new page when exactly one entity page names that party, and the `nurture` skill offers it, on a yes, for a page written before. A page that names no party or several, or a name the People table has under two parties a wall keeps apart, gets none.

## An entity page

`wiki/entities/<slug>.md`, one per organisation:

```yaml
---
title: <its name>
type: entity
party: <tag>                 # the party it stands for, from the Parties table; leave it out if it stands for none
sources: ["[[wiki/sources/<YYMMDD-slug>]]"]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

At most one entity page names a party. With two, a person page could link either, so it links neither, and `check.py` warns about both. An organisation known in two roles, on either side of a wall, has a page per role, each naming its own party, and cites no meeting of the other.

## A question

When an ingest or a lint finds something only you can settle, such as who decides, which version is live, or whether a figure still holds, it writes `questions/<YYMMDD> - <slug>.md` and adds no line to the page:

```yaml
---
type: question
asked: YYYY-MM-DD
status: open                 # open, answered or later
zone: <zone name>
parties: [<tag>]             # the parties of the pages it comes from
origin: "[[raw/<YYMMDD-slug>]]"
pages: ["[[wiki/sources/<YYMMDD-slug>]]"]
---
```

Then the question as one bold line, why it matters, and the options, if there are any, as `- [<label>] <what the pages would then say>`. `origin` is the record that raised it; `pages` are the pages the answer would change. A question carries the zone and parties of what it is about, and the walls read it as they read a page.

## Rules

- **`zone` and `parties` are required**, on a meeting page and a mail page alike. They are what the walls read. A page missing either is unfinished, and no project may use it until it is filled in. When the transcript or the addresses do not make them obvious, ask.
- **Raw is the record.** Never edit a file in `raw/`. Correct the summary, not the source.
- **Quote, do not smooth.** Where the exact words matter (a commitment, a number, a refusal), quote them from the transcript.
- **Pages fade, and nothing is deleted.** A page leaves working memory by age, kind and use, into `dormant/` and later `archive/`, its raw record with it, and every link into it follows: `System/tools/fade.py` proposes it, and only a yes moves it. A page keeps its frontmatter wherever it goes, so its zone and parties hold there as here. `pinned: true` keeps a page working for good; `superseded:` (a link to what replaces it, or a short reason) keeps it out of working memory, and it never comes back by use. A person page never moves: what faded is listed under its `## Earlier`.
- **One page per person**, linked from every meeting they were in. It says who they are and which party they belong to. No status, and nothing learned in any one meeting: a person page is read on both sides of every wall.

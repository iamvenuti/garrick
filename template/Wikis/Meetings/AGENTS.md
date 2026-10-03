# Meetings

Every conversation you have, from every zone, in one place: calls and meetings, and the mail you exchange. This file is the schema; it wins over any skill that writes here.

## Layout

    Meetings/
      raw/
        inbox/          drop transcripts here: .txt, .md or .vtt, from any recorder
        <YYMMDD-slug>.* the record, moved here once ingested; never edited
      wiki/
        sources/        one page per meeting, and one per mail
        people/         one page per person met
        index.md        every page, newest first
        log.md          one line per ingest, newest first

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

Then: what it says or asks, the wording that matters, and an actions table. Attachments stay inside the raw record and are listed on the page. One a project needs is saved into that project's `Sources/` only after this page exists, and only when the project's party is not walled from the page's parties.

## A person page

`wiki/people/<name-slug>.md`, one per person met:

```yaml
---
title: <their name>
type: person
party: <tag>                 # from the Parties table; `none` for someone who belongs to no party
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

Then one sentence: who they are, and which party. Nothing learned in a meeting, and no status: a person page is read on both sides of every wall.

## Rules

- **`zone` and `parties` are required**, on a meeting page and a mail page alike. They are what the walls read. A page missing either is unfinished, and no project may use it until it is filled in. When the transcript or the addresses do not make them obvious, ask.
- **Raw is the record.** Never edit a file in `raw/`. Correct the summary, not the source.
- **Quote, do not smooth.** Where the exact words matter (a commitment, a number, a refusal), quote them from the transcript.
- **One page per person**, linked from every meeting they were in. It says who they are and which party they belong to. No status, and nothing learned in any one meeting: a person page is read on both sides of every wall.

# Knowledge

Published material you study: reports, papers, articles, vendor documents. None of it carries anyone's confidence, so it can be used in any zone. This file is the schema; it wins over any skill that writes here. It is Garrick's, as shipped: this workspace's own additions to it are in `AGENTS.local.md` beside it, when that exists. Read it next; it wins where the two differ.

## Layout

    Knowledge/
      raw/              the frozen original: PDF, saved web page, text; never edited
      wiki/
        sources/        one page per item read
        concepts/       one page per idea, built up across sources
        entities/       one page per organisation or product
        index.md        every working page, newest first
        index-dormant.md  every dormant page: its date, the day it went dormant, and why
        log.md          one line per ingest, newest first
      questions/        one file per question only you can answer
      dormant/          pages faded out of working memory, and their raw files,
        wiki/ raw/        at the same paths below
      archive/          pages faded further, in no index; read only when asked
        wiki/ raw/

## A source page

```yaml
---
title: <title of the work>
type: source
author: <who wrote or published it>
published: YYYY-MM-DD      # or YYYY-MM, or YYYY, when that is all the source gives
raw: "[[raw/<file>]]"
confidence: high | medium | low
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

A wiki that grew its own layout declares it in `schema.json` beside this file, and `intake.py`, the `knowledge` skill and `check.py` follow it: where originals go (`"raw": "raw/{kind}/{date} {publisher} - {title}.{ext}"`, with its `"kinds"`), the source page's `"type"` and required `"fields"`, and the index (`"list"` or `"tables"`) and log (`"line"` or `"section"`). Without it, the layout above applies.

## A question

When an ingest or a lint finds something only you can settle, such as two sources that disagree, it writes `questions/<YYMMDD> - <slug>.md` and adds no line to the page. It has the form of a Meetings question (see `../Meetings/AGENTS.md`), with `type: question`, `asked`, `status`, `origin` and `pages`, and no `zone` or `parties`, as no file here has.

## Rules

- **Freeze first.** Save a web page or document into `raw/` before summarising it, so the source cannot change under you.
- **Attribute claims.** A vendor's claim is written as the vendor's claim, never as fact.
- **Nothing from a meeting comes in here.** Conversations belong in Meetings, where the walls can see them.
- **Reading fades, and nothing is deleted.** A source page leaves working memory by age and kind, into `dormant/` and later `archive/`, and its raw file moves with it, never sooner, so its link to its source always resolves: `System/tools/fade.py` proposes it, and only a yes moves it. `pinned: true` keeps a page working for good; `superseded:` keeps it out of working memory. Concept and entity pages never move: what faded is listed under their `## Earlier`.
- **No page carries `party`, `parties` or a `zone`.** What is here is published and usable anywhere. A newsletter that arrived by mail belongs here, its saved message in `raw/`; a party writing to you does not.

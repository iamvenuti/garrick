# Knowledge

Published material you study: reports, papers, articles, vendor documents. None of it carries anyone's confidence, so it can be used in any zone. This file is the schema; it wins over any skill that writes here.

## Layout

    Knowledge/
      raw/              the frozen original: PDF, saved web page, text; never edited
      wiki/
        sources/        one page per item read
        concepts/       one page per idea, built up across sources
        entities/       one page per organisation or product
        index.md        every page, newest first
        log.md          one line per ingest, newest first

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

## Rules

- **Freeze first.** Save a web page or document into `raw/` before summarising it, so the source cannot change under you.
- **Attribute claims.** A vendor's claim is written as the vendor's claim, never as fact.
- **Nothing from a meeting comes in here.** Conversations belong in Meetings, where the walls can see them.
- **No page carries `parties` or a `zone`.** What is here is published and usable anywhere. A newsletter that arrived by mail belongs here, its saved message in `raw/`; a party writing to you does not.

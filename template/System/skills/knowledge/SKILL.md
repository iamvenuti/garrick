---
name: knowledge
description: >
  Freeze published material into the Knowledge wiki and answer questions from
  it. Use when the user says "read this", "add this to knowledge", "add this
  to the library", "ingest this report", "save this page", "what does my
  library say about X", "what do we know about X", "has anyone written about
  X", or hands over a PDF, a link, or pasted text to keep for later. Also use
  when material dictated in conversation sounds like a published claim rather
  than something that happened in a meeting, so it can be redirected to the
  right memory. The intake skill hands over what it sorted as something to
  read from a zone's Inbox, such as a newsletter; this skill finishes it.
---

# Knowledge

`Wikis/Knowledge/` holds published material: reports, papers, articles,
vendor documents, web pages. None of it carries anyone's confidence, so it
can be cited in any zone and does not need a wall check. `Wikis/Knowledge/AGENTS.md`
is the schema and wins over this file wherever the two disagree; this skill
is the procedure for using it.

This is not the Meetings wiki. Meetings holds conversations, one person's
confidence at a time, and is subject to the Walls table. Knowledge holds
things anyone could have read. The two are never mixed; see *The boundary*.

## Where things are

All paths are relative to the workspace root.

| What | Path |
|---|---|
| Frozen originals | `Wikis/Knowledge/raw/` |
| Source pages, one per item read | `Wikis/Knowledge/wiki/sources/` |
| Concept pages, one per idea | `Wikis/Knowledge/wiki/concepts/` |
| Entity pages, one per organisation or product | `Wikis/Knowledge/wiki/entities/` |
| Every page, newest first | `Wikis/Knowledge/wiki/index.md` |
| One line per ingest, newest first | `Wikis/Knowledge/wiki/log.md` |
| Schema (wins over this file) | `Wikis/Knowledge/AGENTS.md` |

`Wikis/` is its own git repository, shared by Knowledge and Meetings. A
Knowledge commit never touches a Meetings file, and the other way round.

## The boundary: what may not come in here

**Nothing from a conversation or a project ever goes into Knowledge.** A
conversation carries someone's confidence; Knowledge carries none, which is
what lets it cross every wall. Mixing the two would let a wall be laundered
through a "published" page. So a Knowledge page never has `parties` or a
`zone`, and `System/tools/check.py` treats one that does as an error.

Before ingesting anything, ask: did this come from something published, or
from something said to the user? A report, an article, a paper, a vendor's
data sheet, a public web page, a newsletter sent to a list: Knowledge. A
call, a recording, an email exchange, something a person told the user in
confidence, notes from a meeting, a client's own document: Meetings or the
project, never here.

- **"Add this to knowledge" about a recording or a transcript**: say plainly
  that a conversation belongs in Meetings, not Knowledge, and use that skill
  or wiki instead. Do not ingest it here under a different name.
- **Dictated material that sounds like a finding from a call** ("Dana told me
  their volumes are down 12%"): that is Meetings material even though it
  arrived as a spoken instruction rather than a file. Redirect it.
- **A vendor's own claim, published**: that belongs here, attributed to the
  vendor (see *Attribution*). The line is publication, not who the claim
  favours.
- **A newsletter or article that arrived by mail**: published, so it belongs
  here, even though it came through a zone's Inbox. But if it comes from a
  party's own domain, ask before treating it as published: "That newsletter
  comes from Cobalt's own domain. Is it published, or Cobalt writing to
  you?" A party writing to the user is a conversation.
- **Can't tell**: ask, rather than guess. Guessing wrong in either direction
  breaks the boundary the wiki exists to keep.

## Ingest: "read this", "add this to knowledge"

1. **Check the boundary first.** If the material is a conversation or
   something dictated from one, stop and redirect it to Meetings (above).
2. **Freeze it, before reading it for the summary.** The source must not be
   able to change under you.
   - **A URL**: fetch the page and save what was fetched (full text, or the
     saved HTML) into `raw/` before doing anything else with it. Do this
     even for a page that looks stable; sites change and re-fetching later
     will not recover today's version.
   - **A file the user hands over** (PDF, saved page, document): copy it
     unmodified into `raw/`.
   - **Pasted text**: save exactly what was pasted into `raw/` as `.txt` or
     `.md`, unedited.
   - **An item waiting in a zone's Inbox**, sorted as something to read by
     the `intake` skill: `python3 System/skills/intake/intake.py file-reading
     --file "Zones/<Zone>/Inbox/<file>" [--title "<title>"]` moves it into
     `raw/`, makes the slug, and writes a draft source page with the author
     and date filled from the mail where it has them. A file goes in
     untouched; a mail goes in with its recipients taken out, so the frozen
     copy says nothing about who received it. Carry on from step 4, and
     check the author and date against the text.
   - Name the frozen file after the source's slug (below) plus its real
     extension: `raw/<slug>.pdf`, `raw/<slug>.txt`. Once written, a raw file
     is never edited again: correct the source page, never the original.
3. **Make the slug.** Lower-case words from the title, joined with hyphens,
   letters and digits only (`fictus-2026-resilience-report`). If a source
   page with that slug already exists and this is a different item, add a
   distinguishing word rather than a number no one can say.
4. **Find what the schema needs**, and do not invent what you cannot find:
   - **author**: who wrote or published it. A named analyst, a vendor, an
     outlet.
   - **published**: the date it came out, `YYYY-MM-DD`. If the source gives
     only a month or a year, write `YYYY-MM` or `YYYY`; never guess a day.
   - **confidence**: `high` for an independent, methodical source (a named
     analyst firm, a peer-reviewed paper, a standards body); `medium` for
     reputable but not independently verified (trade press, a credible blog);
     `low` for a vendor's own claim about itself, marketing material, or
     anything unverified. A single source page can only carry one
     confidence; when it mixes vendor claims with independent analysis, rate
     it for its weakest claim and let the attribution (below) carry the
     rest of the distinction.
   - Missing author or date: ask the user, or write the source page with
     what is known and say plainly what is missing. Do not leave a
     placeholder the checker would treat as an unfinished install. Write
     prose ("author not stated") instead of an empty field.
5. **Write the source page**, `wiki/sources/<slug>.md`:

   ```yaml
   ---
   title: <title of the work>
   type: source
   author: <who wrote or published it>
   published: YYYY-MM-DD
   raw: "[[raw/<slug>]]"
   confidence: high | medium | low
   created: YYYY-MM-DD
   updated: YYYY-MM-DD
   ---
   ```

   Then a short summary. **Attribute every vendor claim to its vendor as you
   write it**: "Fictus Cloud says its Continuity Mesh product cuts failover
   time by 80%," never "Continuity Mesh cuts failover time by 80%." A claim
   with the vendor's name sanded off has quietly become a fact; it has not
   earned that.
6. **Update or create the concept pages it touches.** A concept is an idea
   that sources build up over time (*failover resilience*, not one report
   about it). For each idea this source speaks to:
   - existing page: add a bullet under `## What sources say`, citing this
     source page, and set `updated:` to today;
   - no page yet: create `wiki/concepts/<slug>.md` (schema below).
7. **Update or create the entity pages it touches.** An entity is an
   organisation, product or standard the source names. For each one:
   - existing page: add or extend a bullet under `## Claims`, citing this
     source, `updated:` to today;
   - no page yet: create `wiki/entities/<slug>.md` (schema below).
   A source naming several vendors gets an entity page per vendor, not one
   shared page: a claim belongs to the one that made it.
8. **Re-read `wiki/index.md` right before you add to it.** Another session
   may have ingested something since you last looked. Add a row for the
   source and for any concept or entity page you created, newest first. For a
   page you only touched, update its Updated cell and move its row to its
   place.
9. **Re-read `wiki/log.md` right before you append.** One line, newest on
   top: what was ingested, its author or vendor, and which concept or entity
   pages it touches.
10. **Commit, in the Wikis repository.** Stage only what this ingest wrote:
    the raw file, the source page, any concept and entity pages touched, the
    index and the log. Never `git add -A`, and never a Meetings file in the
    same commit.
    ```sh
    git -C Wikis add -- Knowledge/raw/<slug>.* Knowledge/wiki/sources/<slug>.md \
      Knowledge/wiki/concepts/<concept>.md Knowledge/wiki/entities/<entity>.md \
      Knowledge/wiki/index.md Knowledge/wiki/log.md
    git -C Wikis commit -m "Knowledge: ingested <title> (<author or vendor>)"
    ```
11. **Check it.** `python3 System/tools/check.py` catches an unfinished
    install, a link that reaches into Meetings, and a raw file changed after
    its first commit. Run it before telling the user the ingest is done.

### Concept page schema

`wiki/concepts/<slug>.md`:

```yaml
---
title: <the idea, in a few words>
type: concept
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

Then one or two sentences saying what the idea is, and:

```markdown
## What sources say

- <claim, attributed to its vendor if it is one>. [[../sources/<slug>|<Source title>]]
```

### Entity page schema

`wiki/entities/<slug>.md`:

```yaml
---
title: <organisation, product or standard>
type: entity
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

Then one or two sentences saying what it is, and:

```markdown
## Claims

- <claim, marked as its own account when it is one>. [[../sources/<slug>|<Source title>]]
```

## Answering: "what does my library say about X"

1. **Look for X** among the entity and concept page titles first, then
   source titles; match loosely (case, plurals, a close spelling).
2. **Nothing found**: say so plainly. "Nothing in the library on X." Do not
   fill the gap with general knowledge presented as the library's. That
   is answering a different question than the one asked.
3. **Something found**: read the concept or entity page, and the source
   pages it cites for anything the summary does not already cover.
4. **Cite the source page for every claim** in the answer, by title, and say
   whose claim it is when the page marks it as a vendor's own. Do not merge
   a vendor's claim with the library's independent sources into one
   undifferentiated answer.
5. **Confidence**: if every source behind an answer is `low`, or the sources
   disagree, say that plainly rather than picking a side.

Spoken: the answer first, then its source, in one or two sentences. "Only one
piece on failover resilience: Fictus Cloud's own report, claiming an 80%
cut. That's the vendor's number, not independently checked." Offer the
detail rather than reading it out.

Written: the same, then each source page linked, and its confidence.

## Examples

Ingest, typed: "Add this PDF to knowledge. It's Northwind Analytics' report
on supply-chain resilience." Freeze the PDF to
`raw/northwind-2026-supply-chain-resilience.pdf`, write
`wiki/sources/northwind-2026-supply-chain-resilience.md` with `author:
Northwind Analytics`, `confidence: high` (a named analyst firm), touch the
`failover-resilience` concept page and a `northwind-analytics` entity page,
update the index and log, commit. Reply: "Added. It's linked from failover
resilience and from Northwind Analytics' own page."

Ingest, spoken, wrong wiki: "Read this. Dana just told me on the call that
their volumes are down 12 percent." That is a meeting finding, not a
publication. Reply: "That's from your call with Dana, so it belongs in
Meetings, not the library. Want me to file it there instead?"

Question, spoken: "What does my library say about failover resilience?"
Reply: "One source, Fictus Cloud's own report, claiming an 80 percent cut in
failover time. That's their number, unverified. Nothing independent yet."

## What this skill does not do

- **It never writes conversation or project material into Knowledge**,
  however it arrives: file, mail, dictation, or a quote from earlier in the
  session. It redirects to Meetings instead, and asks when it cannot tell
  which the material is. It never gives a page `parties` or a `zone`.
- **It never edits `raw/`.** A source that needs correcting gets a corrected
  summary; the frozen original stays as it was fetched or handed over.
- **It never turns a vendor's claim into a fact** by dropping the
  attribution, in a source page, a concept page, an entity page, or a
  spoken answer.
- **It never invents an author, a date or a confidence rating it does not
  have.** It says what is missing and asks, rather than guessing to fill
  the frontmatter.
- **It never overwrites another session's addition** to `index.md` or
  `log.md`. It re-reads immediately before appending and adds to what is
  there.
- **It does not answer from general knowledge and call it the library's.**
  When the library has nothing on a question, it says so.
- **It never commits a Meetings file alongside a Knowledge one.** They share
  a repository but never a commit.

# Extra: a meeting recorder feeding the inbox

`Wikis/Meetings/raw/inbox/` is a drop folder, recorder-agnostic by design: anything that produces a `.txt`, `.md` or `.vtt` file can put it there. Audio files are not read. A dedicated recorder such as Plaud is one example, but nothing about the workspace assumes it. A phone's built-in voice memo transcript, a Zoom or Teams export, or notes you typed yourself right after a call all land the same way.

Garrick installs the inbox folder and the schema a meeting page has to meet (`Wikis/Meetings/AGENTS.md` sets it out in full: `zone` and `parties` are required before anything on the page can be used in a project). It does not install a recorder, and doesn't automate getting a file from a recorder's own app into that folder; that step is yours, whatever your recorder's export or sync mechanism happens to be.

## How to use it

Export or copy the recording's transcript (not the audio; the transcript is what gets summarised and quoted) into `Wikis/Meetings/raw/inbox/`, named however your recorder names it. Then say "process the inbox": the `intake` skill sees a transcript, which is always a conversation, and the `meetings` skill files it. Mail and other files have their own page, [ways in](ways-in.md).

To file one by hand instead, from the workspace root:

1. **Land the file** under its final name:

   ```sh
   python3 System/skills/meetings/ingest.py land --inbox "Wikis/Meetings/raw/inbox/<file>" --date 2026-09-20 --title "Birch launch pricing"
   ```

   It prints the slug, such as `260920-birch-launch-pricing`, and the path it moved the file to.

2. **Make a page for each person** on the call other than you, with their party's tag from `System/context.md`:

   ```sh
   python3 System/skills/meetings/ingest.py person --name "Theo Marsh" --party birch
   ```

   It creates `Wikis/Meetings/wiki/people/theo-marsh.md` if there isn't one, and leaves an existing page alone. On a new page, replace the line in angle brackets with who they are, in a sentence. Nothing learned in the meeting goes on a person page.

3. **Write the meeting page** as `Wikis/Meetings/wiki/sources/<slug>.md`, following the schema in `Wikis/Meetings/AGENTS.md`: title, date, zone, parties, the people pages, a link back to the raw file, then what was decided and who said what where the wording matters.

4. **Rebuild the index and log the ingest:**

   ```sh
   python3 System/skills/meetings/ingest.py index
   python3 System/skills/meetings/ingest.py log --slug 260920-birch-launch-pricing --title "Birch launch pricing" --zone Work --parties birch
   ```

5. **Commit in the `Wikis` repository**: the raw file, the meeting page, any new person page, the index and the log. Actions you owe go in the zone's `Todo.md`, committed in the zone's own repository.

The raw file itself is never edited once it's filed; if the summary is wrong, correct the summary, not the source.

## What it adds

Automatic, accurate capture of what was actually said, instead of relying on notes taken during the call or memory afterward. A recorder like Plaud also handles the transcription step for you, so what lands in the inbox is already text.

## What you lose without it

Nothing about the pipeline itself. You can type a summary directly into `raw/inbox/` as a `.md` file right after a call, with no recorder involved at all, and it goes through exactly the same filing process. What you lose is the recorder's own accuracy and convenience, not any capability of the workspace.

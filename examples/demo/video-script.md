# The three-minute demo: shot list

Sam Rivera runs his day by voice on the demo workspace. It is Tuesday 29 September 2026. Theo Marsh at Birch & Co rang last night straight out of his board meeting, and the recorder has already put that call in the Meetings inbox. Four mails from the same day are saved in the Work zone's inbox. Build the workspace fresh before every take (see *Capture*).

Each beat gives what Sam says, what the assistant should say back, and what is on screen. The replies are the spoken forms the skills prescribe: `threads` for open, list, wrap and close, `intake` for the inbox, `meetings` for the prep. If a reply comes out longer or different on the day, the skill is what's wrong, not the script. Note it and fix the skill.

## 1. Open a thread (0:00 to 0:20)

**Sam:** "Open launch plan."

**Assistant:** "Launch plan: the outline's drafted, and timing and budget are waiting on the board's decision, due Monday the 28th. Next is filling them in once Theo calls."

**Screen:** the Launch Plan note in Birch Entry, with its Resume here block. Caption: *One resume point per thread. It reads that and nothing else.*

## 2. What's open (0:20 to 0:40)

**Sam:** "What's open?"

**Assistant:** "Six open. Most recent: launch plan, freight terms, supplier map, carrier choice and kitchen, plus one more."

**Screen:** the folder tree, with Work (Acme Review, Birch Entry) and Personal (House) side by side. Caption: *Work and Personal. Separate folders, separate histories.*

## 3. Process the inbox (0:40 to 1:20)

**Sam:** "Process the inbox."

**Assistant:** "Five waiting: Theo's call and four mails. Filed the call with Theo: the board said yes to a March launch, and you owe him the draft by Friday the 9th. The newsletter went to the library, Dana's forecast and Owen's quotes are in Acme, but Marta's mail copies both Acme and Birch, who are walled: Acme, Birch, or both?"

**Sam:** "Both."

**Assistant:** "Filed under both, so neither project can draw on it."

**Screen:** the transcript leaves `raw/inbox/`, a new meeting page opens (zone Work, parties `birch`), and the Work to-do list gains its line. Then the four mails leave `Zones/Work/Inbox/`: the newsletter lands in the Knowledge wiki with no parties, Owen's sheet in Acme Review's `Sources/`, and the Cobalt mail's page shows parties `acme`, `birch` and `cobalt`. Caption: *Everything is filed where it belongs: conversations with their zone and parties, reading in the library, a client's file in its project. When a mail sits on both sides of a wall, it asks.*

## 4. Prep me for Cobalt (1:20 to 1:55). The wall holds

**Sam:** "Prep me for Cobalt."

**Assistant:** "Cobalt: you last met Marta Quill on the 22nd, with Iris, and she quoted about 140 euros a pallet from March. You owe her Birch's volume forecast by Friday the 2nd. A wall kept some meeting material out of this brief."

**Screen:** first the Meetings index with both Cobalt calls visible, *Cobalt Freight renewal, for Acme* on 15 September and *Cobalt Freight northern lane, for Birch* on 22 September. Then the Walls table in `System/context.md`, with `acme` and `birch` on one row. Caption: *Sam met Cobalt twice, once for each client. Only one of those calls is Birch's to use.*

The video is built around this beat. The brief is for Birch, because Launch Plan is the thread in focus. The Acme-side call is left out entirely: Cobalt's offer to Acme and what Marta said about northern capacity. The only trace is that last sentence, which never says what was held back or whose it was.

## 5. Wrap (1:55 to 2:20)

**Sam:** "Board said March, and Theo's budget comes Wednesday. Wrap launch plan."

**Assistant:** "Launch plan wrapped. Next is the draft for Theo, due Friday the 9th; his budget should land Wednesday."

**Screen:** the Resume here block rewritten in place, a new dated entry above the older ones, then `git log` in the Work zone showing the new commit on top of September's history. Caption: *Wrapped means anyone can pick it up cold. Git keeps every version.*

## 6. Close for the day (2:20 to 2:40)

**Sam:** "Close for the day."

**Assistant:** "Only launch plan changed today, and it's already wrapped. First thing tomorrow is the draft for Theo, due Friday the 9th."

**Screen:** the terminal, nothing else. Caption: *Every thread touched today is wrapped and committed.*

As written today, the `threads` skill would wrap launch plan a second time here and add a duplicate dated entry. The reply above assumes the fix proposed alongside this demo: skip a thread already wrapped this session with nothing changed since. Until that fix lands, film this beat before beat 5 or leave it out.

## 7. The check, read aloud (2:40 to 3:00)

**Sam:** "Run the check."

**Assistant:** "All clear."

**Screen:** `python3 System/tools/check.py`, ending in *No problems found.* Caption: *Plain files, on your own disk, under git. Any assistant that reads AGENTS.md can run it.*

## For guided sessions: the wall, broken on purpose

After the take, show what the check does when someone crosses a wall. Paste a link to the Acme-side Cobalt call into the Launch Plan note:

    [[Meetings/wiki/sources/260915-cobalt-renewal-for-acme|the renewal call]]

Then "run the check" again. It fails with one error under Walls, naming the Launch Plan note and the wall between `birch` and `acme`. Delete the line and it's all clear again.

## Capture

The workspace comes from `python3 examples/demo/build.py --target ~/Garrick-demo`. Rebuild into an empty folder before each take (it takes about ten seconds), so the inboxes hold Theo's call and the four mails, and the history ends on 26 September. Record on a Mac with the built-in screen recorder (Cmd-Shift-5) and a decent microphone. On screen is one terminal at the workspace root running Claude Code or Codex. Sam speaks through macOS Dictation or through the assistant's own voice input. Before recording, tell the assistant you are listening, so it answers in spoken form from the first beat. Everything else is optional and not part of Garrick. Obsidian beside the terminal makes the notes, meeting pages and to-do lists visible as they change. A terminal app such as cmux gives one tab per thread. A phone app (Claude Code Remote Control, Codex Remote, or a third-party client) lets you film Sam talking from a phone instead of the desk. macOS Spoken Content can read the replies aloud if you want them heard as well as shown. The wrap writes the machine's own date into the note: film on the 29th with the clock left alone, or accept that the dated entry shows the day you filmed.

# Extra: cmux, one terminal tab per thread

Garrick's own idea of a thread, one line of work with one resume point, doesn't care how many terminal windows you have open, or whether you have any open at all beyond the one you're typing in. cmux is a terminal built for running several agent sessions side by side, one workspace per tab, which maps cleanly onto Garrick's model: a tab for the thread you're picking up, and a hooked session per tab that resumes where it left off when you come back to it.

Garrick ships nothing that talks to cmux directly. There's no bundled skill or config for it in `System/skills`; using it is a matter of opening one cmux tab per active thread, in the zone folder that thread lives in, the same way you'd open one plain terminal tab per thread without it.

## How to use it

Run cmux against the workspace the way you'd run it against any repository: one tab per thread you're actively working, started in that thread's folder or its zone's, then "open [thread]" to the assistant inside it. cmux's own session hooks handle resuming that tab's history; Garrick's own resume point, the thread's `### Resume here` block, is what tells you and the assistant where the actual work stands, independent of whether the terminal session itself was ever closed.

## What it adds

A sidebar of live sessions instead of juggling terminal tabs by hand, hooks that record and resume a session automatically, and a CLI you can script against if you want to automate opening a set of tabs for the threads you work most often.

## What you lose without it

Nothing about Garrick itself. One thread at a time, in whatever terminal or terminal tab you already use, works exactly the same: the resume point lives in the thread note, not in cmux's session state, so closing a plain terminal and opening a new one loses you nothing that "open [thread]" doesn't put straight back in front of you.

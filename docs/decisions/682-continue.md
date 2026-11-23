---
concept: Continue
issue: https://github.com/iamvenuti/garrick/issues/682
---

# Continue

**The concept.** Continue is the request that asks Claude where a piece of work stands and opens Claude's desktop app on that session. Since 0.80.0 no button sends it.

**What it touches.** It sat behind *Open in Claude* on the cards, the graph, the app's menu and panel, and Your work. Settings now has one row for each assistant app, which opens a new session through the app's link (#652). `page_action.py` keeps the `continue` verb, so an older page still works, and nothing in the page or the app sends it.

**What was measured.** Two rows named the same app and ended in the same place, a session in that app on that thread, and the user had to know how each route worked to choose. The command-line route needed Claude Code's command-line tool, signed in; the new-session route needs only the app.

**What would show it is wrong.** Users asking for Claude's answer on screen when they open a thread, or a new session that keeps coming up empty where Continue's session did not.

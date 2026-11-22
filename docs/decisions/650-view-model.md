---
concept: View model
issue: https://github.com/iamvenuti/garrick/issues/650
---

# View model

**The concept.** The core builds one JSON document of the workspace, and the Garrick App only draws it.

**What it touches.** It sits beside *Piece of work*, which it reads through the one reader, and *The Garrick App*, which it feeds. It uses the declared operations to say what each piece may do, and it keeps *Wall* intact: each record carries its zone and a count is of one zone.

**What was measured.** The page's old reads, frozen word for word in a test, were compared with the view model on invented workspaces covering every project shape, a parked project, a checkpoint, a link used as a zone and an inbox that leads out of its zone. The two agree on every row; the only differences are two walls the old read missed, named in the test. The page built before and after each moved section was compared byte for byte.

**What would show it is wrong.** A card that shows something the view model does not hold, a change in wording that needs a change in the view model, or a page that differs from the one before it on the same workspace.

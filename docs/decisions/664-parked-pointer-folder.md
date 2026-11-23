---
concept: The parked pointer folder
issue: https://github.com/iamvenuti/garrick/issues/664
---

# The parked pointer folder

**The concept.** A parked thread's memory pointer is moved to `parked/`, in the assistant's memory folder, and its line leaves the memory index until the thread wakes. The move deletes nothing; finishing a thread is the one case that does.

**What it touches.** It sits beside the memory index (`MEMORY.md`), the threads skill's *Park*, *Wake* and *Finish*, the status page's *Park* and *Wake*, `check.py`'s budget warning and Nurture's mechanical fix. It does not touch a zone's repository: the memory folder is outside the workspace and the move is not committed.

**What was measured.** In one workspace the index reached 21,800 characters for 103 pointers, almost three times `System/context.md`, and a quarter of the pointers were parked threads. A test parks and wakes a thread in an invented workspace and compares the index with what it was, character for character.

**What would show it is wrong.** A session that needs a parked thread's pointer, does not find it, and loses something the thread note did not hold. Or a pointer that does not come back exactly. Either one would put the pointers back in the index.

**Choices to know.** The boundary a pointer holds is kept in the thread note by a sentence in the threads skill's *Park* step, since no check can tell a boundary from other text without guessing. Nurture offers the move of a parked or done thread's pointer, files the finding under `System`, and applies it on one yes, never in the nightly run. The move refuses a memory folder inside the workspace's `Zones/`, `Wikis/` or `System/`, an index or `parked/` that is a link, and a kept line that holds a line break; it says so and moves nothing.

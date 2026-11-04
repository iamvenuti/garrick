#!/usr/bin/env python3
"""Recall: a local keyword index over the notes, the wikis and past sessions,
ranked, with the walls applied before anything is returned (#341).

    python3 System/tools/recall.py build [--root DIR]
    python3 System/tools/recall.py search "words" [--project DIR] [--after YYYY-MM-DD]
                                         [--zone Z] [--wiki W] [--sessions] [--limit N]
    python3 System/tools/recall.py stats

Python standard library only (Python 3.9 floor). An index is a cache: one
gitignored SQLite file inside each zone and each wiki, rebuilt from the files
it covers.

Other code (the Ask agent's `search` tool) calls `search()`. Its signature and
the fields of `Result` are stable.
"""

import dataclasses
from pathlib import Path
from typing import List, Optional, Union

PathLike = Union[str, Path]


@dataclasses.dataclass(frozen=True)
class Result:
    """One hit. `path` is relative to the workspace root, with forward slashes.
    `source` names where it came from: a zone ("Work"), a wiki ("Meetings",
    "Knowledge") or "sessions". `date` is YYYY-MM-DD or "". `grade` is
    "working", "dormant" or "archived"; a dormant hit is "from older notes"."""
    id: str
    path: str
    title: str
    date: str
    source: str
    snippet: str
    score: float
    grade: str = "working"


def search(words: str, *, project: Optional[PathLike], after: Optional[str] = None,
           zone: Optional[str] = None, wiki: Optional[str] = None, sessions: bool = False,
           limit: int = 10, root: Optional[PathLike] = None) -> List[Result]:
    """Ranked hits for `words`, best first, at most `limit`.

    `project` is the folder of the project the session works in (absolute, or
    relative to the workspace root), for example `Zones/Work/Acme`. Its zone
    and its hub's `party:` decide which rows may be returned. `None` means a
    session opened at the workspace root or in `System/`, which has no party
    and may read every zone and `System/.sessions/`.

    `after` keeps only hits dated on or after YYYY-MM-DD. `zone` adds another
    zone's index (the project's own zone is always searched); `wiki` limits
    the search to one wiki. `sessions=True` adds extracted sessions: the
    project's own zone's, or from a root session all of them. `root` is the
    workspace root; it defaults to the one above `project`, or above the
    current folder.

    THE WALLS ARE APPLIED INSIDE THIS FUNCTION, BEFORE ANYTHING IS RETURNED.
    A row whose parties are walled from the project's party is dropped before
    ranking, so it is not returned, not counted and not in a snippet. A
    Meetings page with no zone or no parties is dropped too. Knowledge is not
    filtered. Counts and headers built from the returned list therefore
    include only what the caller may see; a caller must never count rows
    any other way.
    """
    raise NotImplementedError("recall.search is not built yet")

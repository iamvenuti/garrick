# Published

What left the workspace from this project, and which copy counts from now on.
One row for every file that went out: the day it went, the file, where it
went, who received it, and whose copy is the one to edit next. The last cell
is read by its first word. `share` means colleagues edit it where it landed,
so the shared copy is home from now on and `Deliverables/` keeps the build
inputs and a frozen snapshot of what was handed over. `here` means nobody
else edits it, or they only read it, so the copy here stays the one that
counts and the shared copy is disposable. A clause may follow either word,
such as who edits it there.

A row is never deleted, because the row is the record of what left. When a
copy comes off the share its date cell becomes `withdrawn YYYY-MM-DD`, and
when a newer version takes its place, `replaced YYYY-MM-DD`, the day it
happened; a file sent by mail rather than placed on a share is dated `sent
YYYY-MM-DD`. Such a row is history, and is never compared again.

`python3 System/tools/drift.py` compares each row's file with its copy on the
share from then on, and `check.py` warns about a row it cannot read, since
that file stops being watched.

## What left

| Date | File | Destination | Recipients | Authoritative |
|---|---|---|---|---|

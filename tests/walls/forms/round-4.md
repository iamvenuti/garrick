# Round 4 of the 0.59.1 review

The four honest forms the 0.59.1 reviews left open. Each names a file of a project's harness folder, which exists and
so resolves: a link or a path the vault finds is refused across the wall, with no line of its own.

### wikilink to a harness path
far: refused
near: passed
~~~~~
# Notes

See [[{harness}]] now.
~~~~~

### absolute path to a harness file
far: refused
near: passed
~~~~~
# Notes

See `{abspath}` now.
~~~~~

### obsidian uri to a harness file
far: refused
near: passed
~~~~~
# Notes

See [x](obsidian://open?vault=Workspace&file={harnessuri}) now.
~~~~~

### file autolink to a harness file
far: refused
near: passed
~~~~~
# Notes

See <file://{abspath}> now.
~~~~~

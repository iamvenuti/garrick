# Round 3 of the 0.59.1 review

Bracket classes that match a `/`: a glob whose last name seems to hold no page's name, and spans two.

### class holding a slash in a link
far: refused
near: passed
~~~~~
# Notes

See [the page](people[/]{pname}) now.
~~~~~

### class holding a slash in a wikilink
far: refused
near: passed
~~~~~
# Notes

See [[people[/]{pname}]] now.
~~~~~

### class holding a slash and a star
far: refused
near: passed
~~~~~
# Notes

See `people[/]{pstar}` now.
~~~~~

### class holding a slash and a dash
far: refused
near: passed
~~~~~
# Notes

See `people[/-]{pname}` now.
~~~~~

### class spanning a slash in a range
far: refused
near: passed
~~~~~
# Notes

See `people[.-/]{pname}` now.
~~~~~

### two classes
far: refused
near: passed
~~~~~
# Notes

See `wiki[/]people[/]{pname}` now.
~~~~~

### class with a backslash
far: refused
near: passed
~~~~~
# Notes

See `people[/\]{pname}` now.
~~~~~

### negated class
far: refused
near: passed
~~~~~
# Notes

See `people[!x]{pname}` now.
~~~~~

### class in a path
far: refused
near: passed
~~~~~
# Notes

See `wiki/people[/]{pname}` now.
~~~~~

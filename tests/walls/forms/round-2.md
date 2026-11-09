# Round 2 of the 0.58.0 review

### typographic quotes in code
far: refused
near: passed
~~~~~
# Notes

See `“{person}”` now.
~~~~~

### typographic quotes in prose
far: refused
near: passed
~~~~~
# Notes

See “{person}” now.
~~~~~

### guillemets
far: refused
near: passed
~~~~~
# Notes

See «{person}» now.
~~~~~

### trailing punctuation
far: refused
near: passed
~~~~~
# Notes

See `{person}?`, `{person},` and `{person})` now.
~~~~~

### trailing full stop in prose
far: refused
near: passed
~~~~~
# Notes

It is in {person}.
~~~~~

### invisible characters
far: by design
near: passed
~~~~~
# Notes

See `wiki/people/<U+200B>{pname}` and `{person}<U+2060>` now.
~~~~~

### soft hyphen
far: by design
near: passed
~~~~~
# Notes

See `wiki/people/<U+00AD>{pname}` now.
~~~~~

### html entities for the slash
far: by design
near: passed
~~~~~
# Notes

See wiki&#47;people&#47;{pname} and wiki&sol;people&sol;{pname} now.
~~~~~

### inline html tags
far: by design
near: passed
~~~~~
# Notes

See <b>wiki</b>/people/{pname} now.
~~~~~

### leading-star glob
far: by design
near: passed
~~~~~
# Notes

See `wiki/people/*{ptail}` now.
~~~~~

### frontmatter flow list
far: refused
near: passed
~~~~~
---
related: [x, {person}]
---

x
~~~~~

### frontmatter quoted value
far: refused
near: passed
~~~~~
---
related: "{person}"
---

x
~~~~~

### frontmatter nested key
far: refused
near: passed
~~~~~
---
meta:
  ref: Wikis/Meetings/{person}
---

x
~~~~~

### frontmatter block scalar
far: refused
near: passed
~~~~~
---
note: |
  see {person}
---

x
~~~~~

### obsidian link parameters
far: refused
near: passed
~~~~~
# Notes

See [x](obsidian://open?vault=v&file=wiki%2Fpeople%2F{pname}) now.
~~~~~

### obsidian link with a path parameter
far: refused
near: passed
~~~~~
# Notes

See <obsidian://open?path=Wikis/Meetings/{person}.md> now.
~~~~~

### prose path with spaces
far: by design
near: passed
~~~~~
# Notes

See {dec} now.
~~~~~

### percent-encoded backslash
far: by design
near: passed
~~~~~
# Notes

See `wiki%5Cpeople%5C{pname}` now.
~~~~~

### percent-encoded slash
far: by design
near: passed
~~~~~
# Notes

See `wiki%2Fpeople%2F{pname}` now.
~~~~~

### word prefix
far: by design
near: passed
~~~~~
# Notes

See `HEAD:Wikis/Meetings/{person}.md` and `host:{person}` now.
~~~~~

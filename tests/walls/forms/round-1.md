# Round 1 of the 0.58.0 review

### file autolink
far: refused
near: passed
~~~~~
# Notes

See <file:///x/Wikis/Meetings/{person}> now.
~~~~~

### file autolink with one slash
far: refused
near: passed
~~~~~
# Notes

See <file:/Wikis/Meetings/{person}> now.
~~~~~

### frontmatter plain value
far: refused
near: passed
~~~~~
---
related: {person}
---

x
~~~~~

### frontmatter list value
far: refused
near: passed
~~~~~
---
related:
  - Wikis/Meetings/{person}
---

x
~~~~~

### indented code
far: refused
near: passed
~~~~~
# Notes

para

    {person}
~~~~~

### indented command
far: refused
near: passed
~~~~~
# Notes

para

	cat {person}.md
~~~~~

### html code
far: refused
near: passed
~~~~~
# Notes

See <code>{person}</code> now.
~~~~~

### html pre
far: refused
near: passed
~~~~~
# Notes

<pre>
{person}
</pre>
~~~~~

### html comment
far: refused
near: passed
~~~~~
# Notes

<!-- {person} -->
~~~~~

### long span
far: refused
near: passed
~~~~~
# Notes

See `{long}cat {person}` now.
~~~~~

### prose slash path
far: refused
near: passed
~~~~~
# Notes

See {person} now.
~~~~~

### at sign prefix
far: by design
near: passed
~~~~~
# Notes

See `@{person}` now.
~~~~~

### path prefix
far: by design
near: passed
~~~~~
# Notes

See `path:{person}` now.
~~~~~

### sigil prefixes
far: refused
near: passed
~~~~~
# Notes

See `!{person}`, `${person}` and `~{person}` now.
~~~~~

### full-width slash
far: by design
near: passed
~~~~~
# Notes

See `wiki／people／{pname}` now.
~~~~~

### line-range suffix
far: by design
near: passed
~~~~~
# Notes

See `{person}:3-5`, `{person}.md:3-5` and `{person}::Heading` now.
~~~~~

### glob
far: by design
near: passed
~~~~~
# Notes

See `wiki/people/{pstar}` now.
~~~~~

### backslash escape
far: by design
near: passed
~~~~~
# Notes

See `wiki/people/{pesc}` now.
~~~~~

### underscore for a hyphen
far: by design
near: passed
~~~~~
# Notes

See `wiki/people/{punder}` now.
~~~~~

### space for a hyphen
far: by design
near: passed
~~~~~
# Notes

See `wiki/people/{pspace}` now.
~~~~~

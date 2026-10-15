#!/usr/bin/env python3
"""guide.py: Garrick's own docs, read inside the Garrick App, and the
Markdown renderer the app draws them and the release notes with.

install.py copies the release's `docs/` into the workspace as
`System/garrick-docs/`, and update.py replaces that copy with each release,
as it does the release notes in `System/garrick-changelog.md`. `status.py`
asks `guide()` for its Guide tab. Every link is settled when the page is
built, because the Mac app may read nothing outside `System/generated/` and
both it and the Obsidian plugin send any link that is not an anchor on the
page itself to another app:

- a link from one doc page to another, with or without a heading, becomes an
  anchor on the page, so it stays in the tab and lands on that heading;
- a link into Garrick outside `docs/` (`../template/...`, `../extras/...`)
  becomes that file on GitHub, at the release the workspace runs, and opens
  in the browser like any web link;
- an image is carried in the page as a `data:` URI.

The pages go into the page as the text of a <script type="text/html"> at the
very end of it, after every script the other tabs run, which the browser
reads past without parsing, laying out or decoding any of it. So the Guide
costs the other tabs nothing until it is opened.

`inline()` and `blocks()` are the one renderer. Without a way to resolve
links they keep a link's text only, which is how the release notes are drawn.
Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import base64
import html
import posixpath
import re
import urllib.parse
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

E = html.escape
PROJECT = "https://github.com/iamvenuti/garrick"
DOCS = ("System", "garrick-docs")
PREFIX = "guide-"
# The contents, in reading order. A page this does not list goes at the end of
# Extras when it is in docs/extras/, and at the end of Look up otherwise; the
# extras pages follow docs/extras/index.md, in the order it links them.
SECTIONS = (("Start here", ("try-it-safely", "first-steps", "terminal-setup", "first-session", "guided-session")),
            ("Understand", ("principles", "concepts", "architecture", "enforced", "harnesses")),
            ("Do", ("updating",)),
            ("Extras", ("extras/index",)),
            ("Look up", ("commands",)))
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp", ".svg": "image/svg+xml"}
OUTSIDE = ("http://", "https://", "mailto:")

# --------------------------------------------------------------------------- inline

CODE = re.compile(r"(`+)(.+?)(?<!`)\1(?!`)", re.S)
TARGET = r'\(\s*<?((?:[^()\s<>]|\([^()\s<>]*\))+)>?(?:\s+"[^"]*")?\s*\)'    # a link's target, one level of brackets in it
IMAGE = re.compile(r'!\[([^\]]*)\]' + TARGET)
LINK = re.compile(r'\[((?:[^\[\]]|\[[^\[\]]*\])+)\]' + TARGET)
AUTOLINK = re.compile(r"<(https?://[^\s<>]+)>")
WIKILINK = re.compile(r"\[\[([^\]|]*\|)?([^\]]*)\]\]")
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<![\w*])\*([^*]+)\*(?![\w*])")
HELD = re.compile(r"\x00(\d+)\x00")

Resolve = Optional[Callable[[str], Optional[str]]]


def _code(text: str) -> str:
    if len(text) > 2 and text[0] == text[-1] == " " and text.strip():
        text = text[1:-1]
    return text


def inline(s: str, link: Resolve = None, image: Resolve = None) -> str:
    """One line or paragraph of Markdown as HTML: code, images, links,
    bold, italics and wikilinks, everything else escaped. `link` turns a
    link's target into an href, or None to keep its text only; without it
    every link keeps its text. `image` turns an image's source into a
    `data:` URI, or None to show its description instead."""
    held: List[str] = []

    def hold(h: str) -> str:
        held.append(h)
        return "\x00%d\x00" % (len(held) - 1)

    s = s.replace("\x00", "")
    s = CODE.sub(lambda m: hold("<code>%s</code>" % E(_code(m.group(2)))), s)

    def img(m):
        uri = image(m.group(2)) if image else None
        if not uri:
            return hold(E(m.group(1)))
        return hold('<img src="%s" alt="%s" loading="lazy">' % (E(uri), E(plain(m.group(1)))))
    s = IMAGE.sub(img, s)

    def anchor(text: str, href: str) -> str:
        to = link(href) if link else None
        if not to:
            return text
        out = ' target="_blank" rel="noopener"' if to.startswith(OUTSIDE) else ""
        return hold('<a href="%s"%s>' % (E(to), out)) + text + hold("</a>")
    s = LINK.sub(lambda m: anchor(m.group(1), m.group(2)), s)
    s = AUTOLINK.sub(lambda m: anchor(m.group(1), m.group(1)), s)
    s = E(s)
    s = BOLD.sub(r"<b>\1</b>", s)
    s = ITALIC.sub(r"<i>\1</i>", s)
    s = WIKILINK.sub(lambda m: m.group(2).rsplit("/", 1)[-1], s)   # [[a/b|c]] reads c, [[a/b]] reads b
    return HELD.sub(lambda m: held[int(m.group(1))], s)


def plain(s: str) -> str:
    """What a reader sees of a line of Markdown, as text: for headings' anchors and the contents."""
    s = CODE.sub(lambda m: _code(m.group(2)), s)
    s = IMAGE.sub(lambda m: m.group(1), s)
    s = LINK.sub(lambda m: m.group(1), s)
    s = WIKILINK.sub(lambda m: m.group(2).rsplit("/", 1)[-1], s)
    s = BOLD.sub(r"\1", s)
    return ITALIC.sub(r"\1", s)


def slug(text: str) -> str:
    """A heading's anchor as GitHub makes it, so the docs' own #links work."""
    s = re.sub(r"[^\w\- ]", "", plain(text).strip().lower())
    return s.replace(" ", "-")


# --------------------------------------------------------------------------- blocks

FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*([^`\s]*)")
HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
ITEM = re.compile(r"^( {0,3})([-*+]|\d{1,9}[.)])( +|$)")
QUOTE = re.compile(r"^ {0,3}> ?")
SEPARATOR = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _cells(line: str) -> List[str]:
    """A table row's cells, split on every | not escaped, as GitHub splits them."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    out, cur, i = [], "", 0
    while i < len(s):
        if s[i] == "\\" and s[i + 1:i + 2] == "|":
            cur += "|"
            i += 2
            continue
        if s[i] == "|":
            out.append(cur.strip())
            cur = ""
        else:
            cur += s[i]
        i += 1
    out.append(cur.strip())
    return out


class Renderer:
    """Blocks of Markdown as HTML: headings, paragraphs, lists, quotes,
    fenced and indented code, tables and rules. `shift` moves every heading
    down that many levels (the release notes draw ### as <h5>); `anchor`
    gives a heading's id from its level and text, or None for none."""

    def __init__(self, link: Resolve = None, image: Resolve = None, shift: int = 0,
                 anchor: Optional[Callable[[int, str], Optional[str]]] = None):
        self.link, self.image, self.shift, self.anchor = link, image, shift, anchor
        self.headings: List[Tuple[int, str, str]] = []    # (level, id, text), in order

    def inline(self, s: str) -> str:
        return inline(s, self.link, self.image)

    def starts(self, lines: List[str], i: int) -> bool:
        """Whether line i begins a block that ends a paragraph."""
        line = lines[i]
        if FENCE.match(line) or HEADING.match(line) or RULE.match(line) or QUOTE.match(line):
            return True
        m = ITEM.match(line)
        if m and line[m.end():].strip() and (not m.group(2)[0].isdigit() or m.group(2)[:-1] == "1"):
            return True
        return self.table_at(lines, i)

    def table_at(self, lines: List[str], i: int) -> bool:
        return ("|" in lines[i] and i + 1 < len(lines) and "-" in lines[i + 1]
                and bool(SEPARATOR.match(lines[i + 1])) and len(_cells(lines[i])) == len(_cells(lines[i + 1])))

    def render(self, text: str) -> str:
        return self.blocks(text.expandtabs(4).splitlines())

    def blocks(self, lines: List[str], tight: bool = False) -> str:
        out: List[str] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            if line.lstrip().startswith("<!--"):                      # a comment: left out
                while i < n and "-->" not in lines[i]:
                    i += 1
                i += 1
                continue
            m = FENCE.match(line)
            if m:
                pad, fence, lang = len(m.group(1)), m.group(2), m.group(3)
                body: List[str] = []
                i += 1
                while i < n and not (lines[i].strip().startswith(fence[0] * len(fence))
                                     and not lines[i].strip().strip(fence[0])):
                    body.append(lines[i][min(pad, _indent(lines[i])):])
                    i += 1
                i += 1
                cls = ' class="lang-%s"' % E(lang) if lang else ""
                out.append("<pre><code%s>%s</code></pre>" % (cls, E("\n".join(body))))
                continue
            m = HEADING.match(line)
            if m:
                level, text = len(m.group(1)), (m.group(2) or "").strip()
                shown = min(6, level + self.shift)
                hid = self.anchor(level, text) if self.anchor else None
                if hid:
                    self.headings.append((level, hid, plain(text)))
                out.append("<h%d%s>%s</h%d>" % (shown, ' id="%s"' % E(hid) if hid else "", self.inline(text), shown))
                i += 1
                continue
            if RULE.match(line):
                out.append("<hr>")
                i += 1
                continue
            if QUOTE.match(line):
                body = []
                while i < n and lines[i].strip() and (QUOTE.match(lines[i]) or body):
                    q = QUOTE.match(lines[i])
                    body.append(lines[i][q.end():] if q else lines[i])
                    i += 1
                out.append("<blockquote>%s</blockquote>" % self.blocks(body))
                continue
            if ITEM.match(line):
                i = self.list(lines, i, out)
                continue
            if self.table_at(lines, i):
                i = self.table(lines, i, out)
                continue
            if _indent(line) >= 4:
                body = []
                while i < n and (not lines[i].strip() or _indent(lines[i]) >= 4):
                    body.append(lines[i][4:])
                    i += 1
                while body and not body[-1].strip():
                    body.pop()
                out.append("<pre><code>%s</code></pre>" % E("\n".join(body)))
                continue
            para = [line.strip()]
            i += 1
            while i < n and lines[i].strip() and not self.starts(lines, i):
                para.append(lines[i].strip())
                i += 1
            text = self.inline(" ".join(para))
            out.append(text if tight else "<p>%s</p>" % text)
        return "".join(out)

    def list(self, lines: List[str], i: int, out: List[str]) -> int:
        first = ITEM.match(lines[i])
        ordered = first.group(2)[0].isdigit()
        items: List[List[str]] = []
        loose = False
        n = len(lines)
        while i < n:
            m = ITEM.match(lines[i])
            if not m or m.group(2)[0].isdigit() != ordered:
                break
            gap = len(m.group(3))
            width = len(m.group(1)) + len(m.group(2)) + (gap if 1 <= gap <= 4 else 1)
            body = [lines[i][width:] if gap <= 4 else lines[i][len(m.group(1)) + len(m.group(2)) + 1:]]
            i += 1
            while i < n:
                line = lines[i]
                if not line.strip():
                    j = i
                    while j < n and not lines[j].strip():
                        j += 1
                    if j < n and _indent(lines[j]) >= width:
                        body.extend([""] * (j - i))
                        i = j
                        continue
                    break
                if _indent(line) >= width:
                    body.append(line[width:])
                    i += 1
                    continue
                if body[-1].strip() and not ITEM.match(line) and not self.starts(lines, i):
                    body.append(line.strip())                         # a paragraph's lazy continuation
                    i += 1
                    continue
                break
            items.append(body)
            j = i
            while j < n and not lines[j].strip():
                j += 1
            nxt = ITEM.match(lines[j]) if j < n else None
            if j > i and nxt and nxt.group(2)[0].isdigit() == ordered:
                loose = True
                i = j
            elif j > i:
                break
        tag = "ol" if ordered else "ul"
        start = int(first.group(2)[:-1]) if ordered else 1
        out.append("<%s%s>" % (tag, ' start="%d"' % start if start != 1 else ""))
        for body in items:
            while body and not body[-1].strip():
                body.pop()
            tight = not loose and all(l.strip() for l in body)
            out.append("<li>%s</li>" % self.blocks(body, tight=tight))
        out.append("</%s>" % tag)
        return i

    def table(self, lines: List[str], i: int, out: List[str]) -> int:
        head = _cells(lines[i])
        aligns = []
        for c in _cells(lines[i + 1]):
            c = c.strip()
            aligns.append("center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":")
                          else "left" if c.startswith(":") else "")
        i += 2
        rows = []
        while i < len(lines) and lines[i].strip() and "|" in lines[i] and not (
                FENCE.match(lines[i]) or HEADING.match(lines[i]) or QUOTE.match(lines[i])):
            rows.append(_cells(lines[i]))
            i += 1

        def cell(tag: str, k: int, text: str) -> str:
            style = ' style="text-align:%s"' % aligns[k] if k < len(aligns) and aligns[k] else ""
            return "<%s%s>%s</%s>" % (tag, style, self.inline(text), tag)
        width = len(head)
        body = "".join("<tr>%s</tr>" % "".join(cell("td", k, (r + [""] * width)[k]) for k in range(width)) for r in rows)
        out.append('<div class="gd-table"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
                   % ("".join(cell("th", k, t) for k, t in enumerate(head)), body))
        return i


def blocks(text: str, link: Resolve = None, image: Resolve = None, shift: int = 0) -> str:
    """Markdown as HTML, with no anchors on its headings."""
    return Renderer(link, image, shift).render(text)


# --------------------------------------------------------------------------- the docs

def release_ref(changelog: Optional[str], edge: bool = False) -> str:
    """The tag on GitHub that matches the workspace's docs: the newest release
    its release notes name, such as v0.29.0. A workspace that follows main, or
    one whose release is not known, reads main."""
    if edge or not changelog:
        return "main"
    for line in changelog.splitlines():
        m = re.match(r"^## \[v?(\d+(?:\.\d+)+(?:-[0-9A-Za-z.-]+)?)\]", line)
        if m:
            return "v" + m.group(1)
    return "main"


def page_key(rel: str) -> str:
    """A page's name in the Guide's anchors: extras/cmux.md is extras-cmux."""
    return rel[:-3].replace("/", "-") if rel.endswith(".md") else rel.replace("/", "-")


def page_id(rel: str, heading: str = "") -> str:
    return PREFIX + page_key(rel) + ("--" + heading if heading else "")


def doc_pages(docs: Path) -> List[str]:
    """Every Markdown page under the docs folder, by its path from there."""
    return sorted(p.relative_to(docs).as_posix() for p in docs.rglob("*.md")
                  if p.is_file() and not any(part.startswith(".") for part in p.relative_to(docs).parts))


def contents(docs: Path, pages: List[str]) -> List[Tuple[str, List[str]]]:
    """The pages under each heading of the contents, in reading order."""
    listed: Dict[str, List[str]] = {}
    for title, names in SECTIONS:
        listed[title] = [n + ".md" for n in names if n + ".md" in pages]
    index = docs / "extras" / "index.md"
    try:
        text = index.read_text(encoding="utf-8")
    except OSError:
        text = ""
    for m in LINK.finditer(text):
        target = posixpath.normpath(posixpath.join("extras", m.group(2).split("#", 1)[0]))
        if target in pages and target.startswith("extras/") and target not in listed["Extras"]:
            listed["Extras"].append(target)
    placed = {p for names in listed.values() for p in names}
    for p in pages:
        if p not in placed:
            listed["Extras" if p.startswith("extras/") else "Look up"].append(p)
    return [(title, listed[title]) for title, _ in SECTIONS if listed[title]]


class Docs:
    """The docs folder, and how each link and image in it is drawn in the Guide."""

    def __init__(self, docs: Path, ref: str = "main"):
        self.docs, self.ref = docs, ref
        self.pages = doc_pages(docs)
        self.images: Dict[str, Optional[str]] = {}

    def github(self, path: str, fragment: str = "") -> str:
        return "%s/blob/%s/%s%s" % (PROJECT, urllib.parse.quote(self.ref, safe=""), urllib.parse.quote(path, safe="/"),
                                    "#" + urllib.parse.quote(fragment, safe="-_.") if fragment else "")

    def resolve(self, page: str, href: str) -> Optional[str]:
        """Where a link in `page` leads in the Guide: an anchor on the page, a
        file on GitHub, a web address as written, or None for one with no
        safe place to go, which then keeps its text only."""
        href = href.strip()
        if href.startswith(OUTSIDE):
            return href
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href):
            return None                                    # javascript:, file:, obsidian: and the like
        path, _, fragment = href.partition("#")
        if not path:
            return "#" + page_id(page, fragment)
        path = urllib.parse.unquote(path)
        if path.startswith("/"):
            return None
        target = posixpath.normpath(posixpath.join(posixpath.dirname(page), path))
        if target in self.pages:
            return "#" + page_id(target, fragment)
        repo = posixpath.normpath(posixpath.join("docs", target))
        if repo == ".." or repo.startswith("../"):
            return None
        return self.github(repo, fragment)

    def image(self, page: str, src: str) -> Optional[str]:
        """An image beside the docs as a data: URI, or None for one that is not there."""
        if src.startswith(("data:", "http://", "https://", "/")) or ":" in src.split("/", 1)[0]:
            return None                                    # the page loads nothing, and reads nothing outside the docs
        target = posixpath.normpath(posixpath.join(posixpath.dirname(page), urllib.parse.unquote(src.split("#", 1)[0])))
        if target.startswith("../") or target == "..":
            return None
        if target not in self.images:
            kind = IMAGE_TYPES.get(posixpath.splitext(target)[1].lower())
            try:
                data = self.docs.joinpath(*target.split("/")).read_bytes() if kind else None
            except OSError:
                data = None
            self.images[target] = "data:%s;base64,%s" % (kind, base64.b64encode(data).decode("ascii")) if data else None
        return self.images[target]

    def render(self, page: str) -> Tuple[str, str, List[Tuple[int, str, str]]]:
        """(title, html, headings) of one page."""
        seen: Dict[str, int] = {}

        def anchor(level: int, text: str) -> str:
            s = slug(text)
            k = seen.get(s, 0)
            seen[s] = k + 1
            return page_id(page, s if not k else "%s-%d" % (s, k))
        r = Renderer(lambda h: self.resolve(page, h), lambda s: self.image(page, s), anchor=anchor)
        text = self.docs.joinpath(*page.split("/")).read_text(encoding="utf-8")
        body = r.render(text)
        title = next((t for level, _, t in r.headings if level == 1), page_key(page))
        return title, body, r.headings


def guide(docs: Optional[Path], ref: str = "main") -> Tuple[str, str]:
    """The Guide tab: (its body, what goes at the end of the page). The
    contents, a search field and each page are the text of a script element
    at the end, which GUIDE_JS puts into the tab's body when the tab first
    opens. With no docs in the workspace, a line that says how to get them."""
    pages = doc_pages(docs) if docs is not None and docs.is_dir() else []
    if not pages:
        return ('<div class="gd-empty"><h2>Guide</h2><p>This workspace has no copy of Garrick&#x27;s docs yet. Update Garrick, '
                'and they arrive in <code>System/garrick-docs/</code>; the Garrick App then shows them here.</p></div>', "")
    d = Docs(docs, ref)
    rendered = {p: d.render(p) for p in pages}
    toc, articles = [], []
    for title, names in contents(docs, pages):
        items = []
        for p in names:
            name, body, heads = rendered[p]
            subs = "".join('<li data-l="%d"><a href="#%s">%s</a></li>' % (level, E(hid), E(text))
                           for level, hid, text in heads if level in (2, 3))
            items.append('<li class="gd-it" data-p="%s"><a href="#%s">%s</a>%s</li>'
                         % (E(page_id(p)), E(page_id(p)), E(name), '<ul class="gd-hs">%s</ul>' % subs if subs else ""))
            articles.append('<article class="gd-page" id="%s" hidden>%s</article>' % (E(page_id(p)), body))
        toc.append('<div class="gd-sec"><h3>%s</h3><ul>%s</ul></div>' % (E(title), "".join(items)))
    side = ('<div class="gd-side"><input class="gd-q" type="search" placeholder="Search the Guide" autocomplete="off" '
            'aria-label="Search the Guide\'s titles and headings"><div class="gd-toc" role="navigation" aria-label="Guide contents">'
            '%s</div><p class="gd-none muted" hidden>No title or heading in the Guide matches.</p></div>' % "".join(toc))
    held = '%s<div class="gd-main">%s</div>' % (side, "".join(articles))
    # Every character of the docs is escaped, so nothing in them can end the script early; this is the belt to that.
    held = re.sub(r"</(script)", r"&lt;/\1", held, flags=re.I)
    return '<div class="gd" id="guide"></div>', '<script type="text/html" id="guide-src">%s</script>' % held


GUIDE_CSS = r"""
.gd{display:grid;grid-template-columns:230px minmax(0,1fr);gap:32px;align-items:start}
.gd-side{position:sticky;top:76px;max-height:calc(100vh - 96px);overflow:auto;padding:2px 4px 12px 2px}
.gd-q{width:100%;font:inherit;font-size:13px;padding:7px 10px;border-radius:8px;border:1px solid var(--line);background:var(--surface);color:var(--ink);margin-bottom:12px}
.gd-q:focus{outline:2px solid var(--accent);outline-offset:-1px}
.gd-sec h3{margin:14px 0 4px;font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink2)}
.gd-toc ul{list-style:none;margin:0;padding:0}.gd-toc a{display:block;padding:3px 8px;border-radius:6px;font-size:13px;color:var(--ink2)}
.gd-toc a:hover{background:var(--wash);color:var(--ink);text-decoration:none}.gd-it.on>a{background:var(--wash);color:var(--ink);font-weight:560}
.gd-hs{display:none;margin:2px 0 6px 10px!important;border-left:1px solid var(--line)}.gd-hs a{font-size:12px;padding:2px 8px}
.gd-it.on>.gd-hs,.gd-toc.q .gd-hs{display:block}.gd-toc:not(.q) .gd-hs>li[data-l="3"]{display:none}.gd-hs>li[data-l="3"] a{padding-left:18px}
.gd-main{min-width:0}
.gd-page{max-width:820px;background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);padding:6px 34px 30px;line-height:1.6;font-size:14.5px}
.gd-page :is(h1,h2,h3,h4,h5,h6){line-height:1.25}
.gd-page h1{font:600 30px/1.2 var(--display);margin:22px 0 14px}.gd-page h2{font:600 21px/1.25 var(--display);margin:30px 0 10px;padding-top:14px;border-top:1px solid var(--grid)}
.gd-page h3{font-size:16px;margin:24px 0 8px}.gd-page h4{font-size:14.5px;margin:20px 0 6px}
.gd-page a{color:var(--accent)}.gd-page a:hover{text-decoration:underline}
.gd-page code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--raise);border:1px solid var(--line);border-radius:4px;padding:0 4px}
.gd-page pre{background:var(--raise);border:1px solid var(--line);border-radius:10px;padding:12px 14px;overflow:auto}
.gd-page pre code{border:0;padding:0;background:none;white-space:pre}
.gd-page img{max-width:100%;height:auto;border-radius:8px;border:1px solid var(--line)}
.gd-page blockquote{margin:12px 0;padding:2px 16px;border-left:3px solid var(--accent);color:var(--ink2);background:var(--wash);border-radius:0 8px 8px 0}
.gd-page ul,.gd-page ol{padding-left:22px}.gd-page li{margin:3px 0}
.gd-table{overflow-x:auto;margin:12px 0}.gd-table table{border-collapse:collapse;font-size:13px;line-height:1.45}
.gd-table th,.gd-table td{border:1px solid var(--grid);padding:6px 10px;vertical-align:top;text-align:left}.gd-table th{background:var(--raise)}
.gd-empty{max-width:620px}.gd-empty h2{font:600 21px/1.25 var(--display)}
@media (max-width:820px){.gd{grid-template-columns:1fr;gap:16px}.gd-side{position:static;max-height:none}.gd-page{padding:4px 18px 22px}}
"""

# The Guide's script. Its pages sit as text at the end of the page until the
# tab first opens, or a link leads into it: JS's anchor handler asks
# GarrickGuide.reveal() for an id it cannot find, and StatusTab mounts the
# Guide when it opens the tab. This runs before that text is read, so a window
# that reopens on the Guide, or a link into it, waits for DOMContentLoaded.
# One page shows at a time, and the last one read is remembered in this window.
GUIDE_JS = r"""
(function(){var box=document.getElementById('guide'),KEY='garrick-guide-page',ready=false,pages=[],items=[];
function get(){try{return localStorage.getItem(KEY)}catch(e){return null}}
function put(v){try{localStorage.setItem(KEY,v)}catch(e){}}
function show(id){var hit=null;pages.forEach(function(p){if(p.id===id)hit=p});if(!hit)hit=pages[0];
pages.forEach(function(p){p.hidden=p!==hit});items.forEach(function(li){li.classList.toggle('on',!!hit&&li.dataset.p===hit.id)});if(hit)put(hit.id);return hit}
function words(s){return s.toLowerCase().split(/\s+/).filter(Boolean)}
function has(t,w){t=t.toLowerCase();return w.every(function(x){return t.indexOf(x)>=0})}
function find(s){var w=words(s),toc=box.querySelector('.gd-toc'),any=false;toc.classList.toggle('q',w.length>0);
items.forEach(function(li){var n=0,t=!w.length||has(li.firstElementChild.textContent,w);
li.querySelectorAll('.gd-hs>li').forEach(function(h){var m=w.length>0&&has(h.textContent,w);h.hidden=w.length>0&&!m;if(m)n++});
li.hidden=!(t||n);if(!li.hidden)any=true});
box.querySelectorAll('.gd-sec').forEach(function(s){s.hidden=!s.querySelector('.gd-it:not([hidden])')});
box.querySelector('.gd-none').hidden=any}
function mount(){var src=document.getElementById('guide-src');if(ready||!box||!src)return;ready=true;box.insertAdjacentHTML('beforeend',src.textContent);src.remove();
pages=[].slice.call(box.querySelectorAll('.gd-page'));items=[].slice.call(box.querySelectorAll('.gd-it'));
var q=box.querySelector('.gd-q');if(q){q.addEventListener('input',function(){find(q.value)});
q.addEventListener('keydown',function(e){if(e.key==='Escape'&&q.value){q.value='';find('');e.stopPropagation()}})}show(get())}
function reveal(id){if(!id||id.indexOf('guide-')!==0)return null;mount();var el=document.getElementById(id);if(!el)return null;
var p=el.closest('.gd-page');if(p)show(p.id);return el}
window.GarrickGuide={mount:mount,reveal:reveal};
function opened(){if(document.body.dataset.tab==='guide')mount();
if(location.hash.indexOf('#guide-')===0){var el=reveal(location.hash.slice(1));if(el&&window.StatusTab){StatusTab('guide');el.scrollIntoView({block:'start'})}}}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',opened);else opened();
})();
"""

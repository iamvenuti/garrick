"""One normaliser and one resolver for the tokens that name a Meetings page.

    cd tests && python3 -m unittest test_wall_forms

The wall check once learned one form at a time: a slash path, a `./` path, a
bare name. This module builds the forms instead of listing them. A token is a
product of page kind x grade x path depth x prefix x suffix x wrapper, and
every row is refused across a wall and passes on the near side. A form a review
finds later is a new value of one factor, not a new test.

Northwind is a project for Acme, Harbour one for Birch & Co, with a wall
between the two parties; neither folder is named like its party. Every
workspace is built in a temporary folder with invented names only.
"""

from __future__ import annotations

import itertools
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

sys.dont_write_bytecode = True

from fixtures import GIT_ENV, HAVE_GIT, build_workspace, commit_all, git, meeting_page, project_hub, thread_note, write  # noqa: E402

import check  # noqa: E402

KINDS = ("source", "person", "entity", "decision", "question", "answer", "raw")
GRADES = ("", "dormant", "archive")           # live, then the two that faded
PREFIXES = ("", "./", "././", "/", "//")
SUFFIXES = ("", "/", ":3", "#heading", ".md", ".md/")
WRAPPERS = ("code", "quoted", "cat", "link", "wikilink")

# Two pages of each kind and grade, one for each side of the wall. A name is
# not shared between two pages, so a bare name leads to one page.
FAR, NEAR = "birch", "acme"
SLUGS = {FAR: ("harvest", "orchard", "meadow"), NEAR: ("quarry", "forge", "lantern")}
PEOPLE = {FAR: ("kai-ross", "lee-ross", "max-ross"), NEAR: ("jo-lane", "ana-lane", "tom-lane")}
ENTITIES = {FAR: ("harvest-co", "orchard-co", "meadow-co"), NEAR: ("quarry-ltd", "forge-ltd", "lantern-ltd")}

GENERIC = ("notes", "todo", "plan", "index")
NOISE_WORDS = ("email", "readme", "config", "slack", "docker", "setup", "status")

DECISION_BODY = ("\n# Pick a supplier\n\n## Decision\n\nGo.\n\n## Assumptions\n\nNone.\n\n"
                 "## Options turned down\n\nNone.\n\n## Revisit when\n\nNever.\n")


def meetings_home(root: Path, grade: str) -> Path:
    home = root / "Wikis" / "Meetings"
    return home / grade if grade else home


def page_files(root: Path, kind: str, grade: str, party: str, n: int):
    """(path, text) of each file one page of `kind` needs, the page first."""
    home = meetings_home(root, grade)
    slug = SLUGS[party][n]
    day = "26031%d" % (5 + n)
    if kind == "source":
        return [(home / "wiki" / "sources" / ("%s-%s.md" % (day, slug)),
                 meeting_page("Work", "[%s]" % party, slug.title()).replace(
                     "people:", "transcript: \"[[raw/%s-%s-call]]\"\npeople:" % (day, slug)))]
    if kind == "raw":
        return [(home / "raw" / ("%s-%s-call.txt" % (day, slug)), "Someone: we start Monday.\n")]
    if kind == "person":
        name = PEOPLE[party][n]
        return [(home / "wiki" / "people" / (name + ".md"),
                 "---\ntitle: %s\ntype: person\nparty: %s\n---\n\n# %s\n" % (name.replace("-", " ").title(), party, name))]
    if kind == "entity":
        name = ENTITIES[party][n]
        return [(home / "wiki" / "entities" / (name + ".md"),
                 "---\ntitle: %s\ntype: entity\nparty: %s\n---\n\n# %s\n" % (name, party, name))]
    if kind == "decision":
        text = ("---\ntitle: Pick a supplier\ntype: decision\nstatus: valid\nzone: Work\nparties: [%s]\n---\n" % party
                + DECISION_BODY)
        return [(home / "wiki" / "decisions" / ("%s - pick-%s.md" % (day, slug)), text)]
    if kind == "question":
        if grade:
            return []
        text = "---\ntitle: Which region\ntype: question\nzone: Work\nparties: [%s]\n---\n\n# Which region\n" % party
        return [(home / "questions" / ("%s - region-%s.md" % (day, slug)), text)]
    if kind == "answer":
        text = "---\ntitle: Which region\ntype: answer\nzone: Work\nparties: [%s]\n---\n\nThe north.\n" % party
        return [(home / "raw" / "answers" / ("%s - region-%s.md" % (day, slug)), text)]
    raise ValueError(kind)


# Pages a review found that the index or the party reading missed: another suffix, another way to write a party, a name
# holding `#` or `%`. Each is (folder, far name, near name, suffix, party line); a `{p}` in the line is the party's tag
# and a `{n}` its name in the Parties table. A far page whose party cannot be read is every party's.
VARIANTS = {
    "source-MD": ("sources", "260416-lake", "260416-cove", ".MD", "parties: [{p}]"),
    "source-markdown": ("sources", "260417-moor", "260417-fen", ".markdown", "parties: [{p}]"),
    "person-MD": ("people", "pat-quill", "ben-quill", ".MD", "party: {p}"),
    "person-markdown": ("people", "fay-cole", "gus-cole", ".markdown", "party: {p}"),
    "entity-MD": ("entities", "dune-ltd", "peak-ltd", ".MD", "party: {p}"),
    "decision-MD": ("decisions", "260418 - pick-fen", "260418 - pick-bog", ".MD", "parties: [{p}]"),
    "person-display": ("people", "rae-moss", "sid-moss", ".md", "party: {n}"),
    "person-quoted": ("people", "zed-pike", "cal-pike", ".md", 'party: "[{p}]"'),
    "person-hash": ("people", "dot#hash", "kit#hash", ".md", "party: {p}"),
    "person-pct": ("people", "pc%20t", "qc%20t", ".md", "party: {p}"),
    "person-unreadable": ("people", "ola-vance", None, ".md", "party: Birch Holdings"),
    # Names that keep punctuation, a sigil or a brace, one plain word, and several words.
    "entity-sigma": ("entities", "Sigma Corp.", "Tau Inc.", ".md", "party: {p}"),
    "entity-gamma": ("entities", "Gamma (EU)", "Omega (US)", ".md", "party: {p}"),
    "entity-delta": ("entities", "Delta+", "Epsilon+", ".md", "party: {p}"),
    "entity-eu": ("entities", "(EU) Gamma", "(US) Omega", ".md", "party: {p}"),
    "entity-dollar": ("entities", "$board-co", "$guild-co", ".md", "party: {p}"),
    "person-at": ("people", "@kay-lin", "@ned-lin", ".md", "party: {p}"),
    "person-paren": ("people", "Wes Park (Jr)", "Tom Park (Sr)", ".md", "party: {p}"),
    "entity-plain": ("entities", "quartz", "basalt", ".md", "party: {p}"),
    "entity-brace": ("entities", "fund-{b}", "seed-{c}", ".md", "party: {p}"),
    "entity-spaced": ("entities", "Pine Ridge", "Oak Hollow", ".md", "party: {p}"),
}
TYPES = {"sources": "source", "people": "person", "entities": "entity", "decisions": "decision"}
PARTY_NAMES = {FAR: "Birch & Co", NEAR: "Acme Corp"}


def variant_file(root: Path, kind: str, party: str):
    folder, far, near, suffix, line = VARIANTS[kind]
    name = far if party == FAR else near
    if name is None:
        return None
    line = line.format(p=party, n=PARTY_NAMES[party])
    extra = "zone: Work\n" if folder in ("sources", "decisions") else ""
    body = DECISION_BODY if folder == "decisions" else "\n# x\n"
    return (meetings_home(root, "") / "wiki" / folder / (name + suffix),
            "---\ntitle: %s\ntype: %s\n%s%s\n---\n%s" % (name, TYPES[folder], extra, line, body))


def build(root: Path):
    """The workspace: the base fixture, Northwind (Acme), Harbour (Birch & Co)
    and every page of every kind and grade for each party. Returns
    {(kind, grade, party): page path}."""
    build_workspace(root)
    work = root / "Zones" / "Work"
    for name, party, thread in (("Northwind", NEAR, "Freight"), ("Harbour", FAR, "Tender")):
        write(work / name / (name + ".md"), project_hub("Work", name, party, [thread]))
        write(work / name / "Threads" / thread / (thread + ".md"), thread_note(name, thread, party))
    # Far pages with a generic name, and the near project's own files of those names.
    for name in GENERIC:
        write(meetings_home(root, "") / "wiki" / "entities" / (name + ".md"),
              "---\ntitle: %s\ntype: entity\nparty: %s\n---\n\n# %s\n" % (name.title(), FAR, name))
        for folder in (work / "Northwind", work / "Northwind" / "Threads" / "Freight"):
            write(folder / (name.title() + ".md"), "# %s\n" % name.title())
    for name in NOISE_WORDS:
        write(meetings_home(root, "") / "wiki" / "entities" / (name + ".md"),
              "---\ntitle: %s\ntype: entity\nparty: %s\n---\n\n# %s\n" % (name.title(), FAR, name))
    pages = {}
    for kind, grade, party in itertools.product(KINDS, GRADES, (FAR, NEAR)):
        files = page_files(root, kind, grade, party, GRADES.index(grade))
        for path, text in files:
            write(path, text)
        if files:
            pages[(kind, grade, party)] = files[0][0]
    for kind, party in itertools.product(VARIANTS, (FAR, NEAR)):
        made = variant_file(root, kind, party)
        if made:
            write(*made)
            pages[(kind, "", party)] = made[0]
    return pages


def depths(root: Path, page: Path):
    """Every tail of the page's path from the wiki's name down to its own name,
    without the extension, then the whole path from the disk's top."""
    parts = list(page.relative_to(root).parts)
    parts[-1] = page.stem
    tails = ["/".join(parts[-i:]) for i in range(1, len(parts) + 1)]
    return tails + [str(root / "/".join(parts))]


def two(root: Path, page: Path):
    """Two depths: the name alone and the path from the wiki's name."""
    every = depths(root, page)
    return [every[0], every[-2]]


def few(root: Path, page: Path):
    """Four depths: the name, its folder and name, the path from the wiki's
    name, and the path from the disk's top."""
    every = depths(root, page)
    return list(dict.fromkeys([every[0], every[1], every[-2], every[-1]]))


NOTE = "# Notes\n\nSee %s now.\n"
# A wrapper puts a token in a note. The first five are the original ones.
WRAPPING = {
    "code": lambda t: NOTE % ("`%s`" % t),
    "quoted": lambda t: NOTE % ("`\"%s\"`" % t),
    "cat": lambda t: NOTE % ("`cat %s`" % t),
    "link": lambda t: NOTE % ("[the page](<%s>)" % t if " " in t else "[the page](%s)" % t),
    "wikilink": lambda t: NOTE % ("[[%s]]" % t),
    "find": lambda t: NOTE % ("`find Wikis -name '%s'`" % t),
    "autolink-file": lambda t: NOTE % ("<file:///x/%s>" % t.lstrip("/")),
    "autolink-file1": lambda t: NOTE % ("<file:/%s>" % t.lstrip("/")),
    "autolink-https": lambda t: NOTE % ("<https://x/%s>" % t.lstrip("/")),
    "frontmatter": lambda t: "---\nrelated: %s\n---\n\nx\n" % t,
    "frontmatter-list": lambda t: "---\nrelated:\n  - %s\n---\n\nx\n" % t,
    "indented": lambda t: "# Notes\n\npara\n\n    %s\n" % t,
    "indented-cat": lambda t: "# Notes\n\npara\n\n\tcat %s\n" % t,
    "indented-refdef": lambda t: "# Notes\n\npara\n\n    [1]: %s\n" % t,
    "html-code": lambda t: NOTE % ("<code>%s</code>" % t),
    "html-pre": lambda t: "# Notes\n\n<pre>\n%s\n</pre>\n" % t,
    "html-comment": lambda t: "# Notes\n\n<!-- %s -->\n" % t,
    "long-span": lambda t: NOTE % ("`%s cat %s`" % ("x " * 600, t)),
    "long-token": lambda t: NOTE % ("`%s%s`" % ("./" * 600, t.lstrip("/"))),
    "prose": lambda t: NOTE % t,
}

def _pct(t, c):
    return t.replace("/", c)


def _entity(t, form):
    """The token with its slashes, and a letter of its name, written as HTML entities."""
    return t.replace("/", form)


def _letter(t):
    head, _, name = t.rpartition("/")
    k = next((i for i, c in enumerate(name) if c.isalpha()), None)
    return t if k is None else (head + "/" if head else "") + name[:k] + "&#%d;" % ord(name[k]) + name[k + 1:]


def _mid(t, ins):
    k = t.rfind("-")
    return t + ins if k < 0 else t[:k] + ins + t[k:]


def _bold(t):
    head, sep, rest = t.partition("/")
    return "<b>%s</b>%s%s" % (head, sep, rest) if sep else "<b>%s</b>" % t


WRAP_PAIRS = {"curly": "\u201c\u201d", "guillemet": "\u00ab\u00bb", "cjk": "\u300c\u300d", "single": "\u2039\u203a",
              "angle": "\u27e8\u27e9", "lenticular": "\u3010\u3011", "paren": "()", "square": "[]"}
WRAPPING.update({
    "prose-sol": lambda t: NOTE % _entity(t, "&sol;"), "prose-num": lambda t: NOTE % _entity(t, "&#47;"),
    "prose-hex": lambda t: NOTE % _entity(t, "&#x2f;"), "link-num": lambda t: NOTE % ("[x](<%s>)" % _entity(t, "&#47;")),
    "prose-wbr": lambda t: NOTE % t.replace("/", "/<wbr>"), "prose-bold": lambda t: NOTE % _bold(t),
    "prose-shy": lambda t: NOTE % _mid(t, "&shy;"), "prose-hyphen": lambda t: NOTE % t.replace("-", "&#45;"),
    "prose-zws": lambda t: NOTE % _mid(t, "&#8203;"), "prose-zwse": lambda t: NOTE % _mid(t, "&ZeroWidthSpace;"),
    "link-letter": lambda t: NOTE % ("[x](<%s>)" % _letter(t)),
    "prose-pct5c": lambda t: NOTE % _pct(t, "%5C"), "prose-pct2f": lambda t: NOTE % _pct(t, "%2F"),
    "code-pct5c": lambda t: NOTE % ("`%s`" % _pct(t, "%5C")), "prose-backslash": lambda t: NOTE % _pct(t, "\\"),
    "prose-nbsp": lambda t: NOTE % t.replace(" ", "\u00a0"),
    "fm-nested": lambda t: "---\nmeeting:\n  id: %s\n---\n\nx\n" % t,
    "fm-block": lambda t: "---\nrelated: |\n  %s\n---\n\nx\n" % t,
    "fm-folded": lambda t: "---\nrelated: >-\n  %s\n---\n\nx\n" % t,
    "fm-comma": lambda t: "---\nrelated: planning, %s\n---\n\nx\n" % t,
    "fm-quoted-key": lambda t: '---\n"related": %s\n---\n\nx\n' % t,
    "fm-key-space": lambda t: "---\nsee also: %s\n---\n\nx\n" % t,
    "fm-explicit": lambda t: "---\n? related\n: %s\n---\n\nx\n" % t,
    "fm-json": lambda t: '{"related": "%s"}\n\n# Notes\n' % t,
    "fm-fence-space": lambda t: "--- \nrelated: %s\n---\n\nx\n" % t,
    "fm-second-doc": lambda t: "---\nrelated: ok\n---\n---\nother: %s\n---\n\nx\n" % t,
    "fm-flow": lambda t: "---\nmeeting: {id: %s}\n---\n\nx\n" % t,
    "fm-list-map": lambda t: "---\nitems:\n  - id: %s\n---\n\nx\n" % t,
    "fm-title": lambda t: "---\ntitle: %s\n---\n\nx\n" % t,
    "fm-tags": lambda t: "---\ntags: [%s]\n---\n\nx\n" % t,
    "fm-paren": lambda t: "---\nrelated: %s (call)\n---\n\nx\n" % t,
    "obs-file": lambda t: NOTE % ("[x](obsidian://open?vault=v&file=%s)" % quote(t, safe="/")),
    "obs-path": lambda t: NOTE % ("[x](obsidian://open?vault=v&path=%s)" % quote(t, safe="/")),
    "obs-filepath": lambda t: NOTE % ("[x](obsidian://adv-uri?vault=v&filepath=%s)" % quote(t, safe="/")),
    "obs-filename": lambda t: NOTE % ("[x](obsidian://adv-uri?vault=v&filename=%s)" % quote(t, safe="/")),
    "obs-fragment": lambda t: NOTE % ("[x](obsidian://open?vault=v#file=%s)" % quote(t, safe="/")),
    "obs-prose": lambda t: NOTE % ("obsidian://adv-uri?vault=v&filepath=%s" % quote(t, safe="/")),
})
for _name, _pair in WRAP_PAIRS.items():
    WRAPPING["code-" + _name] = (lambda pair: lambda t: NOTE % ("`%s%s%s`" % (pair[0], t, pair[1])))(_pair)
    WRAPPING["prose-" + _name] = (lambda pair: lambda t: NOTE % ("%s%s%s" % (pair[0], t, pair[1])))(_pair)
    WRAPPING["link-" + _name] = (lambda pair: lambda t: NOTE % ("[x](%s%s%s)" % (pair[0], t, pair[1])) if " " not in t
                                 else NOTE % ("[x](<%s%s%s>)" % (pair[0], t, pair[1])))(_pair)
LONG = "a" * 5000


def _inner_dots(t):
    """The token with a detour in front of its name: `x/y/../../name`."""
    head, _, name = t.rpartition("/")
    return (head + "/" if head else "") + "x/y/../../" + name


def _long_dots(t):
    """The token with a long detour in front of its name, over 4,096 characters."""
    head, _, name = t.rpartition("/")
    return (head + "/" if head else "") + "a/" * 1100 + "../" * 1100 + name


def _first_dash(t, ins):
    k = t.rfind("-")
    return t if k < 0 else t[:k] + ins + t[k + 1:]


def _first_letter_u(t):
    head, _, name = t.rpartition("/")
    k = next((i for i, c in enumerate(name) if c.isalpha()), None)
    return t if k is None else (head + "/" if head else "") + name[:k] + "\\u%04x" % ord(name[k]) + name[k + 1:]


WRAPPING.update({
    "code-long-tail": lambda t: NOTE % ("`%s#%s`" % (t, LONG)),
    "fence-long-tail": lambda t: "# Notes\n\n```\ncat %s?%s\n```\n" % (t, LONG),
    "prose-long-tail": lambda t: NOTE % ("%s#%s" % (t, LONG)),
    "fm-long-tail": lambda t: "---\nrelated: %s#%s\n---\n\nx\n" % (t, LONG),
    "link-long-fragment": lambda t: NOTE % ("[x](<%s#%s>)" % (t, LONG)),
    "link-long-head": lambda t: NOTE % ("[x](<%s/%s>)" % (LONG, t.lstrip("/"))),
    "code-many-dotdot": lambda t: NOTE % ("`%s%s`" % ("../" * 3000, t.lstrip("/"))),
    "fm-dq-hex": lambda t: '---\nrelated: "[[%s]]"\n---\n\nx\n' % _first_dash(t, "\\x2d"),
    "fm-dq-unicode": lambda t: '---\nrelated: "[[%s]]"\n---\n\nx\n' % _first_letter_u(t),
    "fm-dq-fold": lambda t: '---\nrelated: "[[%s]]"\n---\n\nx\n' % _first_dash(t, "-\n  "),
    "fm-sq": lambda t: "---\nrelated: '[[%s]]'\n---\n\nx\n" % t,
    "prose-underscore": lambda t: NOTE % ("_" + t + "_"), "prose-strike": lambda t: NOTE % ("~~" + t + "~~"),
    "prose-mark": lambda t: NOTE % ("==" + t + "=="), "prose-html-comment": lambda t: NOTE % ("<!-- x -->" + t),
    "prose-obs-comment": lambda t: NOTE % ("%% x %%" + t), "prose-bold-star": lambda t: NOTE % ("**" + t + "**"),
    "prose-segment-italic": lambda t: NOTE % (t.rpartition("/")[0] + "/_" + t.rpartition("/")[2] + "_"),
    "fm-key": lambda t: "---\n%s: yes\n---\n\nx\n" % t,
    "code-middle": lambda t: NOTE % ("`x y z w v %s`" % t),
    "code-dotdot": lambda t: NOTE % ("`%s`" % _inner_dots(t)), "link-dotdot": lambda t: NOTE % ("[x](<%s>)" % _inner_dots(t)),
    "prose-dotdot": lambda t: NOTE % _inner_dots(t),
    "code-long-dotdot": lambda t: NOTE % ("`%s`" % _long_dots(t)),
})
NEW_FORMS = ("code-long-tail", "fence-long-tail", "prose-long-tail", "fm-long-tail", "link-long-fragment", "link-long-head",
             "code-many-dotdot", "fm-dq-hex", "fm-dq-unicode", "fm-dq-fold", "fm-sq", "prose-underscore", "prose-strike",
             "prose-mark", "prose-html-comment", "prose-obs-comment", "prose-bold-star", "prose-segment-italic", "fm-key",
             "code-dotdot", "link-dotdot", "prose-dotdot", "code-long-dotdot")
WRAPPERS = ("code", "quoted", "cat", "link", "wikilink")
# What a wrapper can hold: these read a path of two names or more (a URL has a
# host, prose reads no bare name), the rest any token.
PATH_ONLY = ("autolink-file", "autolink-file1", "autolink-https", "prose", "prose-sol", "prose-num", "prose-hex",
             "prose-wbr", "prose-bold", "prose-shy", "prose-hyphen", "prose-zws", "prose-zwse", "prose-pct5c",
             "prose-pct2f", "prose-backslash", "prose-nbsp") + tuple("prose-" + n for n in WRAP_PAIRS)
# These hold no space or no plain word; a URL needs a wiki, raw or Wikis segment to name a page.
NO_SPACE = PATH_ONLY[:3] + ("prose-sol", "prose-num", "prose-hex", "prose-wbr", "prose-bold", "prose-shy", "prose-hyphen",
                            "prose-zws", "prose-zwse", "prose-pct5c", "prose-pct2f", "prose-backslash")

# The factors a review added. Each block is a product of its own values against
# every page and depth; a form found later is a new value in one of them.
NEW_PREFIXES = ("@", "path:", "!", "$", "*", "#", "~")
NEW_SUFFIXES = (":3-5", "@3", ":L3", "::Heading", "~", ".md:3-5", ".md::Heading", ".md~", "^abc", ".md^abc")
NEW_WRAPPERS = ("autolink-file", "autolink-file1", "autolink-https", "frontmatter", "frontmatter-list", "indented",
                "indented-cat", "indented-refdef", "html-code", "html-pre", "html-comment", "long-span", "long-token",
                "prose")
NAME_FORMS = {
    "escaped": lambda n: n.replace("-", "\\-"), "underscore": lambda n: n.replace("-", "_"),
    "spaced": lambda n: n.replace("-", " "), "star": lambda n: n[:-2] + "*", "question": lambda n: n[:3] + "?" + n[4:],
    "zero-width": lambda n: n[:3] + "\u200b" + n[3:], "soft-hyphen": lambda n: n[:3] + "\u00ad" + n[3:],
    "bidi": lambda n: "\u202e" + n + "\u200f", "joiner": lambda n: n[:2] + "\u200d\u2060" + n[2:],
    "variation": lambda n: n + "\ufe0f", "hangul-filler": lambda n: n[:3] + "\u3164" + n[3:],
    "braille": lambda n: n[:3] + "\u2800" + n[3:], "cgj": lambda n: n[:3] + "\u034f" + n[3:],
    "bell": lambda n: n[:3] + "\x07" + n[3:], "tag-char": lambda n: n[:3] + "\U000e0100" + n[3:],
    "class": lambda n: "[%s]%s" % (n[0], n[1:]), "brace": lambda n: "{%s,zz}" % n,
    "brace7": lambda n: "".join("{%s,\u0071}" % c if i < 7 else c for i, c in enumerate(n)),
}


def with_name(depth: str, form: str) -> str:
    head, _, name = depth.rpartition("/")
    return (head + "/" if head else "") + NAME_FORMS[form](name)


MARKS = ("?", "!", "%", "$", "+", "\u00ba", "'s", "\u2019s", ")", ".", ",")
WORD_PREFIXES = ("HEAD:", "host:")
FM_WRAPPERS = ("fm-nested", "fm-block", "fm-folded", "fm-comma", "fm-quoted-key", "fm-key-space", "fm-explicit",
               "fm-json", "fm-fence-space", "fm-second-doc", "fm-flow", "fm-list-map", "fm-title", "fm-tags", "fm-paren")
OBS_WRAPPERS = ("obs-file", "obs-path", "obs-filepath", "obs-filename", "obs-fragment", "obs-prose")
RENDER_WRAPPERS = ("prose-sol", "prose-num", "prose-hex", "link-num", "prose-wbr", "prose-bold", "prose-shy", "prose-hyphen",
                   "prose-zws", "prose-zwse", "link-letter", "prose-pct5c", "prose-pct2f", "code-pct5c", "prose-backslash")
WRAPCHAR_WRAPPERS = tuple("%s-%s" % (w, n) for n in WRAP_PAIRS for w in ("code", "prose", "link"))
SPACE_OK = ("prose", "prose-nbsp")
PATH_ONLY += ("prose-dotdot", "prose-segment-italic", "prose-long-tail", "prose-underscore", "prose-strike", "prose-mark", "prose-html-comment", "prose-obs-comment",
              "prose-bold-star")
NO_SPACE += ("prose-dotdot", "prose-segment-italic", "prose-long-tail", "prose-underscore", "prose-strike", "prose-mark", "prose-html-comment", "prose-obs-comment",
             "prose-bold-star")


def usable(wrapper: str, depth: str) -> bool:
    """Can `wrapper` hold a token of this depth? A URL and a word of prose hold
    no space (a path into a wiki read over several words excepted), a URL needs
    a `wiki`, `raw` or `Wikis` segment to name a page, and prose reads a path
    of two names or more."""
    if (wrapper in PATH_ONLY or wrapper == "link-long-head") and "/" not in depth:
        return False
    if " " in depth and wrapper in PATH_ONLY and wrapper not in SPACE_OK:
        return False
    if " " in depth and wrapper in NO_SPACE:
        return False
    if wrapper == "autolink-https" and not {x.lower() for x in depth.split("/")} & {"wiki", "raw", "wikis"}:
        return False
    if wrapper in SPACE_OK and " " in depth and not any(
            x.lower() in ("wikis", "wiki", "raw", "meetings", "dormant", "archive", "decisions", "questions", "answers",
                          "sources", "people", "entities") for x in depth.split("/")[:-1]):
        return False
    if wrapper.startswith("obs-") and wrapper != "obs-filename" and False:
        return False
    return True


def blocks(root: Path, page: Path, variant: bool = False):
    """(wrapper, token) for every row that names `page`: the blocks of the
    table, each a product of its own factors against the depths. A page of a
    variant (another suffix, another way to write its party) runs one block."""
    if variant:
        for depth in dict.fromkeys(few(root, page)):
            sufs = ("", "/", ".md", ":3")
            if variant == "entity-plain" and "/" not in depth:
                sufs = (".md", ".markdown", ".md:3")      # one plain word names a page only with its extension
            for prefix, suffix, wrapper in itertools.product(("", "./"), sufs, WRAPPERS):
                yield wrapper, prefix + depth + suffix
            if " " in depth:
                yield "code-middle", depth
        return
    for depth in dict.fromkeys(depths(root, page)):
        for prefix, suffix, wrapper in itertools.product(PREFIXES, SUFFIXES, WRAPPERS):
            yield wrapper, prefix + depth + suffix
    for depth in few(root, page):
        for prefix, suffix, wrapper in itertools.product(NEW_PREFIXES + WORD_PREFIXES, ("", "/", ".md"), ("code", "cat", "link", "wikilink")):
            if prefix == "#" and wrapper in ("link", "wikilink"):
                continue                       # a link that starts with `#` points into the note itself
            yield wrapper, prefix + depth + suffix
        for prefix, suffix, wrapper in itertools.product(("", "./"), NEW_SUFFIXES, WRAPPERS):
            yield wrapper, prefix + depth + suffix
        for prefix, suffix, wrapper in itertools.product(("", "./"), ("", "/", ":3", ".md"), NEW_WRAPPERS):
            if usable(wrapper, depth):
                yield wrapper, prefix + depth + suffix
        if depth in two(root, page):
            for form, suffix, wrapper in itertools.product(NAME_FORMS, ("", ".md", "/"), ("code", "cat", "link", "wikilink", "find")):
                if form == "brace7" and " " in depth.rpartition("/")[2]:
                    continue                   # a brace list round a single space: folded apart from its neighbours
                yield wrapper, with_name(depth, form) + suffix
        for mark, wrapper in itertools.product(MARKS, ("code", "cat", "prose")):
            if usable(wrapper, depth):
                yield wrapper, depth + mark
        for suffix, wrapper in itertools.product(("\u2014the page", ":yes", "\u2013x"), ("prose",)):
            if usable(wrapper, depth):
                yield wrapper, depth + suffix
        for suffix, wrapper in itertools.product(("", ".md"), RENDER_WRAPPERS + WRAPCHAR_WRAPPERS + ("prose-nbsp",)):
            if usable(wrapper, depth):
                yield wrapper, depth + suffix
        for suffix, wrapper in itertools.product(("", ".md"), FM_WRAPPERS):
            yield wrapper, depth + suffix
        for wrapper in OBS_WRAPPERS:
            yield wrapper, depth
        for suffix, wrapper in itertools.product(("", ".md"), NEW_FORMS):
            if usable(wrapper, depth):
                yield wrapper, depth + suffix


def rows(root: Path, pages: dict, party: str):
    """(label, text) for every row that names a page of `party`."""
    out = []
    for (kind, grade, owner), page in sorted(pages.items()):
        if owner != party:
            continue
        for wrapper, token in dict.fromkeys(blocks(root, page, kind if kind in VARIANTS else "")):
            out.append(("%s/%s/%s: %s" % (kind, grade or "live", wrapper, token), WRAPPING[wrapper](token)))
    return out


class Table:
    """The rows run against one check module, in one process: the page index
    is built once, as a run of the check builds it."""

    def __init__(self, tools=check, root: Path = None):
        self.check = tools
        self.root = root
        self.pages = build(root)
        self.ws = tools.discover(root)
        self.ws.quick = True            # the wording comparison is not the subject here
        self.notes = {}
        for name, party, thread in (("Northwind", NEAR, "Freight"), ("Harbour", FAR, "Tender")):
            project = root / "Zones" / "Work" / name
            self.notes[name] = (project, {party}, project / "Threads" / thread / "Notes.md")

    def verdict(self, project_name: str, text: str) -> str:
        project, ptags, note = self.notes[project_name]
        found = self.check.walls_for_file(self.ws, project, ptags, note, text)
        walls = [f for f in found if f.check == "walls"]
        if any(f.severity == "error" for f in walls):
            return "refused"
        return "warned" if walls else "passed"

    def run(self, full: bool = False):
        """{(project, party, label): verdict} for the four readings: each project
        naming the pages of each party. Every row across the wall runs from
        Northwind; the rows on its own side run one in eight, and Harbour reads
        the table the other way round one row in twenty-five. With `full`, all."""
        out = {}
        for project_name, own in (("Northwind", NEAR), ("Harbour", FAR)):
            for party in (FAR, NEAR):
                every = 1 if full else (25 if project_name == "Harbour" else 1 if party != own else 8)
                for i, (label, text) in enumerate(rows(self.root, self.pages, party)):
                    if label.startswith("person-unreadable") and project_name == "Harbour":
                        continue                       # a page whose party cannot be read is walled from every project
                    if i % every == 0:
                        out[(project_name, party, label)] = self.verdict(project_name, text)
        return out


class WallFormsTest(unittest.TestCase):
    """The table, read from Northwind (Acme): the pages of Birch & Co are across
    the wall and every row naming one is refused; the pages of Acme are on the
    near side and every row naming one passes with no finding at all. Harbour
    (Birch & Co) reads the same table the other way round, one row in eleven."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name).resolve() / "Workspace"
        cls.table = Table(root=cls.root)
        cls.verdicts = cls.table.run()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def read(self, project, party):
        return {k[2]: v for k, v in self.verdicts.items() if k[0] == project and k[1] == party}

    def test_the_table_is_as_wide_as_its_factors(self):
        far, near = rows(self.root, self.table.pages, FAR), rows(self.root, self.table.pages, NEAR)
        self.assertEqual(len(far), len(near) + 160)       # the page whose party cannot be read has no near-side twin
        self.assertGreater(len(far), 55000)
        self.assertEqual(len(far), len({label for label, _ in far}))
        self.assertLessEqual(len(self.read("Northwind", NEAR)), len(self.read("Northwind", FAR)))

    def test_every_row_across_the_wall_is_refused(self):
        for project, party in (("Northwind", FAR), ("Harbour", NEAR)):
            wrong = sorted(k for k, v in self.read(project, party).items() if v != "refused")
            self.assertEqual([], wrong[:15], "%s: %d rows pass" % (project, len(wrong)))

    def test_every_row_on_the_near_side_passes_with_no_finding(self):
        for project, party in (("Northwind", NEAR), ("Harbour", FAR)):
            wrong = sorted((k, v) for k, v in self.read(project, party).items() if v != "passed")
            self.assertEqual([], wrong[:15], "%s: %d rows draw a finding" % (project, len(wrong)))


class WallFormsRowsTest(unittest.TestCase):
    """The forms the 0.57.0 release review named, one by one, through the whole
    check, so that the table and the commit hook's path are the same code."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        self.pages = build(self.root)
        self.note = self.root / "Zones" / "Work" / "Northwind" / "Threads" / "Freight" / "Notes.md"
        self.where = "Zones/Work/Northwind/Threads/Freight/Notes.md"

    def says(self, written):
        write(self.note, "# Notes\n\nSee %s now.\n" % written)
        return [(f.severity, f.message) for f in check.run_checks(self.root, walls_only=True) if f.path == self.where]

    def test_the_forms_the_release_review_found_are_refused(self):
        for written in ("`Wikis/Meetings/wiki/people/kai-ross/`", "`cat Wikis/Meetings/wiki/people/kai-ross/`",
                        "`Wikis/Meetings/wiki/people/kai-ross//`", "`//Wikis/Meetings/wiki/people/kai-ross`",
                        "`./Wikis/Meetings/wiki/sources/260315-harvest/`", "`./wiki/sources/260315-harvest/`",
                        "`./260315-harvest/`", "`././260315-harvest.md`", "`260315-harvest`", "`260315-harvest:3`",
                        "`\"260315-harvest\"`", "`./wiki/decisions/260315 - pick-harvest/`",
                        "`wiki/entities/harvest-co/`", "`harvest-co`", "`cat -n wiki/entities/harvest-co.md`"):
            with self.subTest(written):
                found = self.says(written)
                self.assertEqual(["error"], [s for s, _ in found], found)
                self.assertIn("a wall stands between acme and birch", found[0][1])

    def test_a_message_names_the_page_and_the_wall_and_nothing_it_holds(self):
        found = self.says("`./wiki/people/kai-ross/`")
        self.assertEqual(1, len(found), found)
        self.assertIn("person page", found[0][1])
        self.assertIn("a wall stands between acme and birch", found[0][1])

    def test_a_raw_record_by_its_name_or_its_path_is_refused(self):
        for written in ("`raw/260315-harvest-call.txt`", "`./raw/260315-harvest-call/`", "`260315-harvest-call`",
                        "`cat -n Wikis/Meetings/raw/260315-harvest-call.txt:3`"):
            with self.subTest(written):
                found = self.says(written)
                self.assertEqual(["error"], [s for s, _ in found], found)

    def test_a_page_of_nobody_is_not_refused(self):
        write(self.root / "Wikis" / "Meetings" / "wiki" / "people" / "sam-nobody.md",
              "---\ntitle: Sam Nobody\ntype: person\nparty: none\n---\n\n# Sam Nobody\n")
        self.assertEqual([], self.says("`wiki/people/sam-nobody/` and `sam-nobody`"))

    def test_a_far_page_with_a_generic_name_leaves_the_projects_own_files_alone(self):
        for name in ("Notes", "Todo", "Plan", "Index"):
            for form in ("%s", "%s.md", "./%s.md", "./%s", "Northwind/%s.md", "Threads/Freight/%s.md", "../Freight/%s.md"):
                token = form % name
                for wrapper in ("code", "quoted", "cat", "link", "wikilink"):
                    with self.subTest(wrapper=wrapper, token=token):
                        found = self.says(WRAPPING[wrapper](token).split("See ", 1)[1].split(" now.")[0])
                        self.assertEqual([], found, found)
        found = self.says("`wiki/entities/notes` and `Wikis/Meetings/wiki/entities/todo.md`")
        self.assertEqual(["error", "error"], [s for s, _ in found], found)

    def says_raw(self, text):
        write(self.note, text)
        return [(f.severity, f.message) for f in check.run_checks(self.root, walls_only=True) if f.path == self.where]

    def test_plain_words_globs_and_web_addresses_name_nothing(self):
        for written in ("`docker compose up -d`", "`git status`", "`cat ./*.txt | sort`", "`ls **/*.txt`", "`ls *.txt`",
                        "`slack`", "`README`", "`readme.txt`", "`python3 -m setup`", "`vim ~/.config/git/config`",
                        "`git add setup`", "`config`", "`email`", "`ls *.json`", "`ls */`", "`ls *test*`",
                        "See https://example.com/people/kai-ross for the bio.", "`https://github.com/orchard-co`",
                        "[x](https://github.com/orchard-co)", "<https://harvest-co>"):
            with self.subTest(written):
                found = self.says(written)
                self.assertEqual([], found, found)
        for text in ("---\nsource: email\n---\n\nx\n", "---\ntags: [readme]\n---\n\nx\n", "---\nkind: draft\n---\n\nx\n",
                     "---\nrelated: planning, status\n---\n\nx\n"):
            with self.subTest(text):
                found = self.says_raw(text)
                self.assertEqual([], found, found)

    def test_a_link_to_a_bare_word_and_a_web_address_into_a_wiki_are_still_refused(self):
        for written in ("[[setup]]", "[mail](email)", "<https://x/Wikis/Meetings/wiki/people/kai-ross>",
                        "https://x/wiki/entities/harvest-co", "`kai-*`", "`harvest-*`", "`email.md`", "`cat setup.md`", "`./status.md`",
                        "`docker.markdown`"):
            with self.subTest(written):
                found = self.says(written)
                self.assertEqual(["error"], [s for s, _ in found], found)

    def test_a_file_with_many_globs_is_read_or_refused_never_cut_short(self):
        few = "\n".join("ls dir%d*" % i for i in range(300))
        found = self.says_raw("# Notes\n\n```\n%s\n```\n\nSee `harvest-*`.\n" % few)
        self.assertEqual(["error"], [s for s, _ in found], found)
        self.assertIn("harvest-*", found[0][1])
        # Only globs that can match a page are counted (#422): each of these reaches one.
        for i in range(5200):
            write(self.root / "Wikis" / "Meetings" / "wiki" / "entities" / ("zeta-%d.md" % i),
                  "---\ntitle: z\ntype: entity\nparty: acme\n---\n\n# z\n")
        many = "\n".join("ls zeta-%d*" % i for i in range(5200))
        found = self.says_raw("# Notes\n\n```\n%s\n```\n" % many)
        self.assertEqual(["error"], [s for s, _ in found], found)
        self.assertIn("cannot be read", found[0][1])

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_a_symbolic_link_into_the_wiki_or_a_walled_project_is_refused(self):
        work = self.root / "Zones" / "Work"
        thread = work / "Northwind" / "Threads" / "Freight"
        shutil.rmtree(work / ".git", ignore_errors=True)
        git(work, "init", "-q")
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}):
            commit_all(work, "start")
            links = {
                "alias.md": self.root / "Wikis" / "Meetings" / "wiki" / "entities" / "harvest-co.md",
                "relative.md": Path("../../../../../Wikis/Meetings/wiki/entities/harvest-co.md"),
                "people": self.root / "Wikis" / "Meetings" / "wiki" / "people",
                "harbour": work / "Harbour",
                "tender.md": work / "Harbour" / "Harbour.md",
            }
            for name, target in links.items():
                with self.subTest(name):
                    os.symlink(str(target), str(thread / name))
                    try:
                        git(work, "add", "-A")
                        staged = [f for f in check.run_checks(self.root, staged=work) if f.check == "walls"]
                        self.assertTrue(any("symbolic link" in f.message for f in staged), staged)
                        git(work, "reset", "-q")
                        full = [f for f in check.run_checks(self.root, walls_only=True) if "symbolic link" in f.message]
                        self.assertEqual(1, len(full), full)
                    finally:
                        git(work, "reset", "-q")
                        os.unlink(str(thread / name))
            os.symlink(str(work / "Northwind" / "Northwind.md"), str(thread / "own.md"))
            git(work, "add", "-A")
            self.assertEqual([], [f for f in check.run_checks(self.root, staged=work) if f.check == "walls"])

    def test_anchors_plain_folder_words_and_a_root_path_name_nothing(self):
        for written in ("[Setup](#setup)", "[[#Status]]", "[x](<#status>)", '<a id="status"></a>', '<a href="#setup">x</a>',
                        "`setup/`", "`cd setup/`", "`rsync -a status/ backup/`", "`rm -r config/`", "`../config`",
                        "`./setup`", "`./docker/`", "`POST /setup`", "POST /setup", "`curl /status`"):
            with self.subTest(written):
                found = self.says(written)
                self.assertEqual([], found, found)
        for text in ("# n\n\n```\napp/\n  setup/\n  config/\n```\n", "# n\n\n- app/\n  - setup/\n  - docker/\n"):
            with self.subTest(text):
                self.assertEqual([], self.says_raw(text))
        for written in ("`wiki/entities/setup/`", "[[setup]]", "`harvest-co/`"):
            with self.subTest(written):
                self.assertEqual(["error"], [x for x, _ in self.says(written)])

    def test_a_token_naming_two_pages_is_told_by_its_worst_finding(self):
        meetings = self.root / "Wikis" / "Meetings"
        write(meetings / "wiki" / "sources" / "260401-twin.md", meeting_page("Personal", "[acme]", "Twin"))
        write(meetings / "wiki" / "sources" / "260402-other.md",
              meeting_page("Work", "[birch]", "Other").replace("people:", 'transcript: "[[raw/260401-twin.txt]]"\npeople:'))
        write(meetings / "raw" / "260401-twin.txt", "x\n")
        found = self.says("`260401-twin`")
        self.assertIn("error", [x for x, _ in found], found)

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_an_own_file_that_is_not_in_the_commit_exempts_nothing(self):
        work = self.root / "Zones" / "Work"
        shutil.rmtree(work / ".git", ignore_errors=True)
        git(work, "init", "-q")
        own = work / "Northwind" / "Threads" / "Freight" / "260315-harvest.md"
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}):
            commit_all(work, "start")
            write(own, "# mine\n")                                  # on disk, not staged
            write(self.note, "# Notes\n\nSee `./260315-harvest`.\n")
            git(work, "add", str(self.note))
            found = [f for f in check.run_checks(self.root, staged=work) if f.check == "walls"]
            self.assertEqual(["error"], [f.severity for f in found], found)
            git(work, "add", str(own))                               # now the commit holds it
            self.assertEqual([], [f for f in check.run_checks(self.root, staged=work) if f.check == "walls"])
            commit_all(work, "own file")                             # and in HEAD it stays held
            write(self.note, "# Notes\n\nSee `./260315-harvest` again.\n")
            git(work, "add", str(self.note))
            self.assertEqual([], [f for f in check.run_checks(self.root, staged=work) if f.check == "walls"])

    def test_a_path_too_long_for_the_system_is_a_finding_not_a_crash(self):
        found = self.says("[x](%s/Wikis/Meetings/wiki/people/kai-ross.md)" % ("./a/.." * 1500))
        self.assertEqual(["error"], [x for x, _ in found], found)

    def test_a_folder_that_only_shares_a_name_is_still_a_folder(self):
        write(self.root / "Zones" / "Work" / "Harbour" / "Notes" / "Demo.md", "# Demo\n")
        for written in ("`Demo/`", "`Notes/Demo/`", "`./Demo/`", "`~/Applications/Garrick Demo/`"):
            with self.subTest(written):
                self.assertEqual([], self.says(written))

    def test_the_hook_reads_the_same_forms(self):
        ws = check.discover(self.root)
        ws.quick = True
        project = self.root / "Zones" / "Work" / "Northwind"
        text = "# Notes\n\nSee `./wiki/people/kai-ross/` and `260315-harvest`.\n"
        found = check.walls_for_file(ws, project, {NEAR}, self.note, text)
        self.assertEqual(["error", "error"], [f.severity for f in found])

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_commit_hook_refuses_the_forms_too(self):
        work = self.root / "Zones" / "Work"
        shutil.rmtree(work / ".git", ignore_errors=True)
        git(work, "init", "-q")
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}):
            commit_all(work, "start")
            write(self.note, "# Notes\n\nSee `./wiki/people/kai-ross/`, `260315-harvest` and `wiki/entities/quarry-ltd/`.\n")
            git(work, "add", "-A")
            found = check.run_checks(self.root, staged=work)
        self.assertEqual([("error", self.where), ("error", self.where)], [(f.severity, f.path) for f in found])

    def test_plain_forms_settle_every_token_to_one_plain_form(self):
        want = "wiki/sources/260315-harvest"
        for token in ("wiki/sources/260315-harvest", "./wiki/sources/260315-harvest/", "././wiki//sources/260315-harvest.md/",
                      "cat -n wiki/sources/260315-harvest.md:3", '"wiki/sources/260315-harvest"', "//wiki/sources/260315-harvest",
                      "wiki/sources/260315-harvest#heading", "wiki\\sources\\260315-harvest", "wiki/sources/260315-harvest.md/:3"):
            with self.subTest(token):
                self.assertIn(want, check.plain_forms(token))

    def test_the_page_index_is_built_once_a_run(self):
        calls = []
        real = check.PageNames.__init__

        def counting(self, ws):
            calls.append(1)
            real(self, ws)

        check.PageNames.__init__ = counting
        try:
            ws = check.discover(self.root)
            ws.quick = True
            project = self.root / "Zones" / "Work" / "Northwind"
            for n in range(5):
                check.walls_for_file(ws, project, {NEAR}, self.note, "See `./wiki/people/kai-ross/` %d.\n" % n)
        finally:
            check.PageNames.__init__ = real
        self.assertEqual(1, len(calls))


if __name__ == "__main__":
    unittest.main()


class SafeGlobTest(unittest.TestCase):
    """A bracket range out of order (`[h-e]`) never stops the check and reads
    the same on every Python: as literal brackets (3.9's `re` refuses it, 3.13
    reads it as matching nothing)."""

    def test_a_bad_bracket_range_is_read_as_literal_brackets(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "check_safe_glob", Path(__file__).resolve().parents[1] / "template/System/tools/check.py")
        mod = importlib.util.module_from_spec(spec)
        import sys
        sys.modules[spec.name] = mod
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(mod)
        self.assertEqual([], mod._safe_fnmatch(["kai-ross", "jo-lane"], "kai-[s-a]oss"))
        self.assertEqual(["[pick-harvest]"], mod._safe_fnmatch(["[pick-harvest]", "pick-harvest"], "[pick-harvest]"))
        self.assertEqual(["kai-ross"], mod._safe_fnmatch(["kai-ross", "jo-lane"], "kai-[r-s]oss"))
        self.assertEqual(["kai-ross"], mod._safe_fnmatch(["kai-ross"], "kai-ross"))


class BracketHostTest(unittest.TestCase):
    """An address with a bracket in its host part (`obsidian://[open?file=…`)
    never stops the check, and its query is still read."""

    def test_a_bracket_in_the_host_is_read_not_raised(self):
        import importlib.util, sys
        spec = importlib.util.spec_from_file_location(
            "check_bracket_host", Path(__file__).resolve().parents[1] / "template/System/tools/check.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(mod)
        links = mod.extract_links("See obsidian://[open?vault=v&file=wiki/people/kai-ross here.")
        self.assertIn("wiki/people/kai-ross", " ".join(t for _, t in links))
        self.assertEqual(("/y", "a=1"), (mod.urlsplit("http://[x/y?a=1").path, mod.urlsplit("http://[x/y?a=1").query))

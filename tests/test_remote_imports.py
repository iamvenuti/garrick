"""Remote access (preview): the core stays on the standard library (decision 1 of the release).

    cd tests && python3 -m unittest test_remote_imports

Nothing under `template/` and nothing in `extras/status/` imports a third-party package. In the extra, the modules that Settings and the
page action call on the Python macOS ships (`state`, `settings_actions`, `context`, `address`, `launchagent`, `setup_runtime`, and the
files they read: `store`, `logs`, `limits`) hold to it too. Only the service code (`service`, `provider`, `consent`, `tools/`) may import
the packages of the locked runtime, and only those.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
EXTRA = REPO / "extras" / "remote"

# What the standard library calls itself, for a Python that cannot say (before 3.10).
FALLBACK = set("""abc aifc antigravity argparse array ast asynchat asyncio asyncore atexit audioop base64 bdb binascii bisect builtins bz2 cProfile calendar
cgi cgitb chunk cmath cmd code codecs codeop collections colorsys compileall concurrent configparser contextlib contextvars copy copyreg
crypt csv ctypes curses dataclasses datetime dbm decimal difflib dis distutils doctest email encodings ensurepip enum errno faulthandler
fcntl filecmp fileinput fnmatch fractions ftplib functools gc genericpath getopt getpass gettext glob graphlib grp gzip hashlib heapq hmac
html http idlelib imaplib imghdr imp importlib inspect io ipaddress itertools json keyword lib2to3 linecache locale logging lzma mailbox
mailcap marshal math mimetypes mmap modulefinder msilib msvcrt multiprocessing netrc nis nntplib nt ntpath nturl2path numbers opcode
operator optparse os ossaudiodev pathlib pdb pickle pickletools pipes pkgutil platform plistlib poplib posix posixpath pprint profile pstats
pty pwd py_compile pyclbr pydoc pydoc_data pyexpat queue quopri random re readline reprlib resource rlcompleter runpy sched secrets select
selectors shelve shlex shutil signal site smtpd smtplib sndhdr socket socketserver spwd sqlite3 sre_compile sre_constants sre_parse ssl stat
statistics string stringprep struct subprocess sunau symtable sys sysconfig syslog tabnanny tarfile telnetlib tempfile termios textwrap this
threading time timeit tkinter token tokenize tomllib trace traceback tracemalloc tty turtle turtledemo types typing unicodedata unittest
urllib uu uuid venv warnings wave weakref webbrowser winreg winsound wsgiref xdrlib xml xmlrpc zipapp zipfile zipimport zlib zoneinfo""".split())
STDLIB = (set(getattr(sys, "stdlib_module_names", ())) or FALLBACK) | {"__future__"}

# The service code runs in the extra's own runtime; it may import these packages, which the lock pins.
RUNTIME_PACKAGES = {"mcp", "starlette", "uvicorn", "pydantic", "mcp_types", "anyio", "httpx2", "typing_extensions"}
SERVICE_ONLY = {"service.py", "provider.py", "consent.py"}
STDLIB_EXTRA_FILES = ("state.py", "settings_actions.py", "context.py", "address.py", "launchagent.py", "setup_runtime.py", "store.py", "logs.py",
                      "limits.py")


def imported(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name.split(".")[0], node.lineno
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0], node.lineno


class Imports(unittest.TestCase):
    def own_names(self, folder: Path):
        """The workspace's own modules: a file of Garrick that another one imports by its name."""
        return {p.stem for p in folder.glob("*.py")}

    def garrick_modules(self):
        names = set()
        for folder in [REPO / "template", *(f for f in (REPO / "extras").iterdir() if f.name != "remote")]:
            names |= {p.stem for p in folder.rglob("*.py")} if folder.is_dir() else set()
        return names

    def check(self, files, own, allowed=()):
        bad = []
        for path in files:
            for name, line in imported(path):
                if name in STDLIB or name in own or name in allowed:
                    continue
                bad.append("%s:%d imports %s" % (path.relative_to(REPO), line, name))
        self.assertEqual(bad, [])

    def test_the_core_uses_the_standard_library_alone(self):
        tools = REPO / "template" / "System" / "tools"
        files = [p for p in (REPO / "template").rglob("*.py")]
        self.assertGreater(len(files), 10)
        self.check(files, self.garrick_modules())

    def test_the_status_page_uses_the_standard_library_alone(self):
        folder = REPO / "extras" / "status"
        self.check(sorted(folder.glob("*.py")), self.garrick_modules())

    def test_the_modules_settings_calls_use_the_standard_library_alone(self):
        self.check([EXTRA / name for name in STDLIB_EXTRA_FILES], self.own_names(EXTRA))

    def test_the_service_may_use_only_what_the_lock_pins(self):
        self.check([EXTRA / name for name in sorted(SERVICE_ONLY)], self.own_names(EXTRA), RUNTIME_PACKAGES)

    def test_the_lock_holds_every_package_the_service_imports(self):
        lock = (EXTRA / "requirements.lock").read_text().lower().replace("_", "-")
        for name in ("mcp", "starlette", "uvicorn", "pydantic"):
            self.assertIn("\n%s==" % name, "\n" + lock)

    def test_no_stdlib_module_of_the_extra_imports_a_service_module(self):
        for name in STDLIB_EXTRA_FILES:
            for imp, line in imported(EXTRA / name):
                self.assertNotIn(imp, {"service", "provider", "consent"}, "%s:%d" % (name, line))

    def test_the_python_macos_ships_can_parse_them(self):
        # no syntax newer than 3.9 in the files Settings calls: parsed with the feature level of 3.9
        for name in STDLIB_EXTRA_FILES:
            ast.parse((EXTRA / name).read_text(encoding="utf-8"), feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()

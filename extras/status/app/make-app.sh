#!/bin/bash
# Builds Garrick.app: the status page in a window of its own, for the
# Dock and the app launcher. macOS only. It compiles Garrick.swift with
# the Xcode command line tools, which a Mac with git and python3 already has,
# and downloads nothing.
#
#   System/status/app/make-app.sh [--workspace FOLDER] [--dest FOLDER] [--scratch] [-- STATUS.PY FLAGS]
#
# --workspace  the workspace (default: GARRICK_WORKSPACE, or the one this
#              script sits in, three folders up)
# --dest       where the app goes (default: ~/Applications)
# --scratch    a build to look at or test: it touches nothing outside --dest.
#              No lsregister, no tccutil, no pluginkit; the app is never made
#              known to macOS. Use it with a --dest of your own, never with the
#              folder the app is installed in.
# After --, flags for status.py, such as --no-graph or --no-cmux; the app
# rebuilds the page with them. --obsidian VAULT and --no-obsidian, which
# Garrick before 0.51.0 took, are dropped, so a rebuild with an app's old
# flags stores the rest only (#318).
#
# The workspace, the python3 that runs this and the flags go into the app's
# Info.plist, so run this again after moving the workspace or changing them.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
STATUS="$(cd "$HERE/.." && pwd)/status.py"
WS="${GARRICK_WORKSPACE:-$(cd "$HERE/../../.." && pwd)}"
DEST="$HOME/Applications"
SCRATCH=0
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --workspace) WS="$2"; shift 2 ;;
    --dest) DEST="$2"; shift 2 ;;
    --scratch) SCRATCH=1; shift ;;
    --) shift; ARGS=("$@"); break ;;
    *) echo "make-app: unknown option $1" >&2; exit 64 ;;
  esac
done

[ "$(uname)" = Darwin ] || { echo "make-app: Garrick.app is for macOS." >&2; exit 1; }
WS="$(cd "$WS" 2>/dev/null && pwd)" || { echo "make-app: no such folder." >&2; exit 1; }
[ -f "$WS/System/rules.md" ] && [ -d "$WS/Zones" ] || { echo "make-app: $WS is not a Garrick workspace." >&2; exit 1; }
[ -f "$STATUS" ] || { echo "make-app: status.py is not beside app/." >&2; exit 1; }
xcrun --find swiftc >/dev/null 2>&1 || { echo "make-app: no Swift compiler; run xcode-select --install, then try again." >&2; exit 1; }
PY="$(command -v python3)"
# GARRICK_SWIFT_OPT=-Onone builds faster, for a test; nothing else sets it.
OPT=(${GARRICK_SWIFT_OPT:--O})
# What a garrick:// link must carry to be answered: new with every build, in the
# app's Info.plist and the Finder extension's.
mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"
# The folder where the app tells the extension which openers are on: one empty file each. A scratch
# build keeps it beside itself, so it never answers for the installed app's extension, and the
# extension gets an identifier of its own, so it never takes the installed one's place in macOS's list.
FINDER_STATE="$HOME/Library/Application Support/Garrick/Finder"
EXT_ID="local.garrick.status.finder"
if [ "$SCRATCH" = 1 ]; then FINDER_STATE="$DEST/.finder-state"; EXT_ID="$EXT_ID.scratch"; fi
TOKEN="$("$PY" -c 'import secrets; print(secrets.token_hex(16))')"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
NAME="Garrick.app"
APP_ID="local.garrick.status"
OLDNAME="Garrick's Status.app"   # its name before 0.10.0
BUNDLE="$WORK/$NAME/Contents"
mkdir -p "$BUNDLE/MacOS" "$BUNDLE/Resources"

# The app is main.swift beside GarrickShared.swift, which the Finder extension is built from too.
mkdir "$WORK/src"
cp "$HERE/Garrick.swift" "$WORK/src/main.swift"
xcrun swiftc "${OPT[@]}" -o "$BUNDLE/MacOS/Garrick" "$WORK/src/main.swift" "$HERE/GarrickShared.swift"

# The icon is Garrick's mark from status.py, the one the page carries, on a
# navy tile on the macOS icon grid; the app draws the menu bar's icon itself.
# The bundle identifier is the one the app had as Garrick's Status, so its
# settings carry over. The plist is written by plistlib, so no path or flag
# can break it.
"$PY" - "$STATUS" "$WORK" "$WS" "$PY" "$TOKEN" "$FINDER_STATE" "$EXT_ID" "${ARGS[@]+"${ARGS[@]}"}" <<'PY'
import importlib.util, plistlib, sys
status, work, ws, py, token, state, ext_id, given = sys.argv[1:8] + [sys.argv[8:]]
args, i = [], 0
while i < len(given):                  # the flags gone in 0.51.0 (#318), and --obsidian's vault with it
    if given[i] == "--obsidian":
        i += 2
        continue
    if given[i] != "--no-obsidian" and not given[i].startswith("--obsidian="):
        args.append(given[i])
    i += 1
spec = importlib.util.spec_from_file_location("status", status)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
open(work + "/icon.svg", "w").write(mod.app_icon())
with open(work + "/Garrick.app/Contents/Info.plist", "wb") as f:
    plistlib.dump({
        "CFBundleIdentifier": "local.garrick.status", "CFBundleName": "Garrick",
        "CFBundleDisplayName": "Garrick", "CFBundleExecutable": "Garrick",
        "CFBundleIconFile": "AppIcon", "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0", "CFBundleVersion": "1", "LSMinimumSystemVersion": "12.0",
        "LSApplicationCategoryType": "public.app-category.productivity", "NSHighResolutionCapable": True,
        "CFBundleURLTypes": [{"CFBundleURLName": "Garrick link", "CFBundleURLSchemes": ["garrick"]}], "GarrickLinkToken": token,
        "GarrickFinderState": state, "GarrickWorkspace": ws, "GarrickStatusScript": status, "GarrickPython": py, "GarrickStatusArgs": args,
    }, f)
# The Finder extension (#346): a Finder Sync extension, which macOS loads from Contents/PlugIns.
# Its only entitlement is the App Sandbox. It holds the workspace's place, the token a link must
# carry and the folder the app keeps the opener files in, and nothing else of the app's.
with open(work + "/appex-Info.plist", "wb") as f:
    plistlib.dump({
        "CFBundleIdentifier": ext_id, "CFBundleName": "GarrickFinder", "CFBundleDisplayName": "Garrick",
        "CFBundleExecutable": "GarrickFinder", "CFBundlePackageType": "XPC!",
        "CFBundleShortVersionString": "1.0", "CFBundleVersion": "1", "LSMinimumSystemVersion": "12.0",
        "NSExtension": {"NSExtensionPointIdentifier": "com.apple.FinderSync",
                        "NSExtensionPrincipalClass": "GarrickFinder.GarrickFinder"},
        "GarrickWorkspace": ws, "GarrickLinkToken": token, "GarrickFinderState": state,
    }, f)
with open(work + "/appex.entitlements", "wb") as f:
    plistlib.dump({"com.apple.security.app-sandbox": True}, f)
PY
sips -s format png "$WORK/icon.svg" --out "$WORK/icon-1024.png" >/dev/null
ICONSET="$WORK/AppIcon.iconset"
mkdir "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$WORK/icon-1024.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$WORK/icon-1024.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUNDLE/Resources/AppIcon.icns"

# Signed ad hoc, with a requirement that does not change between builds.
# macOS refuses to launch an unsigned app on Apple silicon, and an ad hoc
# signature carries no identity, so by default its designated requirement is
# the build's own cdhash. macOS keeps a permission, such as Accessibility,
# against that requirement, and every rebuild has a new cdhash: the grant
# stopped matching at every update (#361). Naming the bundle identifier as the
# requirement keeps the grant across builds, once it has been made under this
# requirement. The trade-off: ANY ad hoc signed app with the identifier
# local.garrick.status matches the requirement, and so inherits what was
# granted to Garrick. That is acceptable on a Mac whose owner builds the app
# from a workspace they run, and it is not a signature of a publisher.
FIXED_REQ="identifier \"$APP_ID\""
sign() {   # sign FILE IDENTIFIER [ENTITLEMENTS]
  local ent=()
  [ -z "${3:-}" ] || ent=(--entitlements "$3")
  codesign --force --sign - -r="designated => identifier \"$2\"" ${ent[@]+"${ent[@]}"} "$1" 2>/dev/null
}
# The extension is signed first, with its entitlements, then the app that holds it. Its failure to
# build leaves the app without the Finder menu: the app is still worth having.
APPEX="$BUNDLE/PlugIns/GarrickFinder.appex"
mkdir -p "$APPEX/Contents/MacOS"
if xcrun swiftc "${OPT[@]}" -application-extension -parse-as-library -module-name GarrickFinder \
     -o "$APPEX/Contents/MacOS/GarrickFinder" "$HERE/GarrickFinder.swift" "$HERE/GarrickShared.swift" \
     -Xlinker -e -Xlinker _NSExtensionMain 2>"$WORK/appex.log"; then
  cp "$WORK/appex-Info.plist" "$APPEX/Contents/Info.plist"
  sign "$APPEX" "$EXT_ID" "$WORK/appex.entitlements"
else
  echo "make-app: the Finder extension did not build, so the app has no Finder menu:" >&2
  head -n 5 "$WORK/appex.log" >&2
  rm -rf "$BUNDLE/PlugIns"
fi
sign "$WORK/$NAME" "$APP_ID"

# The requirement an installed app was signed with: empty when it cannot be read.
requirement() { codesign -d -r- "$1" 2>&1 | sed -n 's/^# *//; s/^designated => //p' | head -n 1; }

mkdir -p "$DEST"
RESET=0
# Replace only an earlier build of this app, under either name, never another
# app of that name.
for N in "$NAME" "$OLDNAME"; do
  [ -e "$DEST/$N" ] || continue
  OLD="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$DEST/$N/Contents/Info.plist" 2>/dev/null || true)"
  if [ "$OLD" != local.garrick.status ]; then
    [ "$N" = "$NAME" ] || continue   # another app called Garrick's Status is none of ours
    echo "make-app: $DEST/$N is another app; move it, or pass --dest." >&2; exit 1
  fi
  # Quit it only if it is the copy being replaced that is running, not an installed one elsewhere.
  if ps -axo command= | grep -qF "$DEST/$N/Contents/MacOS/"; then
    osascript -e 'tell application id "local.garrick.status" to quit' >/dev/null 2>&1 || true
    sleep 1
  fi
  # An earlier build whose requirement is not the fixed one holds a grant that
  # can never match this build, and macOS would not ask again, since an entry
  # for the identifier exists. Reset it, once, in the folder this build
  # replaces and nowhere else. Unreadable: no reset.
  OLDREQ="$(requirement "$DEST/$N")"
  if [ -n "$OLDREQ" ] && [ "$OLDREQ" != "$FIXED_REQ" ]; then RESET=1; fi
  rm -rf "${DEST:?}/$N"
done
mv "$WORK/$NAME" "$DEST/$NAME"
if [ "$SCRATCH" = 0 ]; then
  "${GARRICK_LSREGISTER:-/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister}" -f "$DEST/$NAME" 2>/dev/null || true
  if [ "$RESET" = 1 ]; then
    # The last time macOS asks: the next permission is kept across builds.
    tccutil reset Accessibility "$APP_ID" >/dev/null 2>&1 || true
    echo "make-app: Accessibility was reset for Garrick once; allow it again when macOS asks." >&2
  fi
fi
echo "$DEST/$NAME"

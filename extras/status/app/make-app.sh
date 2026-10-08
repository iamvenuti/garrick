#!/bin/bash
# Builds Garrick's Status.app: the status page in a window of its own, for the
# Dock and the app launcher. macOS only. It compiles GarrickStatus.swift with
# the Xcode command line tools, which a Mac with git and python3 already has,
# and downloads nothing.
#
#   System/status/app/make-app.sh [--workspace FOLDER] [--dest FOLDER] [-- STATUS.PY FLAGS]
#
# --workspace  the workspace (default: GARRICK_WORKSPACE, or the one this
#              script sits in, three folders up)
# --dest       where the app goes (default: ~/Applications)
# After --, flags for status.py, such as --no-graph or --obsidian VAULT; the
# app rebuilds the page with them.
#
# The workspace, the python3 that runs this and the flags go into the app's
# Info.plist, so run this again after moving the workspace or changing them.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
STATUS="$(cd "$HERE/.." && pwd)/status.py"
WS="${GARRICK_WORKSPACE:-$(cd "$HERE/../../.." && pwd)}"
DEST="$HOME/Applications"
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --workspace) WS="$2"; shift 2 ;;
    --dest) DEST="$2"; shift 2 ;;
    --) shift; ARGS=("$@"); break ;;
    *) echo "make-app: unknown option $1" >&2; exit 64 ;;
  esac
done

[ "$(uname)" = Darwin ] || { echo "make-app: Garrick's Status.app is for macOS." >&2; exit 1; }
WS="$(cd "$WS" 2>/dev/null && pwd)" || { echo "make-app: no such folder." >&2; exit 1; }
[ -f "$WS/System/rules.md" ] && [ -d "$WS/Zones" ] || { echo "make-app: $WS is not a Garrick workspace." >&2; exit 1; }
[ -f "$STATUS" ] || { echo "make-app: status.py is not beside app/." >&2; exit 1; }
xcrun --find swiftc >/dev/null 2>&1 || { echo "make-app: no Swift compiler; run xcode-select --install, then try again." >&2; exit 1; }
PY="$(command -v python3)"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
NAME="Garrick's Status.app"
BUNDLE="$WORK/$NAME/Contents"
mkdir -p "$BUNDLE/MacOS" "$BUNDLE/Resources"

xcrun swiftc -O -o "$BUNDLE/MacOS/GarrickStatus" "$HERE/GarrickStatus.swift"

# The icon is Garrick's mark from status.py, the one the page carries, on the
# macOS icon grid: an 824-unit rounded square on a 1024 canvas. The plist is
# written by plistlib, so no path or flag can break it.
"$PY" - "$STATUS" "$WORK" "$WS" "$PY" "${ARGS[@]+"${ARGS[@]}"}" <<'PY'
import importlib.util, plistlib, re, sys
status, work, ws, py, args = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:]
spec = importlib.util.spec_from_file_location("status", status)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
inner = re.search(r"<svg[^>]*>(.*)</svg>", mod.mark(full=True, image=True), re.S).group(1)
inner = re.sub(r'(<rect[^>]*?)rx="[^"]*"', r'\1rx="14.4"', inner, count=1)
open(work + "/icon.svg", "w").write(
    '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">'
    '<g transform="translate(100 100) scale(12.875)">%s</g></svg>' % inner)
# The menu bar's icon is the favicon cut, edge to edge.
open(work + "/menu.svg", "w").write(mod.mark(full=False, image=True).replace('viewBox="0 0 64 64"', 'viewBox="0 0 64 64" width="256" height="256"', 1))
with open(work + "/Garrick's Status.app/Contents/Info.plist", "wb") as f:
    plistlib.dump({
        "CFBundleIdentifier": "local.garrick.status", "CFBundleName": "Garrick's Status",
        "CFBundleDisplayName": "Garrick's Status", "CFBundleExecutable": "GarrickStatus",
        "CFBundleIconFile": "AppIcon", "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0", "CFBundleVersion": "1", "LSMinimumSystemVersion": "12.0",
        "LSApplicationCategoryType": "public.app-category.productivity", "NSHighResolutionCapable": True,
        "GarrickWorkspace": ws, "GarrickStatusScript": status, "GarrickPython": py, "GarrickStatusArgs": args,
    }, f)
PY
sips -s format png "$WORK/icon.svg" --out "$WORK/icon-1024.png" >/dev/null
ICONSET="$WORK/AppIcon.iconset"
mkdir "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$WORK/icon-1024.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$WORK/icon-1024.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUNDLE/Resources/AppIcon.icns"
sips -s format png "$WORK/menu.svg" --out "$WORK/menu-256.png" >/dev/null
sips -z 18 18 "$WORK/menu-256.png" --out "$BUNDLE/Resources/MenuIcon.png" >/dev/null
sips -z 36 36 "$WORK/menu-256.png" --out "$BUNDLE/Resources/MenuIcon@2x.png" >/dev/null

# Signed ad hoc: macOS refuses to launch an unsigned app on Apple silicon.
codesign --force --sign - "$WORK/$NAME" 2>/dev/null

mkdir -p "$DEST"
if [ -e "$DEST/$NAME" ]; then
  # Replace only an earlier build of this app, never another app of that name.
  OLD="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$DEST/$NAME/Contents/Info.plist" 2>/dev/null || true)"
  [ "$OLD" = local.garrick.status ] || { echo "make-app: $DEST/$NAME is another app; move it, or pass --dest." >&2; exit 1; }
  if pgrep -qx GarrickStatus; then
    osascript -e 'tell application id "local.garrick.status" to quit' >/dev/null 2>&1 || true
  fi
  rm -rf "${DEST:?}/$NAME"
fi
mv "$WORK/$NAME" "$DEST/$NAME"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DEST/$NAME" 2>/dev/null || true
echo "$DEST/$NAME"

// Garrick.app: the status page in a window of its own, for the Dock
// and the app launcher. It shows System/generated/status.html and nothing else,
// so the page is still made in one place, status.py. Built by make-app.sh,
// which writes the workspace, the Python to run and status.py's flags into
// Info.plist.
//
// What it adds to a browser, and only that:
//   - it rebuilds the page when it is over 30 minutes old, at launch and
//     whenever the app comes forward, and reloads whenever the page is
//     rewritten, by itself, a schedule or a terminal;
//   - it answers the page's buttons: Copy puts the text on the clipboard,
//     Rebuild now runs status.py, and Open in cmux opens a cmux tab in a
//     project's or thread's folder. The page offers Open in cmux only where
//     cmux was installed when it was built; the app checks again on the click;
//   - it gives the page each app's icon, so a card's ways to open a note
//     show as the icons its menu bar draws, where a browser shows words;
//   - every link the page holds (a note in Obsidian, a file, the web) goes to
//     the app macOS uses for it;
//   - Add your own work opens macOS's folder picker, which grants the app
//     access to the folder picked, and hands it to page_action.py (#182);
//   - Save a copy, on an earlier version of a work's file, opens macOS's
//     Save panel and hands the place chosen to page_action.py (#189);
//   - an icon in the menu bar listing the live
//     threads of the zone the graph shows, each opening a session, with a red
//     dot when the Status tab has one, and Keep awake: for a time, until
//     turned off, or while an assistant is working (agents_working.py). Settings › Menu bar switches it on,
//     opens the app at login and sets a hotkey for the menu; the app keeps
//     those three in its own defaults, as it keeps the menu between launches.
//     A field at the top of the menu finds a project or thread, and asks;
//   - instead of the icon, the same menu as a panel that slides out from the
//     left or right edge of the screen, or down from under the notch, when the
//     pointer rests there or the hotkey is pressed (Settings › Menu bar › Shows as);
//     its projects start folded, and it remembers the ones you unfold;
//   - with the preview ask on, the fields of the menu and the panel, and the
//     window the Ask hotkey opens from any app (⌘G until Settings sets another),
//     answer a request in plain words through
//     ask.py, beside status.py, and run what it proposes; off, a field opens
//     the default assistant with the words. The window is one, kept: Escape
//     hides it, and its exchange stays until New conversation or quit, with
//     Stop while a request runs. Once the box has opened, it can
//     start dictation (Settings › Then start dictation): macOS's own, or
//     another tool's, by pressing its key;
// Each time it fills the menu or the panel it leaves garrick-app-menu.json in
// the jobs folder: what it had to fill them with, in counts and zone names.
// Nothing here changes a file in the workspace, as nothing on the page does,
// except through page_action.py and ask.py (preview ask).
import AppKit
import Carbon.HIToolbox
import IOKit.pwr_mgt
import ServiceManagement
import SwiftUI
import UniformTypeIdentifiers
import UserNotifications
import WebKit

let info = Bundle.main.infoDictionary ?? [:]
let workspace = URL(fileURLWithPath: info["GarrickWorkspace"] as? String ?? NSHomeDirectory() + "/Garrick", isDirectory: true)
let generated = workspace.appendingPathComponent("System/generated", isDirectory: true)
let page = generated.appendingPathComponent("status.html")
let builder = URL(fileURLWithPath: info["GarrickStatusScript"] as? String ?? workspace.path + "/System/status/status.py")
let python = info["GarrickPython"] as? String ?? "/usr/bin/python3"
let flags = info["GarrickStatusArgs"] as? [String] ?? []
let cmuxBundle = "com.cmuxterm.app"
let claudeBundle = "com.anthropic.claudefordesktop"
let codexBundle = "com.openai.codex"
// A Claude that is not running drops a deep link while its window is still
// loading, so a cold Claude is started and the link waits for the window.
// Claude's own log writes `boot: done` once the window has loaded; where that
// log cannot be read, the fixed delay stands in and the link goes anyway.
// extras/status/obsidian/main.js waits the same way and says the same words,
// so the two hosts of one page behave alike.
let claudeLog = URL(fileURLWithPath: NSHomeDirectory() + "/Library/Logs/Claude/main.log")
let claudeReadyMark = "boot: done"
let claudeReadyPoll: TimeInterval = 0.5
let claudeReadyCeiling: TimeInterval = 40
let claudeReadySettle: TimeInterval = 1
let claudeReadyFallback: TimeInterval = 15
let maxAge: TimeInterval = 30 * 60
// The jobs extra's folder, as agent.py's jobs_dir() finds it, and what the app
// leaves there each time it fills its menu or panel: counts and zone names,
// never a note's content, for a menu that lists less than the page holds.
let jobsDir = URL(fileURLWithPath: ProcessInfo.processInfo.environment["GARRICK_JOBS_DIR"].map { NSString(string: $0).expandingTildeInPath }
	?? NSHomeDirectory() + "/Library/Logs/garrick-jobs", isDirectory: true)
let menuReport = jobsDir.appendingPathComponent("garrick-app-menu.json")
// --check loads the page out of sight, acts on nothing, prints what it found
// and quits: the test that the page loads, sees the app and is answered.
let checking = CommandLine.arguments.contains("--check")

// How a cold Claude's window was found: the mark in its log, the fixed delay
// where the log could not be read, or the ceiling reached with no mark.
enum ClaudeWindow { case ready, assumed, late }

// Where Claude's log stands now, so only what it writes after the app is
// started is read. nil where the log is not there at all.
func claudeLogSize() -> UInt64? {
	let attrs = try? FileManager.default.attributesOfItem(atPath: claudeLog.path)
	return (attrs?[.size] as? NSNumber)?.uint64Value
}

// Waits for a cold Claude's window: the mark its log writes when the window has
// loaded, read from where the log stood before the app was started, up to the
// ceiling. Blocks, so it runs off the main thread, and never waits for ever:
// every ending sends the link, and the caller says which ending it was.
func awaitClaudeWindow(from: UInt64?, sleep: (TimeInterval) -> Void = { Thread.sleep(forTimeInterval: $0) }) -> ClaudeWindow {
	guard let from, let handle = try? FileHandle(forReadingFrom: claudeLog) else {
		sleep(claudeReadyFallback)
		return .assumed
	}
	defer { try? handle.close() }
	var waited: TimeInterval = 0
	while waited < claudeReadyCeiling {
		sleep(claudeReadyPoll)
		waited += claudeReadyPoll
		guard (try? handle.seek(toOffset: from)) != nil else {    // rotated under us: no mark to find
			sleep(claudeReadyFallback)
			return .assumed
		}
		if String(data: handle.availableData, encoding: .utf8)?.contains(claudeReadyMark) == true {
			sleep(claudeReadySettle)                 // a moment for its URL handler to take the window over
			return .ready
		}
	}
	return .late
}

// What the app keeps between launches, in its own defaults: the three menu bar
// settings, the menu as the page last gave it, and whether the window was open.
let defaults = UserDefaults.standard
let kMenuBar = "menuBar", kHotkey = "hotkey", kMenu = "menu", kWindowShown = "windowShown"
// The Ask box's hotkey (preview ask): a key as the page records it, an empty
// one for none, or, never set, ⌘G, unless ⌘G is the menu's hotkey.
let kAskHotkey = "askHotkey"
let askDefault: [String: Any] = ["code": "KeyG", "mods": ["cmd"], "label": "⌘G"]
// What the Ask box does once it has opened with the cursor in its field
// (Settings › Then start dictation): nothing; macOS Dictation; or the key another
// dictation tool listens for, Fn once, Fn twice, or a shortcut recorded as the
// hotkeys are. Only a key needs the Accessibility permission, to post the press.
let kDictation = "askDictation", kDictationKey = "askDictationKey"
enum Dictation: String { case off, macos, fn, fn2, key }
func savedDictation() -> Dictation { defaults.string(forKey: kDictation).flatMap(Dictation.init) ?? .off }
// The panel's projects whose threads you unfolded, by row: every other one starts folded.
let kPanelOpen = "panelUnfolded"
// Where the menu shows: unset or "icon" in the menu bar, or a panel from an edge.
let kStyle = "menuStyle"
enum PanelEdge: String { case left, right, top }
func savedEdge() -> PanelEdge? { defaults.string(forKey: kStyle).flatMap(PanelEdge.init) }
// Keep awake: only the agent-driven mode outlives a quit, since a forgotten
// "until turned off" should not come back at login; and whether the display stays on too.
let kAwakeWorking = "awakeWhileWorking", kAwakeDisplay = "awakeDisplay"
enum Awake: Equatable { case off, on, until(Date), whileWorking }
// agents_working.py, beside status.py: exit 0 when an assistant is mid-turn, 1 when none is, 2 when it cannot tell.
let agentsCheck = builder.deletingLastPathComponent().appendingPathComponent("agents_working.py")
// ask.py, beside status.py (preview ask): a warm assistant session that answers a request and acts on it.
let asker = builder.deletingLastPathComponent().appendingPathComponent("ask.py")
let flagsFile = workspace.appendingPathComponent("System/garrick-flags.json")
// Read at each use, so switching the preview on or off needs no restart.
func askOn() -> Bool {
	guard let data = try? Data(contentsOf: flagsFile),
	      let flags = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return false }
	return flags["ask"] as? Bool == true
}
let askHint = "Ask Garrick: open, park, wake, add a line, what's open…"
// Above the turn a wall reset came with (#261, slice C sends it as "reset": "wall"): the earlier
// exchange stays on screen, and nothing of it reaches the new session.
let askAfresh = "———  The assistant started afresh here. What is above is on screen only.  ———"
// What the red dot on the mark means, said where the dot cannot be seen: its tooltip and its label.
let troubleSaid = "Something on the Status tab failed"
// Seconds the app waits for ask.py: longer than ask.py waits for its server
// (ASK_WAIT), so its own message comes first; past it, the request is let go.
// Both cover the slowest request the box can make, an action that commits and
// waits for the zone's wall check among them, because a box that gives up
// while that commit runs used to invite the retry that added the line twice
// (#92). A test holds this against ask.py's ASK_WAIT.
let askWait = 510.0
// Seconds between the app's `keep`s to ask.py (#261): the session starts with
// the app and is started again if it dies. ask.py's LEASE outlasts two of
// them, so a quit the app never heard of (a crash, a force quit) stops the
// server within LEASE; a test holds the two apart.
let askKeepEvery = 120.0

// Settings › Opening a thread, from the choices the workspace keeps, as
// status.py's shared_launchers() reads them (garrick_lib's PREFERENCES_FILE,
// committed with the workspace): {name: true or false}, a name left out being
// on, or a list of those on. Nothing saved, or nothing that reads: every way is on.
func launcherOn(_ k: String) -> Bool {
	guard let data = try? Data(contentsOf: workspace.appendingPathComponent("System/garrick-settings.json")),
	      let saved = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return true }
	if let on = saved["launchers"] as? [String: Any] { return on[k] == nil || on[k] as? Bool == true }
	if let on = saved["launchers"] as? [String] { return on.contains(k) }
	return true
}

// One request to ask.py, running: Stop interrupts it (SIGINT), and ask.py then says
// stop on its connection to the server, which ends the turn (#261).
final class AskRequest {
	let process = Process()
	var stopped = false
	func stop() {
		guard process.isRunning, !stopped else { return }
		stopped = true
		process.interrupt()
	}
}

// ask.py with its arguments, its output read line by line as it comes (#261): each
// {"progress": …} line to progress, then the final line, the reply with its kind, to done.
// Both on the main queue. Nil when ask.py could not be run, done told so first.
@discardableResult
func askStream(_ args: [String], progress: @escaping (String) -> Void, done: @escaping ([String: Any]) -> Void) -> AskRequest? {
	let r = AskRequest()
	let p = r.process
	p.executableURL = URL(fileURLWithPath: python)
	p.arguments = [asker.path, "--workspace", workspace.path, "--json"] + args
	p.currentDirectoryURL = workspace
	let out = Pipe()
	p.standardOutput = out
	p.standardError = FileHandle.nullDevice
	p.standardInput = FileHandle.nullDevice
	let late = DispatchWorkItem { if p.isRunning { p.terminate() } }
	var pending = Data()
	var final: [String: Any]?
	// The handler runs on one queue of its own, a chunk at a time; the end of the output is the end of the request.
	out.fileHandleForReading.readabilityHandler = { h in
		let chunk = h.availableData
		guard !chunk.isEmpty else {
			h.readabilityHandler = nil
			DispatchQueue.global().async {
				p.waitUntilExit()
				let timedOut = !late.isCancelled && !r.stopped && p.terminationReason == .uncaughtSignal
				late.cancel()
				// It may yet finish, so this says what to look at and never to ask again (#92).
				let gaveUp = "Garrick did not answer in \(Int(askWait / 60)) minutes. The change may still be on its way: "
					+ "an action that commits waits for the zone's wall check. Look at the Todo list, or the thread, "
					+ "before you ask again, because asking again does it a second time."
				let none: [String: Any] = r.stopped ? ["say": "Stopped.", "ok": false, "stopped": true]
					: ["say": timedOut ? gaveUp : "No answer.", "ok": false, "failed": true]
				DispatchQueue.main.async { done(final ?? none) }
			}
			return
		}
		pending.append(chunk)
		while let nl = pending.firstIndex(of: 0x0A) {
			let line = pending.subdata(in: pending.startIndex..<nl)
			pending.removeSubrange(pending.startIndex...nl)
			guard let said = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any] else { continue }
			if said["kind"] == nil, let text = said["progress"] as? String {
				DispatchQueue.main.async { progress(text) }
			} else {
				final = said
			}
		}
	}
	do { try p.run() } catch {
		out.fileHandleForReading.readabilityHandler = nil
		done(["say": "Cannot run \(python)", "ok": false, "failed": true])
		return nil
	}
	DispatchQueue.global().asyncAfter(deadline: .now() + askWait, execute: late)
	return r
}

// ask.py with its arguments; its answer, parsed, back on the main queue.
func askCall(_ args: [String], done: @escaping ([String: Any]) -> Void) {
	askStream(args, progress: { _ in }, done: done)
}

// One request and what came back, as the Ask window shows it. The exchange is a list of
// these, kept until New conversation or quit, however long the window is hidden (#261).
struct AskTurn {
	var request: String
	var reply = ""
	var kind = "command"
	var stopped = false
	var failed = false
	var afresh = false        // a wall reset came before it: the assistant started again, and what is above is on screen only
	var running = true
}

// The Ask window (preview ask): it takes the keys without bringing the app forward, as
// Spotlight does. Escape hides it and keeps the exchange; the hotkey brings the same one back.
final class AskPanel: NSPanel {
	override var canBecomeKey: Bool { true }
	override func cancelOperation(_ sender: Any?) { orderOut(nil) }
}

// The field the request is typed in: Return sends it, Shift-Return starts a new line, and
// Escape hides the window, where a text view would otherwise offer completions.
final class AskInput: NSTextView {
	var placeholder = "" { didSet { needsDisplay = true } }
	var submit: () -> Void = {}
	var hide: () -> Void = {}
	var changed: () -> Void = {}

	override func doCommand(by sel: Selector) {
		if sel == #selector(insertNewline(_:)) {
			if NSApp.currentEvent?.modifierFlags.contains(.shift) == true { return insertNewlineIgnoringFieldEditor(nil) }
			return submit()
		}
		if sel == #selector(cancelOperation(_:)) || sel == #selector(complete(_:)) { return hide() }
		super.doCommand(by: sel)
	}

	override func didChangeText() {
		super.didChangeText()
		needsDisplay = true
		changed()
	}

	override func draw(_ dirty: NSRect) {
		super.draw(dirty)
		guard string.isEmpty, !placeholder.isEmpty else { return }
		let at = NSPoint(x: textContainerInset.width + (textContainer?.lineFragmentPadding ?? 0), y: textContainerInset.height)
		(placeholder as NSString).draw(at: at, withAttributes: [.font: font ?? NSFont.systemFont(ofSize: 20),
		                                                        .foregroundColor: NSColor.placeholderTextColor])
	}
}

func savedMenu() -> [String: Any]? {
	defaults.data(forKey: kMenu).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
}
// Left in the menu bar with the window closed, it starts that way again when
// macOS opens it at login. Opened by you, from the Finder, the Dock or
// Spotlight, it shows the window all the same: see applicationDidFinishLaunching.
let startHidden = !checking && defaults.bool(forKey: kMenuBar) && savedMenu() != nil
	&& defaults.object(forKey: kWindowShown) as? Bool == false

// Whether this launch is macOS opening the app at login (Settings › Open at
// login), read from the event that opened it.
func launchedAtLogin() -> Bool {
	guard let event = NSAppleEventManager.shared().currentAppleEvent, event.eventID == AEEventID(kAEOpenApplication) else { return false }
	return event.paramDescriptor(forKeyword: AEKeyword(keyAEPropData))?.enumCodeValue == OSType(keyAELaunchedAsLogInItem)
}

// The page names a key by where it sits (KeyboardEvent.code); Carbon by the same place.
let keyCodes: [String: Int] = [
	"KeyA": kVK_ANSI_A, "KeyB": kVK_ANSI_B, "KeyC": kVK_ANSI_C, "KeyD": kVK_ANSI_D, "KeyE": kVK_ANSI_E, "KeyF": kVK_ANSI_F,
	"KeyG": kVK_ANSI_G, "KeyH": kVK_ANSI_H, "KeyI": kVK_ANSI_I, "KeyJ": kVK_ANSI_J, "KeyK": kVK_ANSI_K, "KeyL": kVK_ANSI_L,
	"KeyM": kVK_ANSI_M, "KeyN": kVK_ANSI_N, "KeyO": kVK_ANSI_O, "KeyP": kVK_ANSI_P, "KeyQ": kVK_ANSI_Q, "KeyR": kVK_ANSI_R,
	"KeyS": kVK_ANSI_S, "KeyT": kVK_ANSI_T, "KeyU": kVK_ANSI_U, "KeyV": kVK_ANSI_V, "KeyW": kVK_ANSI_W, "KeyX": kVK_ANSI_X,
	"KeyY": kVK_ANSI_Y, "KeyZ": kVK_ANSI_Z,
	"Digit0": kVK_ANSI_0, "Digit1": kVK_ANSI_1, "Digit2": kVK_ANSI_2, "Digit3": kVK_ANSI_3, "Digit4": kVK_ANSI_4,
	"Digit5": kVK_ANSI_5, "Digit6": kVK_ANSI_6, "Digit7": kVK_ANSI_7, "Digit8": kVK_ANSI_8, "Digit9": kVK_ANSI_9,
	"Minus": kVK_ANSI_Minus, "Equal": kVK_ANSI_Equal, "BracketLeft": kVK_ANSI_LeftBracket, "BracketRight": kVK_ANSI_RightBracket,
	"Backslash": kVK_ANSI_Backslash, "Semicolon": kVK_ANSI_Semicolon, "Quote": kVK_ANSI_Quote, "Comma": kVK_ANSI_Comma,
	"Period": kVK_ANSI_Period, "Slash": kVK_ANSI_Slash, "Backquote": kVK_ANSI_Grave, "Space": kVK_Space,
	"F1": kVK_F1, "F2": kVK_F2, "F3": kVK_F3, "F4": kVK_F4, "F5": kVK_F5, "F6": kVK_F6,
	"F7": kVK_F7, "F8": kVK_F8, "F9": kVK_F9, "F10": kVK_F10, "F11": kVK_F11, "F12": kVK_F12,
]

// The same key and modifiers, whatever the label says.
func sameKey(_ a: [String: Any]?, _ b: [String: Any]?) -> Bool {
	guard let a, let b, let code = a["code"] as? String, code == b["code"] as? String else { return false }
	return Set(a["mods"] as? [String] ?? []) == Set(b["mods"] as? [String] ?? [])
}

// The Ask box's hotkey as things stand: the one set, none, or ⌘G.
func askSpec() -> [String: Any]? {
	if let set = defaults.dictionary(forKey: kAskHotkey) { return set["code"] == nil ? nil : set }
	return sameKey(defaults.dictionary(forKey: kHotkey), askDefault) ? nil : askDefault
}

// A key as a menu item's key equivalent, so File › Ask Garrick… shows it.
func keyEquivalent(_ spec: [String: Any]?) -> (String, NSEvent.ModifierFlags) {
	guard let spec, let code = spec["code"] as? String else { return ("", []) }
	let marks = ["Minus": "-", "Equal": "=", "BracketLeft": "[", "BracketRight": "]", "Backslash": "\\", "Semicolon": ";",
	             "Quote": "'", "Comma": ",", "Period": ".", "Slash": "/", "Backquote": "`", "Space": " "]
	var key = marks[code] ?? ""
	if code.hasPrefix("Key") || code.hasPrefix("Digit") { key = String(code.dropFirst(code.hasPrefix("Key") ? 3 : 5)).lowercased() }
	if code.hasPrefix("F"), let n = Int(code.dropFirst()), let f = UnicodeScalar(NSF1FunctionKey + n - 1) { key = String(Character(f)) }
	var mods: NSEvent.ModifierFlags = []
	for m in spec["mods"] as? [String] ?? [] {
		switch m {
		case "cmd": mods.insert(.command)
		case "alt": mods.insert(.option)
		case "ctrl": mods.insert(.control)
		case "shift": mods.insert(.shift)
		default: break
		}
	}
	return (key, mods)
}

func modified(_ url: URL) -> Date? {
	(try? FileManager.default.attributesOfItem(atPath: url.path))?[.modificationDate] as? Date
}

// A menu row that is both a button and a submenu: AppKit gives a plain item
// with a submenu no action, so the row is a view that draws itself, runs its
// default on a click and leaves the hover to open its submenu.
// The dot of a live session: green while it waits for you, blue while it works.
func liveColor(_ state: String) -> NSColor { state == "working" ? .systemBlue : .systemGreen }

final class RowView: NSView {
	let title: String
	let live: String?
	let indent: CGFloat              // a thread listed under its project, as the field finds it
	let click: () -> Void
	init(_ title: String, live: String? = nil, depth: Int = 0, click: @escaping () -> Void) {
		self.title = title
		self.live = live
		self.indent = CGFloat(depth) * 14
		self.click = click
		let width = (title as NSString).size(withAttributes: [.font: NSFont.menuFont(ofSize: 0)]).width
		super.init(frame: NSRect(x: 0, y: 0, width: max(200, ceil(width) + 60 + indent), height: 22))
		autoresizingMask = [.width]
		setAccessibilityElement(true)
		setAccessibilityRole(.menuItem)
		setAccessibilityLabel(title)
	}
	required init?(coder: NSCoder) { nil }

	override func draw(_ dirty: NSRect) {
		let lit = enclosingMenuItem?.isHighlighted == true
		if lit {
			NSColor.selectedContentBackgroundColor.setFill()
			NSBezierPath(roundedRect: bounds.insetBy(dx: 5, dy: 0), xRadius: 4, yRadius: 4).fill()
		}
		let ink: NSColor = lit ? .selectedMenuItemTextColor : .labelColor
		let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.menuFont(ofSize: 0), .foregroundColor: ink]
		let h = (title as NSString).size(withAttributes: attrs).height
		(title as NSString).draw(at: NSPoint(x: 21 + indent, y: (bounds.height - h) / 2), withAttributes: attrs)
		if let live {                                  // a session is open in it (the cmux extra)
			liveColor(live).setFill()
			NSBezierPath(ovalIn: NSRect(x: 10 + indent, y: bounds.midY - 3, width: 6, height: 6)).fill()
		}
		if enclosingMenuItem?.hasSubmenu == true {     // the chevron AppKit draws for a plain item
			let x = bounds.maxX - 17, y = bounds.midY
			let path = NSBezierPath()
			path.move(to: NSPoint(x: x, y: y + 4)); path.line(to: NSPoint(x: x + 4, y: y)); path.line(to: NSPoint(x: x, y: y - 4))
			path.lineWidth = 1.6; path.lineCapStyle = .round; path.lineJoinStyle = .round
			(lit ? ink : NSColor.secondaryLabelColor).setStroke()
			path.stroke()
		}
	}

	override func mouseUp(with event: NSEvent) {
		enclosingMenuItem?.menu?.cancelTracking()
		DispatchQueue.main.async(execute: click)
	}
}

// The field at the top of the icon's menu, as the panel has one: typing finds
// a project or thread, and Return opens the first found or, with none, asks.
// It is a search field in the menu's own window, which passes it the keys
// while the menu is open.
final class MenuField: NSView, NSSearchFieldDelegate {
	let field = NSSearchField()
	var changed: (String) -> Void = { _ in }
	var submit: (String) -> Void = { _ in }

	init(_ placeholder: String) {
		super.init(frame: NSRect(x: 0, y: 0, width: 240, height: 32))
		autoresizingMask = [.width]
		field.frame = NSRect(x: 14, y: 5, width: 212, height: 22)
		field.autoresizingMask = [.width]
		field.placeholderString = placeholder
		field.setAccessibilityLabel(placeholder)
		field.delegate = self
		addSubview(field)
	}
	required init?(coder: NSCoder) { nil }

	func controlTextDidChange(_ note: Notification) { changed(field.stringValue) }

	func control(_ control: NSControl, textView: NSTextView, doCommandBy sel: Selector) -> Bool {
		guard sel == #selector(NSResponder.insertNewline(_:)) else { return false }
		submit(field.stringValue)
		return true
	}
}

// What a field finds among a zone's projects, the menu's and the panel's
// alike: a project whose name holds the words keeps all its threads;
// otherwise only its threads whose names do.
func found(_ rows: [[String: Any]], _ query: String) -> [[String: Any]] {
	let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
	guard !q.isEmpty else { return rows }
	func hit(_ r: [String: Any]) -> Bool { (r["n"] as? String ?? "").lowercased().contains(q) }
	return rows.compactMap { r in
		if hit(r) { return r }
		let t = (r["t"] as? [[String: Any]] ?? []).filter(hit)
		return t.isEmpty ? nil : r.merging(["t": t]) { _, new in new }
	}
}

// A row's actions on one line: the icon of each app it can open in, the
// default on a tinted square, each named in its tooltip. A click runs it and
// closes the menu.
final class ActionBar: NSView {
	let acts: [[String: Any]]
	let pick: ([String: Any]) -> Void
	let side: CGFloat = 24, gap: CGFloat = 10, pad: CGFloat = 16

	init(_ acts: [[String: Any]], pick: @escaping ([String: Any]) -> Void) {
		self.acts = acts
		self.pick = pick
		super.init(frame: NSRect(x: 0, y: 0, width: pad * 2 + CGFloat(acts.count) * (side + gap) - gap, height: side + 12))
		for (n, a) in acts.enumerated() {
			let b = NSButton(frame: NSRect(x: pad + CGFloat(n) * (side + gap), y: 6, width: side, height: side))
			b.isBordered = false
			b.imageScaling = .scaleProportionallyUpOrDown
			b.image = a["icon"] as? NSImage
			b.toolTip = a["l"] as? String
			b.setAccessibilityLabel(a["l"] as? String)
			b.tag = n
			b.target = self
			b.action = #selector(press(_:))
			addSubview(b)
		}
	}
	required init?(coder: NSCoder) { nil }

	override func draw(_ dirty: NSRect) {
		guard let n = acts.firstIndex(where: { $0["d"] as? Bool == true }) else { return }
		let r = NSRect(x: pad + CGFloat(n) * (side + gap) - 4, y: 2, width: side + 8, height: side + 8)
		NSColor.controlAccentColor.withAlphaComponent(0.25).setFill()
		NSBezierPath(roundedRect: r, xRadius: 6, yRadius: 6).fill()
	}

	@objc func press(_ sender: NSButton) {
		enclosingMenuItem?.menu?.cancelTracking()
		let a = acts[sender.tag]
		DispatchQueue.main.async { self.pick(a) }
	}
}

// An app's icon as a PNG data URL, for the page: the same icon the menu bar
// draws, so a card's ways to open a note look as its menu row's do.
func pngURL(_ image: NSImage, side: Int = 64) -> String? {
	guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: side, pixelsHigh: side, bitsPerSample: 8,
	                                 samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
	                                 bytesPerRow: 0, bitsPerPixel: 0) else { return nil }
	NSGraphicsContext.saveGraphicsState()
	NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
	image.draw(in: NSRect(x: 0, y: 0, width: side, height: side))
	NSGraphicsContext.restoreGraphicsState()
	return rep.representation(using: .png, properties: [:]).map { "url(data:image/png;base64,\($0.base64EncodedString()))" }
}

final class StatusApp: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuDelegate, NSMenuItemValidation, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
	var window: NSWindow!
	var web: WKWebView!
	var watcher: DispatchSourceFileSystemObject?
	var shown: Date?
	var rebuilding = false
	var pendingReload: DispatchWorkItem?
	var heard: [String] = []          // what --check caught instead of acting on
	var statusItem: NSStatusItem?
	var edgePanel: EdgePanel?
	// Living outside the window, as an icon or a panel: closing the window keeps the app.
	var resident: Bool { statusItem != nil || edgePanel != nil }
	var menuState: [String: Any]?     // what the page last said the menu lists
	var menuHeard: (at: Date, data: Bool, zones: Int, count: Int)?   // when the page last said it, with rows or not, and how often since launch
	var pageLoaded: Date?             // when the page last finished loading
	var settingsAsked: Date?          // Settings asked for from the menu or the panel, opened at the next load within a minute
	var pageErrors: [[String: Any]] = []   // the page's script errors since, where and of what kind
	let launched = Date()
	var again = false                 // a rebuild asked for during one: one more after it
	var hotKey: EventHotKeyRef?
	var keySpec: [String: Any]?       // the hotkey Settings set, as registered
	var askKey: EventHotKeyRef?       // the Ask box's, from any app (preview ask)
	var askKeySpec: [String: Any]?    // and the key it holds
	var askMenuItem: NSMenuItem?      // File › Ask Garrick…, which shows that key
	var recording = false             // a hotkey field in Settings has the keys: both hot keys let go of theirs
	var keySaid: [String: String] = [:]   // why a key was refused, said under its field
	var hotKeyHandler: EventHandlerRef?
	var menuField: MenuField?         // the icon's menu's field, made anew each time it opens
	var hourly: Timer?
	var awake: Awake = .off
	var held: [String: IOPMAssertionID] = [:]   // the sleep assertions this app holds, by type
	var agentsBusy: Bool?                       // the last check: nil when it could not tell
	var awakeTimer: Timer?
	var askPanel: AskPanel?
	var askKeeper: Timer?             // the `keep` every askKeepEvery seconds (preview ask)
	var askKept = false               // whether this app has a background session kept, for quit to stop it
	var askField: AskInput!
	var askInputHeight: NSLayoutConstraint!
	var askLog: NSTextView!           // the exchange, once the window has expanded
	var askLogBox: NSScrollView!
	var askWorking: NSStackView!      // what is happening now, with Stop
	var askSpinner: NSProgressIndicator!
	var askSaid: NSTextField!
	var askStopButton: NSButton!
	var askReply: NSTextField!        // the last reply, while the window is compact
	var askFoot: NSStackView!
	var askNewButton: NSButton!
	var askTurns: [AskTurn] = []      // the exchange: only New conversation and quit clear it
	var askRunning: AskRequest?       // the request on its way, which Stop interrupts
	var askExpanded = false           // grown for an answer, a question back or a wall reset; compact again on New conversation
	var askPreparing = false          // the session starting when the window opened: a request sent now waits for it once

	func applicationDidFinishLaunching(_ note: Notification) {
		// The app starts as a regular one, in the Dock (the end of this file), so a launch you make goes
		// straight to the window. Only macOS opening it at login, left in the menu bar, goes out of sight,
		// and loses its Dock icon first thing: this is the first point a login launch can be told from yours.
		let outOfSight = startHidden && launchedAtLogin()
		if outOfSight { NSApp.setActivationPolicy(.accessory) }
		NSApp.mainMenu = menu()
		let config = WKWebViewConfiguration()
		// So the page, and Safari's Web Inspector, can tell the app's view from a browser's.
		config.applicationNameForUserAgent = "GarrickApp"
		config.userContentController.add(self, name: "garrick")
		config.userContentController.addUserScript(appScript())
		web = WKWebView(frame: .zero, configuration: config)
		web.navigationDelegate = self
		web.uiDelegate = self
		// Safari › Develop › this Mac lists the page, for its console and its storage.
		if #available(macOS 13.3, *) { web.isInspectable = true }
		web.allowsMagnification = true

		window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1400, height: 900),
		                  styleMask: [.titled, .closable, .miniaturizable, .resizable],
		                  backing: .buffered, defer: false)
		window.title = "Garrick"
		window.contentView = web
		window.isReleasedWhenClosed = false   // closed into the menu bar, it opens again
		window.delegate = self
		window.acceptsMouseMovedEvents = true   // so the panel's edge is felt with this window in front too
		window.center()
		window.setFrameAutosaveName("GarrickStatus")   // the name it had as Garrick, so the window keeps its place
		if checking {
			guard FileManager.default.fileExists(atPath: page.path) else {
				print("no page at \(page.path): build it with status.py first")   // the check would wait for it forever
				exit(1)
			}
			return load()
		}
		menuState = savedMenu()
		present()
		applyHotKeys()    // the menu's, and the Ask box's with the preview ask on
		if resident && defaults.bool(forKey: kAwakeWorking) { setAwake(.whileWorking) }
		// Out of sight, nothing brings the app forward to check the page's age.
		hourly = Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { [weak self] _ in self?.freshen() }
		if !outOfSight { showWindow() }   // a launch you make always shows something

		watch()
		if FileManager.default.fileExists(atPath: page.path) { load() }
		freshen()
		// The Ask session starts once the window is up, never before it: askCall() runs ask.py off
		// the main queue, so the window waits for none of it (#261).
		DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [weak self] in
			guard let self = self else { return }
			self.askKeep()
			self.askKeeper = Timer.scheduledTimer(withTimeInterval: askKeepEvery, repeats: true) { [weak self] _ in self?.askKeep() }
		}
	}

	// Ask's background session (#261): kept while the preview is on, started again by ask.py if it
	// died, and stopped once the preview is switched off. Read at each tick, so the switch needs no restart.
	func askKeep() {
		if checking { return }
		if askOn() {
			askKept = true
			askCall(["keep"]) { _ in }
		} else if askKept {
			askKept = false
			askCall(["stop"]) { _ in }
		}
	}

	// Quit stops the session this app kept. Run here and waited for, briefly: askCall() would return
	// before the app is gone. A crash or a force quit never gets here, and ask.py's lease covers those.
	func applicationWillTerminate(_ note: Notification) {
		askKeeper?.invalidate()
		guard askKept && !checking else { return }
		let p = Process()
		p.executableURL = URL(fileURLWithPath: python)
		p.arguments = [asker.path, "--workspace", workspace.path, "--json", "stop"]
		p.currentDirectoryURL = workspace
		p.standardOutput = FileHandle.nullDevice
		p.standardError = FileHandle.nullDevice
		p.standardInput = FileHandle.nullDevice
		guard (try? p.run()) != nil else { return }
		let until = Date().addingTimeInterval(2)
		while p.isRunning && Date() < until { usleep(50_000) }
		if p.isRunning { p.terminate() }
	}

	// With the icon in the menu bar, or the panel at an edge, closing the window leaves the app there.
	func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { edgePanel == nil && statusItem == nil }

	func applicationShouldHandleReopen(_ app: NSApplication, hasVisibleWindows: Bool) -> Bool {
		if !hasVisibleWindows { showWindow() }
		return true
	}

	func windowWillClose(_ note: Notification) {
		if recording { recording = false; applyHotKeys() }    // the field that had the keys goes with the window
		guard resident else { return }
		defaults.set(false, forKey: kWindowShown)
		NSApp.setActivationPolicy(.accessory)  // no Dock icon while only the menu bar's or the panel is there
	}

	@objc func showWindow(_ sender: Any? = nil) {
		NSApp.setActivationPolicy(.regular)
		window.makeKeyAndOrderFront(nil)
		NSApp.activate(ignoringOtherApps: true)
		defaults.set(true, forKey: kWindowShown)
	}

	// Settings from the menu or the panel (#34): the window forward, as Open
	// Garrick brings it, then Settings, as ⌘, opens it. A page not loaded yet, or
	// reloaded by the rebuild that coming forward can start, opens it once loaded.
	@objc func showSettings(_ sender: Any? = nil) {
		showWindow()
		settingsAsked = Date()
		if pageLoaded != nil && !web.isLoading { openSettings(nil) }
	}

	// Left in the Dock for days, it still checks the page's age when it comes forward.
	func applicationDidBecomeActive(_ note: Notification) { if !checking { freshen() } }

	func load() {
		shown = modified(page)
		pageErrors = []
		web.loadFileURL(page, allowingReadAccessTo: generated)
	}

	func reload() {
		guard modified(page) != nil else { return }
		if web.url == nil { return load() }
		shown = modified(page)
		pageErrors = []
		web.reload()
	}

	func freshen(force: Bool = false) {
		let age = modified(page).map { -$0.timeIntervalSinceNow } ?? .infinity
		if force || age >= maxAge { rebuild(queue: force) }
	}

	// A rebuild asked for (queue) while one runs follows it: the one running may
	// have read the workspace before a button changed it.
	func rebuild(queue: Bool = false) {
		guard !rebuilding else { again = again || queue; return }
		rebuilding = true
		window.subtitle = "Rebuilding…"
		let p = Process()
		p.executableURL = URL(fileURLWithPath: python)
		p.arguments = [builder.path, "--workspace", workspace.path] + flags
		p.currentDirectoryURL = workspace
		p.standardOutput = FileHandle.nullDevice
		p.standardError = FileHandle.nullDevice
		p.terminationHandler = { proc in
			DispatchQueue.main.async {
				self.rebuilding = false
				self.window.subtitle = proc.terminationStatus == 0 ? "" : "Did not rebuild; showing the last build"
				if self.watcher == nil { self.watch() }
				if self.web.url == nil { self.load() }
				if self.again { self.again = false; self.rebuild() }
			}
		}
		do { try p.run() } catch {
			rebuilding = false
			window.subtitle = "Cannot run \(python)"
		}
	}

	// status.py writes a temporary file and renames it over status.html, so the
	// folder is what changes. Debounced, so one rebuild is one reload.
	func watch() {
		let fd = open(generated.path, O_EVTONLY)
		guard fd >= 0 else { return }
		let src = DispatchSource.makeFileSystemObjectSource(fileDescriptor: fd, eventMask: .write, queue: .main)
		src.setEventHandler { [weak self] in
			guard let self, let m = modified(page), m != self.shown else { return }
			self.pendingReload?.cancel()
			let work = DispatchWorkItem { self.reload() }
			self.pendingReload = work
			DispatchQueue.main.asyncAfter(deadline: .now() + 0.5, execute: work)
		}
		src.setCancelHandler { close(fd) }
		src.resume()
		watcher = src
	}

	// `alsoNotify: false` keeps a message in the window only. A launcher that
	// opened at once passes it: the app it opened is in front, saying as much,
	// and a notification for every click of the menu's icons would be noise.
	// A cold start, which takes seconds, and every failure keep the notification.
	func toast(_ text: String, alsoNotify: Bool = true) {
		let quoted = (try? String(data: JSONSerialization.data(withJSONObject: [text]), encoding: .utf8)) ?? "[\"\"]"
		web.evaluateJavaScript("""
			(function(s){var t=document.getElementById('toast');if(!t)return;t.textContent=s;t.style.opacity=1;
			setTimeout(function(){t.style.opacity=0},4000)})(\(quoted)[0])
			""")
		// The toast lives in the window. Asked from the menu, the panel or the
		// Ask box with the window out of sight, the answer would go unseen, so it
		// comes as a notification too.
		if alsoNotify, window == nil || !window.isVisible || !NSApp.isActive { notify(text) }
	}

	func notify(_ text: String) {
		if checking { return }
		let center = UNUserNotificationCenter.current()
		center.requestAuthorization(options: [.alert]) { granted, _ in
			guard granted else { return }
			let note = UNMutableNotificationContent()
			note.title = "Garrick"
			note.body = text
			center.add(UNNotificationRequest(identifier: UUID().uuidString, content: note, trigger: nil))
		}
	}

	// MARK: the page's buttons

	func userContentController(_ c: WKUserContentController, didReceive message: WKScriptMessage) {
		guard let body = message.body as? [String: Any] else { return }
		if let e = body["pageError"] as? [String: Any] {   // appScript's: the page's script stopped somewhere
			pageErrors = Array((pageErrors + [e]).suffix(5))
			return
		}
		if let m = body["menu"] {
			if checking { menuState = m as? [String: Any]; return heard.append("menu") }
			let data = (m as? [String: Any])?["data"] as? [String: Any]
			menuHeard = (Date(), data != nil, (data?["zones"] as? [Any])?.count ?? -1, (menuHeard?.count ?? 0) + 1)
			return setMenu(m as? [String: Any])
		}
		if checking { return heard.append(body.keys.sorted().joined(separator: "+")) }
		if body["pick"] as? String == "folder" { return pickFolder() }
		if let save = body["save"] as? [String: Any] { return saveVersion(save) }
		if let request = body["app"] as? [String: Any] { return setting(request) }
		// A Copy button's own text. A launch carries the phrase too, for an app
		// built before 0.28.0; here the launcher owns the clipboard and says
		// when it replaced it, so the copy is left to it and never happens twice.
		if let text = body["copy"] as? String, !text.isEmpty, body["launch"] == nil {
			NSPasteboard.general.clearContents()
			NSPasteboard.general.setString(text, forType: .string)
		}
		if let app = body["launch"] as? String, let folder = body["folder"] as? String {
			launch(app, folder, phrase: body["phrase"] as? String ?? "", desk: body["dk"] != nil)
		} else if let folder = body["cmux"] as? String {
			openInCmux(folder)                 // a page built before Open in Claude and Codex
		}
		if body["rebuild"] as? Bool == true { freshen(force: true) }
		if let request = body["act"] as? [String: Any] { act(request) }
	}

	// Add your own work (#182): macOS's own folder picker, which also grants
	// this app access to the folder picked, as a sheet on the window. It opens
	// on the cloud drives where there are any, since that is where work is
	// usually kept. The folder goes to page_action.py's `discover`, which
	// reads its names and dates and changes nothing in it; discover.py
	// refuses the whole Mac, the home folder and Garrick's own folders. The
	// page then opens on what it found.
	func pickFolder() {
		let panel = NSOpenPanel()
		panel.canChooseDirectories = true
		panel.canChooseFiles = false
		panel.allowsMultipleSelection = false
		panel.canCreateDirectories = false
		panel.prompt = "Choose"
		panel.message = "Choose the folder you work from. Garrick reads the names and dates in it, and never changes anything."
		let cloud = URL(fileURLWithPath: NSHomeDirectory() + "/Library/CloudStorage", isDirectory: true)
		var isDir: ObjCBool = false
		panel.directoryURL = FileManager.default.fileExists(atPath: cloud.path, isDirectory: &isDir) && isDir.boolValue
			? cloud : URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
		panel.beginSheetModal(for: window) { [weak self] response in
			guard let self, response == .OK, let folder = panel.url else { return }
			self.toast("Looking through \(folder.lastPathComponent): names and dates only, and nothing in it is changed.",
			           alsoNotify: false)
			self.act(["verb": "discover", "folder": folder.path])
		}
	}

	// Save a copy, on an earlier version of a work's file (#189): macOS's own
	// Save panel, as a sheet on the window, on Downloads, with the name the
	// page gives it ("Launch brief, 3 days ago.docx"). The place chosen goes
	// to page_action.py's `work-file`, which writes the version there as a
	// file of its own and refuses the user's folder and Garrick's copy. Nothing
	// is ever put back over the file itself.
	func saveVersion(_ save: [String: Any]) {
		guard var request = save["act"] as? [String: Any] else { return }
		let panel = NSSavePanel()
		panel.canCreateDirectories = true
		panel.nameFieldStringValue = save["name"] as? String ?? "Earlier version"
		panel.message = "Save this version as a separate file. The file in the work is not changed."
		panel.prompt = "Save"
		panel.directoryURL = URL(fileURLWithPath: NSHomeDirectory() + "/Downloads", isDirectory: true)
		panel.beginSheetModal(for: window) { [weak self] response in
			guard let self, response == .OK, let url = panel.url else { return }
			request["to"] = url.path
			self.act(request)
		}
	}

	// A folder of this workspace that still exists, or nil, with the page rebuilt.
	func inWorkspace(_ path: String) -> URL? {
		let folder = URL(fileURLWithPath: path, isDirectory: true).standardizedFileURL
		let root = workspace.standardizedFileURL.path
		var isDir: ObjCBool = false
		guard folder.path == root || folder.path.hasPrefix(root + "/"),     // the root: Process the Inbox
		      FileManager.default.fileExists(atPath: folder.path, isDirectory: &isDir), isDir.boolValue else {
			toast("That folder is not in this workspace any more. Rebuilding the page.")
			freshen(force: true)
			return nil
		}
		return folder
	}

	// The clipboard is replaced in one place only, and only where a launcher
	// cannot take the phrase itself and did open the folder: Codex and cmux.
	// The toast that follows says the clipboard now holds the phrase, so it is
	// never replaced without the user being told in the same breath.
	func copyText(_ text: String) {
		guard !text.isEmpty else { return }
		NSPasteboard.general.clearContents()
		NSPasteboard.general.setString(text, forType: .string)
	}

	// What a launcher says when it is done. Every sentence names the phrase one
	// way or another, so no launcher leaves the phrase to be rebuilt: Claude
	// types it into the session, Codex and cmux put it on the clipboard and say
	// so, and Finder, which can take nothing, names it. The Obsidian plugin
	// says the same words; tests/test_status_more.py compares the two.
	func opened(_ app: String, _ name: String, _ phrase: String) -> String {
		if phrase.isEmpty { return "Opened \(app) in \(name)." }
		if app == "Claude" { return "Opened Claude in \(name) with “\(phrase)” typed in. Press Enter to send it." }
		return "Opened \(app) in \(name). The clipboard now holds “\(phrase)”; paste it to resume."
	}

	func notOpened(_ app: String, _ name: String, _ phrase: String) -> String {
		phrase.isEmpty ? "\(app) did not open \(name)."
			: "\(app) did not open \(name). The phrase that resumes it is “\(phrase)”."
	}

	func showedInFinder(_ name: String, _ phrase: String) -> String {
		phrase.isEmpty ? "Showed \(name) in Finder."
			: "Showed \(name) in Finder. Nothing was copied; the phrase that resumes it is “\(phrase)”."
	}

	func startingClaude(_ name: String) -> String {
		"Starting Claude, then opening \(name). This takes a few seconds."
	}

	func claudeWasLate(_ name: String, _ phrase: String) -> String {
		phrase.isEmpty ? "Claude did not say its window was ready within forty seconds. Opened \(name) anyway."
			: "Claude did not say its window was ready within forty seconds. Opened \(name) anyway; "
			  + "if the session came up empty, the phrase that resumes it is “\(phrase)”."
	}

	// Open a project or thread folder, or the workspace root, in Claude, Codex or cmux, or show it
	// in Finder. Claude gets the phrase typed into a new session, for you to send; Codex and cmux get
	// the folder, and the phrase goes on the clipboard. Nothing is sent and no
	// command is typed into a terminal. Says whether anything was opened.
	// Every route reports on screen when it is done, a failure included, and
	// not before: the page says it is opening, this says what opened. A cold
	// Claude is started first and the link waits for its window, so the return
	// value there says only that the wait began; startClaude() reports it.
	// cmux with the cmux extra's desk ready (the page's menu says so, or the
	// caller's row or Ask's answer does) goes through page_action.py instead:
	// a tab in that folder that starts the assistant on the phrase, or on
	// "open X" for a project or thread, as the page's buttons open it.
	@discardableResult
	func launch(_ app: String, _ path: String, phrase: String, desk: Bool = false) -> Bool {
		guard let folder = inWorkspace(path) else { return false }
		if app == "cmux" && (desk || deskReady()) {
			act(["verb": "open", "folder": folder.path, "prompt": phrase])
			return true
		}
		switch app {
		case "claude":
			guard NSWorkspace.shared.urlForApplication(withBundleIdentifier: claudeBundle) != nil else {
				toast("Claude is not installed here any more. Rebuilding the page without it.")
				freshen(force: true)
				return false
			}
			var c = URLComponents()
			c.scheme = "claude"; c.host = "code"; c.path = "/new"
			c.queryItems = [URLQueryItem(name: "folder", value: folder.path)] + (phrase.isEmpty ? [] : [URLQueryItem(name: "q", value: phrase)])
			guard let url = c.url else { return false }
			let name = folder.lastPathComponent
			// A running Claude takes the link at once, as it always has. A cold
			// one would drop it while its window loads, so it is started first.
			if NSRunningApplication.runningApplications(withBundleIdentifier: claudeBundle).isEmpty {
				startClaude(url, name: name, phrase: phrase)
				return true
			}
			return sendToClaude(url, name: name, phrase: phrase, window: nil)
		case "codex":
			guard let codex = NSWorkspace.shared.urlForApplication(withBundleIdentifier: codexBundle) else {
				toast("Codex is not installed here any more. Rebuilding the page without it.")
				freshen(force: true)
				return false
			}
			let cli = ["Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex", "Contents/Resources/codex", "Contents/Resources/bin/codex"]
				.map { codex.appendingPathComponent($0) }
				.first { FileManager.default.isExecutableFile(atPath: $0.path) }
			guard let cli else {
				// Each build checks for this launcher, so the page does not
				// offer Codex without it; a page built before it went missing still can.
				toast("Codex's own launcher is missing; reinstall the Codex app. Rebuilding the page without it.")
				freshen(force: true)
				return false
			}
			let p = Process()
			p.executableURL = cli
			p.arguments = ["app", folder.path]
			p.standardOutput = FileHandle.nullDevice
			p.standardError = FileHandle.nullDevice
			do { try p.run() } catch {
				toast(notOpened("Codex", folder.lastPathComponent, phrase))
				return false
			}
			copyText(phrase)                 // it opened: the phrase goes over, and the toast says so
			toast(opened("Codex", folder.lastPathComponent, phrase), alsoNotify: false)
			return true
		case "cmux":
			return openInCmux(folder.path, phrase: phrase)
		case "finder":
			NSWorkspace.shared.activateFileViewerSelecting([folder])
			toast(showedInFinder(folder.lastPathComponent, phrase), alsoNotify: false)
			return true
		default:
			return false
		}
	}

	// Sends the link to a Claude whose window is up, and says what happened.
	// `window` is how a cold Claude's window was found, nil for a Claude that
	// was already running; a wait that ran out says the session may have come
	// up empty and names the phrase again.
	@discardableResult
	func sendToClaude(_ url: URL, name: String, phrase: String, window: ClaudeWindow?) -> Bool {
		guard NSWorkspace.shared.open(url) else {
			toast(notOpened("Claude", name, phrase))
			return false
		}
		toast(window == .late ? claudeWasLate(name, phrase) : opened("Claude", name, phrase), alsoNotify: window != nil)
		return true
	}

	// Starts a Claude that is not running, waits for its window, then sends the
	// link. It says it is starting first, so a ten-second gap does not look
	// like nothing happened, and says what opened when the link has gone.
	// Nothing is sent to anybody: the phrase is typed into the new session, for
	// you to send, exactly as it is for a Claude already running.
	func startClaude(_ url: URL, name: String, phrase: String) {
		guard let app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: claudeBundle) else { return }
		let from = claudeLogSize()                   // before it starts: only what it writes from here counts
		toast(startingClaude(name))
		let cfg = NSWorkspace.OpenConfiguration()
		cfg.activates = true
		NSWorkspace.shared.openApplication(at: app, configuration: cfg) { [weak self] _, error in
			guard let self else { return }
			if error != nil {
				DispatchQueue.main.async { self.toast(self.notOpened("Claude", name, phrase)) }
				return
			}
			DispatchQueue.global(qos: .userInitiated).async {
				let window = awaitClaudeWindow(from: from)
				DispatchQueue.main.async { self.sendToClaude(url, name: name, phrase: phrase, window: window) }
			}
		}
	}

	// Whether the page says the desk opens cmux here: the cmux extra, cmux
	// itself, as its menu's `dk` says.
	func deskReady() -> Bool {
		(menuState?["data"] as? [String: Any])?["dk"] as? Int == 1
	}

	// A button that changes something: page_action.py,
	// beside status.py, does it and commits it, and says what it did. The app
	// only passes the request on; the script checks every part of it. It waits
	// as long as the script takes, a slow wall check included, and every
	// request gets a reply on the page, a failed one too: the page shows a
	// request running until its reply comes.
	func act(_ request: [String: Any]) {
		guard let data = try? JSONSerialization.data(withJSONObject: request) else { return }
		let script = builder.deletingLastPathComponent().appendingPathComponent("page_action.py")
		guard FileManager.default.fileExists(atPath: script.path) else {
			return acted(request, ["ok": false, "say": "This page's actions need page_action.py beside status.py."])
		}
		let p = Process()
		p.executableURL = URL(fileURLWithPath: python)
		p.arguments = [script.path, "--workspace", workspace.path]
		p.currentDirectoryURL = workspace
		let input = Pipe(), output = Pipe()
		p.standardInput = input
		p.standardOutput = output
		p.standardError = FileHandle.nullDevice
		p.terminationHandler = { _ in
			let reply = output.fileHandleForReading.readDataToEndOfFile()
			let said = (try? JSONSerialization.jsonObject(with: reply)) as? [String: Any]
			DispatchQueue.main.async {
				self.acted(request, said ?? ["ok": false, "say": "That did not work."])
				if self.rebuilds(request) { self.freshen(force: true) }
			}
		}
		do {
			try p.run()
			input.fileHandleForWriting.write(data)
			input.fileHandleForWriting.closeFile()
		} catch {
			acted(request, ["ok": false, "say": "Cannot run \(python)"])
		}
	}

	// The page asking what is running (page_action.py's "operations"), how
	// far a copy or a move of a work's files has got ("files-progress"), what
	// Settings › Memory's unsaved values would do ("memory-preview"), or a note
	// for Explore's Preview ("note-read", #206), only reads: the reply goes to
	// the page, with no toast and no rebuild, or asking would rebuild the page
	// it asks from.
	func reading(_ request: [String: Any]) -> Bool { ["operations", "files-progress", "memory-preview", "note-read"].contains(request["verb"] as? String ?? "") }

	// What changes nothing the page shows is not followed by a rebuild, which
	// would reload the page under the preview: a request that only reads, and
	// a note opened in its own app from it ("note-open"), which still toasts.
	func rebuilds(_ request: [String: Any]) -> Bool { !reading(request) && request["verb"] as? String != "note-open" }

	// The reply: the toast, then the page, which shows a park or a wake at once
	// (the rebuild confirms it) and ends what it showed running.
	func acted(_ request: [String: Any], _ said: [String: Any]) {
		if !reading(request) { toast(said["say"] as? String ?? "That did not work.") }
		if let both = try? JSONSerialization.data(withJSONObject: [request, said]),
		   let text = String(data: both, encoding: .utf8) {
			web.evaluateJavaScript("(function(a){window.GarrickActed&&window.GarrickActed(a[0],a[1])})(\(text))")
		}
	}

	// Only a folder inside this workspace, and only through Launch Services, as
	// Finder's Open With would: no socket, no password, no command typed.
	// Says whether it was asked to; a failure after that is a toast of its own.
	@discardableResult
	// The phrase goes on the clipboard only once cmux has the folder, and the
	// toast says so. A page built before 0.5.0 sends no phrase, and then
	// nothing is copied and the toast names nothing to paste.
	func openInCmux(_ path: String, phrase: String = "") -> Bool {
		guard let folder = inWorkspace(path) else { return false }
		guard let cmux = NSWorkspace.shared.urlForApplication(withBundleIdentifier: cmuxBundle) else {
			toast("cmux is not installed here any more. Rebuilding the page without it.")
			freshen(force: true)
			return false
		}
		NSWorkspace.shared.open([folder], withApplicationAt: cmux, configuration: NSWorkspace.OpenConfiguration()) { _, error in
			DispatchQueue.main.async {
				guard error == nil else { return self.toast(self.notOpened("cmux", folder.lastPathComponent, phrase)) }
				self.copyText(phrase)
				self.toast(self.opened("cmux", folder.lastPathComponent, phrase), alsoNotify: false)
			}
		}
		return true
	}

	// MARK: the menu bar

	// Settings › Menu bar shows the app's own values: they are put in the page
	// before it runs, and again whenever one changes.
	func appState() -> [String: Any] {
		var login: Any = NSNull()             // null: this macOS cannot add a login item this way
		if #available(macOS 13, *) { login = SMAppService.mainApp.status == .enabled }
		return ["menubar": defaults.bool(forKey: kMenuBar), "style": savedEdge()?.rawValue ?? "icon", "login": login,
		        "hotkey": defaults.dictionary(forKey: kHotkey)?["label"] as? String ?? "",
		        "askhotkey": askSpec()?["label"] as? String ?? "",
		        "askdefault": defaults.object(forKey: kAskHotkey) == nil && askSpec() != nil, "said": keySaid,
		        "dictation": savedDictation().rawValue, "dictationkey": defaults.dictionary(forKey: kDictationKey)?["label"] as? String ?? ""]
	}

	func appJSON() -> String {
		(try? JSONSerialization.data(withJSONObject: appState())).flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
	}

	// Each installed app's icon as --icon-<key> on the page's root, with
	// .appicons, which the page reads as "draw the ways to open a note as
	// icons". The note's own is Obsidian's for an obsidian: link and the
	// Markdown app's otherwise. Made once.
	lazy var iconJSON: String = {
		var urls: [String: String] = [:]
		let bundles = ["obsidian": "md.obsidian", "finder": "com.apple.finder", "cmux": cmuxBundle, "codex": codexBundle, "claude": claudeBundle]
		for (key, id) in bundles {
			if let app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: id) { urls[key] = pngURL(NSWorkspace.shared.icon(forFile: app.path)) }
		}
		let md = URL(fileURLWithPath: workspace.path + "/AGENTS.md")
		urls["note"] = pngURL(NSWorkspace.shared.urlForApplication(toOpen: md).map { NSWorkspace.shared.icon(forFile: $0.path) }
			?? NSImage(systemSymbolName: "doc.text", accessibilityDescription: nil) ?? NSImage())
		return (try? JSONSerialization.data(withJSONObject: urls)).flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
	}()

	// GarrickReads tells the page this app answers a request that only reads, so
	// it may ask what is running (page_action.py's "operations"); GarrickReadsFiles,
	// that it answers how far a copy or a move has got (#189); GarrickReadsMemory,
	// that it counts what Settings › Memory would do (#108); GarrickReadsNotes,
	// that it reads a note for Explore's Preview (#206); and GarrickSaves,
	// that Save a copy opens its Save panel. An app without
	// it is never asked, and the page works as it did before the record. It is
	// set at document start, before the page's own scripts run.
	func appScript() -> WKUserScript {
		WKUserScript(source: """
			window.GarrickApp=\(appJSON());window.GarrickReads=true;window.GarrickReadsFiles=true;window.GarrickSaves=true;window.GarrickReadsMemory=true;window.GarrickReadsNotes=true;
			(function(i){var r=document.documentElement;r.classList.add('appicons');
			for(var k in i)r.style.setProperty('--icon-'+k,i[k])})(\(iconJSON));
			window.addEventListener('error',function(e){try{window.webkit.messageHandlers.garrick.postMessage({pageError:{line:e.lineno||0,
			col:e.colno||0,msg:String(e.message||'').replace(/(["'`]).*?\\1/g,'…').slice(0,160)}})}catch(x){}});
			""", injectionTime: .atDocumentStart, forMainFrameOnly: true)
	}

	func pushAppState() {
		web.configuration.userContentController.removeAllUserScripts()
		web.configuration.userContentController.addUserScript(appScript())
		web.evaluateJavaScript("window.GarrickAppSet&&window.GarrickAppSet(\(appJSON()))")
	}

	func setting(_ request: [String: Any]) {
		if let style = request["style"] as? String {
			defaults.set(PanelEdge(rawValue: style)?.rawValue ?? "icon", forKey: kStyle)
			if defaults.bool(forKey: kMenuBar) && menuState != nil {
				present()
				toast(whereItIs())
			}
		}
		if let on = request["menubar"] as? Bool {
			defaults.set(on, forKey: kMenuBar)
			if on && menuState != nil {
				present()
				toast(whereItIs())
			} else {
				takeAway()
				toast(on ? "Rebuilding the page for the menu." : "The menu is off. The window stays.")
				if on { freshen(force: true) }
			}
		}
		if let on = request["login"] as? Bool {
			if #available(macOS 13, *) {
				let service = SMAppService.mainApp
				do {
					if on { try service.register() } else { try service.unregister() }
					if service.status == .requiresApproval {
						toast("Allow Garrick in System Settings, under Login Items.")
						SMAppService.openSystemSettingsLoginItems()
					} else {
						toast(on ? "Garrick opens when you log in." : "Garrick no longer opens at login.")
					}
				} catch {
					toast("macOS did not change the login item: \(error.localizedDescription)")
				}
			}
		}
		// A hotkey field has the keys, so a key this app holds reaches it: ⌘G too.
		if let on = request["recording"] as? Bool, on != recording {
			recording = on
			applyHotKeys()
		}
		if let key = request["hotkey"] { setKey(kHotkey, "hotkey", key as? [String: Any]) }
		if let key = request["askhotkey"] { setKey(kAskHotkey, "askhotkey", key as? [String: Any]) }
		if let mode = request["dictation"] as? String { setDictation(Dictation(rawValue: mode) ?? .off) }
		if let key = request["dictationkey"] { setDictationKey(key as? [String: Any]) }
		pushAppState()
	}

	// The page sends the menu at every load and change; nil means the flag is
	// off, which takes the icon or the panel away and brings the window back if it was hidden.
	func setMenu(_ m: [String: Any]?) {
		menuState = m
		if let m, let data = try? JSONSerialization.data(withJSONObject: m) {
			defaults.set(data, forKey: kMenu)
		} else {
			defaults.removeObject(forKey: kMenu)
		}
		present()
		recording = false     // a page loaded again has no field with the keys
		applyHotKeys()        // the page is loaded again whenever it is rebuilt, so the flag is read often
	}

	// The icon or the panel, whichever Settings picks, or neither.
	func present() {
		guard menuState != nil, defaults.bool(forKey: kMenuBar) else { return takeAway() }
		if let edge = savedEdge() {
			removeStatusItem()
			if edgePanel?.edge != edge {
				edgePanel?.close()
				edgePanel = EdgePanel(edge) { [weak self] m in self?.fillPanel(m) }
			}
			edgePanel?.refresh()
		} else {
			edgePanel?.close()
			edgePanel = nil
			showStatusItem()
		}
	}

	func whereItIs() -> String {
		switch savedEdge() {
		case .left?: return "Rest the pointer at the left edge of the screen for Garrick's panel. Close the window and it stays there."
		case .right?: return "Rest the pointer at the right edge of the screen for Garrick's panel. Close the window and it stays there."
		case .top?: return "Rest the pointer on the notch, or the top of the screen, for Garrick's panel. Close the window and it stays there."
		case nil: return "Garrick is in the menu bar. Close the window and it stays there."
		}
	}

	func showStatusItem() {
		if statusItem == nil {
			let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
			let menu = NSMenu()
			menu.delegate = self
			item.menu = menu
			statusItem = item
		}
		let trouble = (menuState?["data"] as? [String: Any])?["trouble"] as? Bool == true
		let said = (trouble ? "Garrick: " + troubleSaid.lowercased() : "Garrick") + (held.isEmpty ? "" : ", keeping the Mac awake")
		statusItem?.button?.image = icon(trouble: trouble, awake: !held.isEmpty)
		statusItem?.button?.toolTip = said
		statusItem?.button?.setAccessibilityLabel(said)
	}

	func removeStatusItem() {
		guard let item = statusItem else { return }
		NSStatusBar.system.removeStatusItem(item)
		statusItem = nil
	}

	// Neither icon nor panel.
	func takeAway() {
		guard resident else { return }
		removeStatusItem()
		edgePanel?.close()
		edgePanel = nil
		setAwake(.off, remember: false)    // its controls live in the menu; never hold the Mac awake out of reach
		if !window.isVisible { showWindow() }  // never leave the app with nothing to click
	}

	// Garrick's mark, the small cut from status.py on its 64-unit grid: the
	// walls in the menu bar's own text colour, the open compartment in the
	// mark's blue for that ground, the Status tab's red dot at the top right,
	// and an amber dot at the bottom right while Keep awake holds the Mac.
	// Drawn at each draw, so it follows the menu bar from light to dark.
	func icon(trouble: Bool, awake: Bool = false) -> NSImage {
		NSImage(size: NSSize(width: 18, height: 18), flipped: true) { rect in
			let m = rect.insetBy(dx: 1, dy: 1), k = m.width / 64
			func box(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) -> NSBezierPath {
				NSBezierPath(rect: NSRect(x: m.minX + x * k, y: m.minY + y * k, width: w * k, height: h * k))
			}
			let dark = NSAppearance.currentDrawing().bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
			NSColor.labelColor.setFill()
			box(4, 4, 20, 56).fill()
			box(28, 32, 32, 28).fill()
			(dark ? NSColor(srgbRed: 0x8E / 255, green: 0xB1 / 255, blue: 0xF5 / 255, alpha: 1)
			      : NSColor(srgbRed: 0x3D / 255, green: 0x73 / 255, blue: 0xE0 / 255, alpha: 1)).setFill()
			box(28, 4, 32, 24).fill()
			if trouble {
				let dot = NSRect(x: rect.maxX - 7.5, y: rect.minY, width: 7.5, height: 7.5)
				NSColor.white.setFill(); NSBezierPath(ovalIn: dot).fill()
				NSColor.systemRed.setFill(); NSBezierPath(ovalIn: dot.insetBy(dx: 1, dy: 1)).fill()
			}
			if awake {
				let dot = NSRect(x: rect.maxX - 7.5, y: rect.maxY - 7.5, width: 7.5, height: 7.5)
				NSColor.white.setFill(); NSBezierPath(ovalIn: dot).fill()
				NSColor.systemOrange.setFill(); NSBezierPath(ovalIn: dot.insetBy(dx: 1, dy: 1)).fill()
			}
			return true
		}
	}

	// Filled as it opens, so it is always the page's latest; an old page is
	// rebuilt meanwhile, and the next opening shows the result.
	func menuNeedsUpdate(_ menu: NSMenu) {
		guard menu === statusItem?.menu else { return }   // a row's submenu is built with its row
		fill(menu)
		freshen()
	}

	// The field takes the keys as the menu opens, so typing finds at once. Its
	// window exists only once the menu is on screen, during its tracking.
	func menuWillOpen(_ menu: NSMenu) {
		guard menu === statusItem?.menu, let box = menuField else { return }
		RunLoop.main.perform(inModes: [.eventTracking, .default]) { box.window?.makeFirstResponder(box.field) }
	}

	// A view-backed row repaints only when told: the highlight moves here.
	func menu(_ menu: NSMenu, willHighlight item: NSMenuItem?) {
		menu.items.forEach { $0.view?.needsDisplay = true }
	}

	// The zone the graph shows. A wiki, a zone gone since, or the All a page
	// before #250 stored (*), falls back to Work, as the graph does, or to
	// every zone.
	func shownZones() -> [[String: Any]] {
		let zones = (menuState?["data"] as? [String: Any])?["zones"] as? [[String: Any]] ?? []
		let place = menuState?["place"] as? String ?? ""
		if let z = zones.first(where: { $0["z"] as? String == place }) { return [z] }
		if let z = zones.first(where: { $0["z"] as? String == "Work" }) { return [z] }
		return zones
	}

	// What a fill had to go on, left in the jobs folder as garrick-app-menu.json:
	// the menu or the panel, the style, the zones it held with a count of
	// projects each (-1: not a list the app can read), the zones shown, the
	// length of what the field held and the rows built; when the page last
	// sent its menu (a post comes just before the load it belongs to ends),
	// with rows or not, and its script errors since; and the menu saved for the
	// next launch. Zone names and counts only. A failure to write is no failure to fill.
	func reportMenu(_ place: String, query: String, rows: Int) {
		guard !checking else { return }
		let iso = ISO8601DateFormatter()
		let data = menuState?["data"] as? [String: Any]
		func zones(_ d: [String: Any]?) -> Any {
			guard let raw = d?["zones"] else { return NSNull() }
			guard let list = raw as? [[String: Any]] else { return "not a list of zones" }
			return list.map { ["z": $0["z"] as? String ?? "?", "projects": ($0["p"] as? [[String: Any]])?.count ?? -1] as [String: Any] }
		}
		let report: [String: Any] = [
			"time": iso.string(from: Date()), "launched": iso.string(from: launched), "filled": place,
			"style": savedEdge()?.rawValue ?? "icon", "menuBar": defaults.bool(forKey: kMenuBar),
			"menuState": menuState != nil, "keys": data.map { $0.keys.sorted() } ?? [],
			"zones": zones(data), "place": menuState?["place"] as? String ?? "",
			"shownZones": shownZones().map { $0["z"] as? String ?? "?" },
			"query": query.trimmingCharacters(in: .whitespacesAndNewlines).count, "rows": rows,
			"pagePost": menuHeard.map { ["time": iso.string(from: $0.at), "data": $0.data, "zones": $0.zones, "posts": $0.count] as [String: Any] } ?? NSNull(),
			"pageLoaded": pageLoaded.map { iso.string(from: $0) } ?? NSNull(),
			"pageErrors": pageErrors,
			"saved": zones(savedMenu()?["data"] as? [String: Any]),
		]
		guard JSONSerialization.isValidJSONObject(report),
		      let out = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]) else { return }
		try? FileManager.default.createDirectory(at: jobsDir, withIntermediateDirectories: true)
		try? out.write(to: menuReport, options: .atomic)
	}

	// A row's actions, as its card offers them: the note's own link, then each
	// app switched on in Settings that can open its folder. The one Settings
	// picks for clicking a thread is the default, and the note where it is not
	// on offer. Claude on a thread, where the page found Claude Code's
	// command-line tool (the menu's `cli`), carries the thread's note (`oc`),
	// which run() continues as the page's Open in Claude does (#180).
	func acts(_ r: [String: Any]) -> [[String: Any]] {
		var out: [[String: Any]] = []
		if menuState?["note"] as? Bool != false, let u = r["u"] as? String { out.append(["k": "note", "u": u]) }
		let cli = (menuState?["data"] as? [String: Any])?["cli"] as? Int == 1
		if let f = r["f"] as? String {
			for k in menuState?["launchers"] as? [String] ?? [] {
				var a: [String: Any] = ["k": k, "f": f, "w": r["w"] as? String ?? ""]
				if k == "cmux", let dk = r["dk"] { a["dk"] = dk }      // the cmux extra's desk opens it
				if k == "claude", cli, let oc = r["oc"] as? [String], oc.count == 2 { a["oc"] = oc; a["n"] = r["n"] as? String ?? "" }
				out.append(a)
			}
		}
		let picked = menuState?["def"] as? String ?? "note"
		let n = out.firstIndex(where: { $0["k"] as? String == picked }) ?? out.firstIndex(where: { $0["k"] as? String == "note" }) ?? 0
		if !out.isEmpty { out[n]["d"] = true }
		return out
	}

	// The menu: a field, Process the Inbox, then the shown zone's projects.
	// Hovering one opens its actions and its threads; hovering a thread opens
	// its actions. Clicking a project or a thread itself runs its default.
	func fill(_ menu: NSMenu) {
		menu.removeAllItems()
		let box = MenuField(canAsk() ? "Find a thread, or ask Garrick" : "Find a project or thread")
		box.changed = { [weak self, weak menu] text in if let self, let menu { self.fillRows(menu, text) } }
		box.submit = { [weak self, weak menu] text in self?.enter(text, closing: menu) }
		let field = NSMenuItem()
		field.view = box
		menu.addItem(field)
		menuField = box
		fillRows(menu, "")
	}

	// Everything under the field, again at each key typed in it. With words in
	// it, Ask Garrick comes first and the inbox goes; a thread found lists under
	// its project, as the panel lists it.
	func fillRows(_ menu: NSMenu, _ typed: String) {
		while menu.items.count > 1 { menu.removeItem(at: menu.items.count - 1) }
		let text = typed.trimmingCharacters(in: .whitespacesAndNewlines)
		if !text.isEmpty, let ask = askItem(text) {
			menu.addItem(ask)
		} else if text.isEmpty, let inbox = inboxItem() {
			menu.addItem(inbox)
		}
		menu.addItem(.separator())
		for (n, zone) in shownZones().enumerated() {
			if n > 0 { menu.addItem(.separator()) }
			menu.addItem(header(zone["z"] as? String ?? ""))
			let projects = found(zone["p"] as? [[String: Any]] ?? [], text)
			if projects.isEmpty {
				let none = NSMenuItem(title: text.isEmpty ? "No live projects" : "Nothing matches", action: nil, keyEquivalent: "")
				none.isEnabled = false
				menu.addItem(none)
			}
			for p in projects {
				menu.addItem(row(p))
				if !text.isEmpty { (p["t"] as? [[String: Any]] ?? []).forEach { menu.addItem(row($0, depth: 1)) } }
			}
		}
		reportMenu("menu", query: text, rows: menu.items.filter { $0.view is RowView }.count)
		menu.addItem(.separator())
		menu.addItem(awakeItem())
		let open = NSMenuItem(title: "Open Garrick", action: #selector(showWindow(_:)), keyEquivalent: "")
		show(open, mark(16))
		open.target = self
		menu.addItem(open)
		let settings = NSMenuItem(title: "Settings…", action: #selector(showSettings(_:)), keyEquivalent: "")
		show(settings, symbol("gearshape"))
		settings.target = self
		menu.addItem(settings)
		let quit = NSMenuItem(title: "Quit Garrick", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "")
		show(quit, symbol("power"))
		menu.addItem(quit)
	}

	func header(_ title: String) -> NSMenuItem {
		if #available(macOS 14, *) { return NSMenuItem.sectionHeader(title: title) }
		let i = NSMenuItem(title: title, action: nil, keyEquivalent: "")
		i.isEnabled = false
		return i
	}

	// A project or a thread: a row that runs its default when clicked, with a
	// submenu of its actions on one line and, for a project, its threads.
	func row(_ r: [String: Any], depth: Int = 0) -> NSMenuItem {
		let acts = acts(r)
		let fallback = acts.first(where: { $0["d"] as? Bool == true })
		let item = NSMenuItem(title: r["n"] as? String ?? "", action: nil, keyEquivalent: "")
		item.view = RowView(item.title, live: r["s"] as? String, depth: depth) { [weak self] in if let a = fallback { self?.run(a) } }
		let sub = NSMenu()
		sub.delegate = self
		if !acts.isEmpty {
			let bar = NSMenuItem()
			bar.view = ActionBar(acts.map { a in a.merging(["icon": icon(a), "l": label(a)]) { _, new in new } }) { [weak self] a in self?.run(a) }
			sub.addItem(bar)
		}
		let threads = r["t"] as? [[String: Any]] ?? []
		if !threads.isEmpty {
			sub.addItem(.separator())
			sub.addItem(header("Threads"))
			threads.forEach { sub.addItem(row($0)) }
		}
		item.submenu = sub
		return item
	}

	// Return in the menu's field: the first thread found, or the first project,
	// opens the default way, as the panel's Return does; with nothing found, it asks.
	func enter(_ typed: String, closing menu: NSMenu?) {
		let text = typed.trimmingCharacters(in: .whitespacesAndNewlines)
		guard !text.isEmpty else { return }
		let q = text.lowercased()
		let rows = shownZones().flatMap { found($0["p"] as? [[String: Any]] ?? [], text) }
		let thread = rows.flatMap { $0["t"] as? [[String: Any]] ?? [] }.first { ($0["n"] as? String ?? "").lowercased().contains(q) }
		let open = (thread ?? rows.first).flatMap { r in acts(r).first { $0["d"] as? Bool == true } }
		let go = { [weak self] in
			guard let self else { return }
			if let open { self.run(open) } else { self.askFrom(text) }
		}
		if checking { return go() }
		menu?.cancelTracking()
		DispatchQueue.main.async(execute: go)     // once the menu has gone, so what opens comes forward
	}

	// Whether a field can ask: Garrick itself with the preview ask on, else an assistant to open with the words.
	func canAsk() -> Bool { askOn() || assistant() != nil }

	// The Ask Garrick row, with the words typed: where they go, as the panel says it.
	func askItem(_ text: String) -> NSMenuItem? {
		let via: String
		if askOn() { via = ": Garrick answers" }
		else if let app = assistant() { via = " in " + label(["k": app]).replacingOccurrences(of: "Open in ", with: "") }
		else { return nil }
		let item = NSMenuItem(title: "Ask Garrick", action: #selector(askRow(_:)), keyEquivalent: "")
		item.target = self
		item.representedObject = text
		let said = NSMutableAttributedString(string: "Ask Garrick", attributes: [.font: NSFont.menuFont(ofSize: 0)])
		said.append(NSAttributedString(string: "  \u{201C}\(text)\u{201D}" + via,
		                               attributes: [.font: NSFont.menuFont(ofSize: 0), .foregroundColor: NSColor.secondaryLabelColor]))
		item.attributedTitle = said
		show(item, symbol("text.bubble"))
		return item
	}

	@objc func askRow(_ sender: NSMenuItem) {
		if let text = sender.representedObject as? String { askFrom(text) }
	}

	// A request from the menu's field. With the preview ask on, it goes to
	// the Ask box, which sends it to ask.py as the panel's field does and shows
	// the answer; off, the default assistant opens at the workspace root with
	// it, as from the panel.
	func askFrom(_ text: String) {
		if checking { return heard.append("menu:ask") }
		if askOn() {
			showAsk()
			askField.string = text
			askSubmit(askField)
		} else if let app = assistant() {
			launch(app, workspace.path, phrase: text)
		}
	}

	func label(_ a: [String: Any]) -> String {
		switch a["k"] as? String ?? "" {
		case "note": return (a["u"] as? String ?? "").hasPrefix("obsidian:") ? "Open in Obsidian" : "Open the note"
		case "finder": return "Reveal in Finder"
		case "cmux": return "Open in cmux"
		case "codex": return "Open in Codex"
		case "claude": return "Open in Claude"
		default: return ""
		}
	}

	// The icon of the app an action opens: for the note, the app macOS opens it in.
	func icon(_ a: [String: Any]) -> NSImage {
		let k = a["k"] as? String ?? ""
		let bundles = ["finder": "com.apple.finder", "cmux": cmuxBundle, "codex": codexBundle, "claude": claudeBundle]
		var app: URL?
		if k == "note", let u = a["u"] as? String, let url = URL(string: u) {
			app = NSWorkspace.shared.urlForApplication(toOpen: url)
		} else if let id = bundles[k] {
			app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: id)
		}
		if let app { return NSWorkspace.shared.icon(forFile: app.path) }
		return NSImage(systemSymbolName: "doc.text", accessibilityDescription: nil) ?? NSImage()
	}

	// An action: the note's link to macOS, or the folder to an app, as the
	// card's button opens it. Claude on a thread with its note (`oc`) is the
	// simple home's Continue (#180): page_action.py primes a session that
	// asks where the thread stands and opens the desktop app on its answer,
	// and its reply, or its refusal, is the toast that follows.
	func run(_ a: [String: Any]) {
		let k = a["k"] as? String ?? ""
		if checking { return heard.append("menu:" + k) }
		if k == "claude", let oc = a["oc"] as? [String], oc.count == 2 {
			let name = a["n"] as? String ?? "it"
			toast("Opening \(name) in Claude…", alsoNotify: false)
			act(["verb": "continue", "zone": oc[0], "file": oc[1]])
			return
		}
		if k == "note" {
			if let u = a["u"] as? String, let url = URL(string: u) { NSWorkspace.shared.open(url) }
		} else if let f = a["f"] as? String {
			let w = a["w"] as? String ?? ""
			launch(k, f, phrase: w.isEmpty ? "" : "open " + w, desk: a["dk"] != nil)
		}
	}

	// A row's icon, kept visible: macOS 27 hides menu item images unless the
	// item asks for them (preferredImageVisibility = .visible, 1). Set by name,
	// so the app still compiles with an SDK older than macOS 27's.
	func show(_ item: NSMenuItem, _ image: NSImage?) {
		item.image = image
		if item.responds(to: NSSelectorFromString("setPreferredImageVisibility:")) {
			item.setValue(1, forKey: "preferredImageVisibility")
		}
	}

	// A menu row's icon: an SF Symbol, drawn in the menu's own text colour.
	func symbol(_ name: String) -> NSImage? {
		NSImage(systemSymbolName: name, accessibilityDescription: nil)
	}

	// Garrick's mark at a menu row's size, as the menu bar draws it.
	func mark(_ side: CGFloat) -> NSImage {
		let image = icon(trouble: false)
		image.size = NSSize(width: side, height: side)
		return image
	}

	// MARK: process the inbox
	// One row for everything waiting: the intake skill reads each item and
	// decides whether it is a conversation, reading or project material. The
	// row opens the Settings default assistant (Claude, Codex or cmux; the
	// first of those switched on when the default is the note or Finder) at the
	// workspace root with "process the inbox", as a thread's row opens with
	// "open X": Claude gets it typed in, Codex on the clipboard, and cmux too
	// unless the desk is ready, when a tab at the root starts on it.
	// The assistant a phrase goes to: the default for clicking a thread when it
	// is Claude, Codex or cmux, else the first of those switched on.
	func assistant() -> String? {
		let on = menuState?["launchers"] as? [String] ?? []
		let assistants = ["claude", "codex", "cmux"].filter(on.contains)
		let picked = menuState?["def"] as? String ?? ""
		return assistants.contains(picked) ? picked : assistants.first
	}

	func inbox() -> (title: String, waiting: Int, act: [String: String], where: String)? {
		guard let row = (menuState?["data"] as? [String: Any])?["intake"] as? [String: Any],
		      let folder = row["f"] as? String, let phrase = row["w"] as? String, let app = assistant() else { return nil }
		// Where they wait, as "Meetings 1 · Work 4": a page built before it says only how many.
		let places = (row["b"] as? [[Any]] ?? []).compactMap { b -> String? in
			guard b.count == 2, let name = b[0] as? String, let n = b[1] as? Int else { return nil }
			return "\(name) \(n)"
		}
		return (row["n"] as? String ?? "Process the Inbox", row["c"] as? Int ?? 0, ["k": app, "f": folder, "w": phrase], places.joined(separator: " · "))
	}

	func inboxItem() -> NSMenuItem? {
		guard let row = inbox(), let app = row.act["k"], let phrase = row.act["w"] else { return nil }
		let title = row.title, n = row.waiting, act = row.act
		let item = NSMenuItem(title: title, action: #selector(processInbox(_:)), keyEquivalent: "")
		item.target = self
		item.representedObject = act
		let text = NSMutableAttributedString(string: title, attributes: [.font: NSFont.menuFont(ofSize: 0)])
		text.append(NSAttributedString(string: "  " + (n == 0 ? "empty" : "\(n) waiting"),
		                               attributes: [.font: NSFont.menuFont(ofSize: 0), .foregroundColor: NSColor.secondaryLabelColor]))
		item.attributedTitle = text
		show(item, symbol("tray.and.arrow.down"))
		item.toolTip = app == "cmux" && deskReady()
			? "Opens a cmux tab at the workspace root that starts on \u{201C}\(phrase)\u{201D}"
			: "Opens \(label(["k": app])) at the workspace root with \u{201C}\(phrase)\u{201D}"
		return item
	}

	@objc func processInbox(_ sender: NSMenuItem) {
		guard let r = sender.representedObject as? [String: String], let k = r["k"], let f = r["f"] else { return }
		if checking { return heard.append("menu:inbox") }
		launch(k, f, phrase: r["w"] ?? "")
	}

	// MARK: catch up (#27)
	// File › Catch Up… opens the page's own dialog, which picks the period and
	// the projects or threads. The menu and the panel leave it out (#226): a
	// row with nothing of its own to show takes a line from the rows that do.
	@objc func openCatchUp(_ sender: Any?) { web.evaluateJavaScript("window.GarrickCatchUp && window.GarrickCatchUp.open()") }

	// MARK: the panel
	// The menu's rows for the panel: the same zones, rows, actions and Keep
	// awake, each running as its menu item does.
	func fillPanel(_ m: PanelModel) {
		let trouble = (menuState?["data"] as? [String: Any])?["trouble"] as? Bool == true
		m.trouble = trouble
		m.mark = icon(trouble: trouble, awake: !held.isEmpty)
		m.zones = shownZones().map { z in PanelZone(name: z["z"] as? String ?? "", rows: (z["p"] as? [[String: Any]] ?? []).map(panelRow)) }
		reportMenu("panel", query: m.filter, rows: m.zones.reduce(0) { $0 + $1.rows.count })
		m.inbox = inbox().map { title, n, act, places in
			PanelInbox(title: title, note: n == 0 ? "empty" : "\(n) waiting", places: places) { [weak self] in
				guard let self, let k = act["k"], let f = act["f"] else { return }
				if checking { return self.heard.append("panel:inbox") }
				self.launch(k, f, phrase: act["w"] ?? "")
			}
		}
		m.awakeLabel = "Keep Awake" + awakeState()
		m.awakeHeld = !held.isEmpty
		switch awake {
		case .off: m.awakeTag = 0
		case .on: m.awakeTag = 3
		case .whileWorking: m.awakeTag = 4
		case .until: m.awakeTag = -1
		}
		m.display = defaults.bool(forKey: kAwakeDisplay)
		m.pickAwake = { [weak self] tag in self?.pickAwake(tag: tag) }
		m.openApp = { [weak self] in self?.showWindow() }
		m.openSettings = { [weak self] in self?.showSettings() }
		// A question typed in the panel's field. With the preview ask on, ask.py
		// answers it in the panel and acts on it. Off, the assistant opens at the
		// workspace root with it, as Process the Inbox opens with its phrase.
		if askOn() {
			m.askVia = "Garrick"
			m.answersHere = true
			m.ask = { [weak self, weak m] text in
				guard let self, let m else { return }
				if checking { return self.heard.append("panel:ask") }
				m.answering = true
				m.answer = ""
				self.askGarrick(text) { say, ranAway, _ in
					m.answering = false
					m.answer = say
					if ranAway { m.after() }    // an app came forward with what was asked for
				}
			}
		} else if let app = assistant() {
			m.askVia = label(["k": app]).replacingOccurrences(of: "Open in ", with: "")
			m.answersHere = false
			m.ask = { [weak self] text in
				guard let self else { return }
				if checking { return self.heard.append("panel:ask") }
				self.launch(app, workspace.path, phrase: text)
			}
		} else {
			m.askVia = ""
			m.answersHere = false
			m.ask = nil
		}
	}

	// MARK: ask (preview, ask)
	// The request goes to ask.py, which keeps a warm assistant session, checks
	// what it proposes and runs it through page_action.py. What comes back to
	// open, a project or a thread, opens here, as its row's icons open it, in
	// the app the request named or the default assistant. The reply is the
	// session's sentence and what was done; ranAway says an app came forward;
	// and the reply itself, with its kind. Progress comes before it, line by line.
	// An app the request named must be switched on in Settings, as on the page.
	@discardableResult
	func askGarrick(_ text: String, progress: @escaping (String) -> Void = { _ in },
	                done: @escaping (String, Bool, [String: Any]) -> Void) -> AskRequest? {
		askStream(["ask", "--", text], progress: progress) { [weak self] out in
			guard let self else { return }
			let say = out["say"] as? String ?? ""
			var lines = out["done"] as? [String] ?? []
			var ok = out["ok"] as? Bool ?? false
			var opened = false
			for item in out["launch"] as? [[String: Any]] ?? [] {
				guard let folder = item["folder"] as? String else { continue }
				let named = item["app"] as? String ?? ""
				guard let app = named.isEmpty ? self.assistant() : named else {
					self.toast("Switch on Claude, Codex or cmux in Settings to open threads from here.")
					continue
				}
				guard launcherOn(app) else {
					lines.append("Refused: \(app == "cmux" ? app : app.capitalized) is switched off in Settings")
					ok = false
					continue
				}
				if self.launch(app, folder, phrase: item["phrase"] as? String ?? "", desk: item["dk"] != nil) { opened = true }
			}
			if lines.count > lines.filter({ $0.hasPrefix("Opening ") }).count { self.freshen(force: true) }
			done(([say] + lines.map { "  " + $0 }).filter { !$0.isEmpty }.joined(separator: "\n"), opened && ok, out)
		}
	}

	// One window, made once and kept: the hotkey brings this one forward, with the cursor in its
	// field, and never makes a second. Compact, it is the field and the last reply; it grows for
	// an answer, a question back or a wall reset, and shows the whole exchange (#261).
	@objc func showAsk(_ sender: Any? = nil) {
		guard askOn() else { return }
		if askPanel == nil {
			let p = AskPanel(contentRect: NSRect(x: 0, y: 0, width: 620, height: 132),
			                 styleMask: [.titled, .closable, .fullSizeContentView, .nonactivatingPanel],
			                 backing: .buffered, defer: false)
			p.titleVisibility = .hidden
			p.titlebarAppearsTransparent = true
			p.isMovableByWindowBackground = true
			p.level = .floating
			p.hidesOnDeactivate = false
			p.isReleasedWhenClosed = false
			p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]

			askLog = NSTextView(frame: NSRect(x: 0, y: 0, width: 580, height: 320))
			askLog.isEditable = false
			askLog.isSelectable = true
			askLog.drawsBackground = false
			askLog.textContainerInset = NSSize(width: 0, height: 4)
			askLog.isVerticallyResizable = true
			askLog.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
			askLog.autoresizingMask = [.width]
			askLog.textContainer?.widthTracksTextView = true
			askLogBox = NSScrollView()
			askLogBox.documentView = askLog
			askLogBox.hasVerticalScroller = true
			askLogBox.drawsBackground = false
			askLogBox.borderType = .noBorder

			askField = AskInput(frame: NSRect(x: 0, y: 0, width: 580, height: 28))
			askField.placeholder = askHint
			askField.font = .systemFont(ofSize: 20)
			askField.isRichText = false
			askField.allowsUndo = true
			askField.drawsBackground = false
			askField.focusRingType = .none
			askField.textContainerInset = NSSize(width: 0, height: 2)
			askField.isVerticallyResizable = true
			askField.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
			askField.autoresizingMask = [.width]
			askField.textContainer?.widthTracksTextView = true
			askField.submit = { [weak self] in self?.askSubmit(nil) }
			askField.hide = { [weak self] in self?.askPanel?.orderOut(nil) }
			askField.changed = { [weak self] in self?.askFit() }
			let input = NSScrollView()
			input.documentView = askField
			input.drawsBackground = false
			input.borderType = .noBorder
			input.hasVerticalScroller = false
			askInputHeight = input.heightAnchor.constraint(equalToConstant: 28)

			askSpinner = NSProgressIndicator()
			askSpinner.style = .spinning
			askSpinner.controlSize = .small
			askSaid = NSTextField(labelWithString: "")
			askSaid.textColor = .secondaryLabelColor
			askSaid.font = .systemFont(ofSize: 13)
			askStopButton = NSButton(title: "Stop", target: self, action: #selector(askStop(_:)))
			askStopButton.controlSize = .small
			askStopButton.bezelStyle = .rounded
			askWorking = NSStackView(views: [askSpinner, askSaid, NSView(), askStopButton])
			askWorking.orientation = .horizontal
			askWorking.spacing = 8

			askReply = NSTextField(wrappingLabelWithString: "")
			askReply.textColor = .secondaryLabelColor
			askReply.font = .systemFont(ofSize: 13)
			askReply.isSelectable = true

			askNewButton = NSButton(title: "New conversation", target: self, action: #selector(askNew(_:)))
			askNewButton.controlSize = .small
			askNewButton.bezelStyle = .rounded
			askFoot = NSStackView(views: [NSView(), askNewButton])
			askFoot.orientation = .horizontal

			let stack = NSStackView(views: [askLogBox, input, askWorking, askReply, askFoot])
			stack.orientation = .vertical
			stack.alignment = .leading
			stack.spacing = 10
			stack.edgeInsets = NSEdgeInsets(top: 30, left: 20, bottom: 16, right: 20)
			stack.translatesAutoresizingMaskIntoConstraints = false
			let content = NSView()
			content.addSubview(stack)
			p.contentView = content
			NSLayoutConstraint.activate([
				stack.leadingAnchor.constraint(equalTo: content.leadingAnchor),
				stack.trailingAnchor.constraint(equalTo: content.trailingAnchor),
				stack.topAnchor.constraint(equalTo: content.topAnchor),
				stack.bottomAnchor.constraint(equalTo: content.bottomAnchor),
				content.widthAnchor.constraint(equalToConstant: 620),
				askLogBox.heightAnchor.constraint(equalToConstant: 320),
				askInputHeight,
			])
			for v in [askLogBox, input, askWorking, askReply, askFoot] as [NSView] {
				v.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -40).isActive = true
			}
			askPanel = p
			askRender()
		}
		guard let p = askPanel else { return }
		let opening = !(p.isVisible && p.isKeyWindow)   // pressed again on an open box, it starts nothing a second time
		if !p.isVisible, let screen = NSScreen.main?.visibleFrame {
			p.setFrameOrigin(NSPoint(x: screen.midX - p.frame.width / 2, y: screen.maxY - screen.height / 4 - p.frame.height))
		}
		p.makeKeyAndOrderFront(nil)
		p.makeFirstResponder(askField)
		askWarm()                       // the session starts while the request is typed
		if opening { startDictation() }
	}

	// Preparing: the session may be starting. Said only when it takes a moment, so a warm
	// session never makes the window flicker; a request sent meanwhile waits for it once.
	func askWarm() {
		askPreparing = true
		askCall(["warm"]) { [weak self] _ in
			self?.askPreparing = false
			self?.askRender()
		}
		DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { [weak self] in self?.askRender() }
	}

	// MARK: dictation (preview ask)
	// Started once the box has opened with the cursor in its field, so the words
	// land there, and only then: a second press of the Ask hotkey on an open box
	// would stop a tool that toggles. macOS Dictation starts through the action
	// behind Edit › Start Dictation, which needs nothing; another tool through its
	// own key, posted where the keyboard's own events come in, which needs the
	// Accessibility permission. Stopping it is the tool's, as is where it pastes:
	// a tool that pastes with ⌘V reaches the field through Edit › Paste.
	func startDictation() {
		let mode = savedDictation()
		guard mode != .off else { return }
		if checking { return heard.append("dictation:" + mode.rawValue) }
		if mode != .macos && !AXIsProcessTrusted() {
			return toast("Garrick cannot press your dictation key: allow it in System Settings › Privacy & Security › Accessibility.")
		}
		DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { [weak self] in
			guard self?.askPanel?.isKeyWindow == true else { return }   // closed meanwhile: the words would go elsewhere
			switch mode {
			case .macos: NSApp.sendAction(Selector(("startDictation:")), to: NSApp, from: nil)
			case .fn: tapFn()
			case .fn2: tapFn(); DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { tapFn() }
			case .key: if let spec = defaults.dictionary(forKey: kDictationKey) { press(spec) }
			case .off: break
			}
		}
	}

	// A choice from Settings: kept, and for a key, the permission asked for at
	// once, so macOS's prompt comes while you are looking at the setting.
	func setDictation(_ mode: Dictation) {
		defaults.set(mode.rawValue, forKey: kDictation)
		keySaid["dictation"] = nil
		switch mode {
		case .off: toast("The Ask box starts no dictation.")
		case .macos: toast("The Ask box starts macOS Dictation when it opens.")
		case .fn, .fn2, .key:
			let trusted = AXIsProcessTrustedWithOptions(["AXTrustedCheckOptionPrompt": true] as CFDictionary)
			if !trusted { keySaid["dictation"] = "Allow Garrick in System Settings › Privacy & Security › Accessibility, so it can press the key." }
			toast(keySaid["dictation"] ?? "The Ask box presses your dictation key when it opens.")
		}
	}

	// A key the Ask hotkey or the menu's would answer is refused: pressed, it would open the box again or the menu.
	func setDictationKey(_ spec: [String: Any]?) {
		let label = spec?["label"] as? String ?? "That"
		if let spec, sameKey(spec, askSpec()) || sameKey(spec, defaults.dictionary(forKey: kHotkey)) {
			keySaid["dictationkey"] = "\(label) is already a hotkey of Garrick's. Pick your dictation tool's key."
			return toast(keySaid["dictationkey"]!)
		}
		keySaid["dictationkey"] = nil
		if let spec { defaults.set(spec, forKey: kDictationKey) } else { defaults.removeObject(forKey: kDictationKey) }
		toast(spec == nil ? "No dictation key." : "The Ask box presses \(label) when it opens.")
	}

	// An answer, a question back or a refusal stays in the window to be read or
	// answered; when an app came forward with what was asked for, the window hides.
	// Either way the exchange is kept. One request at a time: Return while one runs does nothing.
	@objc func askSubmit(_ sender: Any? = nil) {
		let text = askField.string.trimmingCharacters(in: .whitespacesAndNewlines)
		guard !text.isEmpty, askRunning == nil else { return }
		askField.string = ""
		askTurns.append(AskTurn(request: text))
		let at = askTurns.count - 1
		askRunning = askGarrick(text, progress: { [weak self] said in self?.askProgress(said) }) { [weak self] reply, ranAway, out in
			guard let self else { return }
			self.askRunning = nil
			guard at < self.askTurns.count else { return self.askRender() }
			var turn = self.askTurns[at]
			turn.running = false
			turn.reply = reply.isEmpty ? "No answer." : reply
			turn.kind = out["kind"] as? String ?? "command"
			turn.stopped = out["stopped"] as? Bool == true
			turn.failed = out["failed"] as? Bool == true
			turn.afresh = out["reset"] as? String == "wall"
			self.askTurns[at] = turn
			if turn.kind != "command" || turn.afresh { self.askExpanded = true }
			// Stopped: nothing was done, so the question goes back in the field, to be sent again or changed.
			if turn.stopped && self.askField.string.isEmpty { self.askField.string = text }
			self.askRender()
			if ranAway { self.askPanel?.orderOut(nil) }
		}
		askRender()
	}

	// Finding an answer: the window grows to show what is being done, with Stop.
	func askProgress(_ said: String) {
		guard askRunning != nil else { return }
		askExpanded = true
		askRender()
		askSaid.stringValue = said
	}

	@objc func askStop(_ sender: Any?) {
		askRunning?.stop()
		askSaid.stringValue = "Stopping…"
		askStopButton.isEnabled = false
	}

	// New conversation: the exchange goes, and so does the session's context (`reset`). The only
	// place, with quit, that clears it. Not while a request runs: Stop it first.
	@objc func askNew(_ sender: Any?) {
		guard askRunning == nil else { return }
		askTurns.removeAll()
		askExpanded = false
		askField.string = ""
		askCall(["reset"]) { _ in }
		askRender()
		askPanel?.makeFirstResponder(askField)
	}

	// Each state the window can be in, from the exchange and the request on its way: Ready,
	// Preparing, Command, Finding an answer, Answer, Clarification, Stopped or failed.
	func askRender() {
		guard askPanel != nil else { return }
		let last = askTurns.last
		let running = askRunning != nil
		askLogBox.isHidden = !askExpanded
		if askExpanded {
			askLog.textStorage?.setAttributedString(askTranscript())
			askLog.scrollToEndOfDocument(nil)
		}
		let preparing = askPreparing && !running
		askWorking.isHidden = !running && !preparing
		askStopButton.isHidden = !running
		askStopButton.isEnabled = askRunning?.stopped != true
		if running {
			if askRunning?.stopped == true {
				askSaid.stringValue = "Stopping…"
			} else if askSaid.stringValue.isEmpty || askSaid.stringValue == "Preparing the assistant…" {
				askSaid.stringValue = askPreparing ? "Waiting for the assistant to start…" : "Working…"
			}
			askSpinner.startAnimation(nil)
		} else if preparing {
			askSaid.stringValue = "Preparing the assistant…"
			askSpinner.startAnimation(nil)
		} else {
			askSaid.stringValue = ""
			askSpinner.stopAnimation(nil)
		}
		// Compact: the last request stands in the empty field, and its reply under it.
		let reply = !askExpanded && !running ? last?.reply ?? "" : ""
		askReply.stringValue = reply
		askReply.isHidden = reply.isEmpty
		askReply.textColor = last?.failed == true || last?.stopped == true ? .systemOrange : .secondaryLabelColor
		askField.placeholder = askExpanded ? askHint : last?.request ?? askHint
		askFoot.isHidden = askTurns.isEmpty
		askNewButton.isEnabled = !running
		askFit()
	}

	// The exchange as the expanded window shows it: each request, then what came back; a
	// stop or a failure said as such; a wall reset as a divider above the turn it came with.
	func askTranscript() -> NSAttributedString {
		let out = NSMutableAttributedString()
		let asked: [NSAttributedString.Key: Any] = [.font: NSFont.boldSystemFont(ofSize: 13), .foregroundColor: NSColor.labelColor]
		let said: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 13), .foregroundColor: NSColor.labelColor]
		var aside: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 12), .foregroundColor: NSColor.secondaryLabelColor]
		for (i, turn) in askTurns.enumerated() {
			if turn.afresh && i > 0 {
				let centred = NSMutableParagraphStyle()
				centred.alignment = .center
				aside[.paragraphStyle] = centred
				out.append(NSAttributedString(string: askAfresh + "\n\n", attributes: aside))
				aside[.paragraphStyle] = nil
			}
			out.append(NSAttributedString(string: turn.request + "\n", attributes: asked))
			if turn.running {
				out.append(NSAttributedString(string: "…\n\n", attributes: aside))
				continue
			}
			var reply = said
			if turn.stopped || turn.failed { reply[.foregroundColor] = NSColor.systemOrange }
			out.append(NSAttributedString(string: turn.reply + "\n\n", attributes: reply))
		}
		return out
	}

	// The field grows with what is typed, up to five lines; the window keeps its top edge where it is.
	func askFit() {
		guard let p = askPanel, let content = p.contentView, let lm = askField.layoutManager, let tc = askField.textContainer else { return }
		lm.ensureLayout(for: tc)
		let line = lm.defaultLineHeight(for: askField.font ?? .systemFont(ofSize: 20))
		let used = max(lm.usedRect(for: tc).height, line)
		askInputHeight.constant = ceil(min(used, line * 5) + askField.textContainerInset.height * 2)
		content.layoutSubtreeIfNeeded()
		let size = content.fittingSize
		guard size.height > 0, size != content.frame.size else { return }
		let top = p.frame.maxY
		p.setContentSize(size)
		p.setFrameTopLeftPoint(NSPoint(x: p.frame.minX, y: top))
	}

	// File › Ask Garrick… is there only with the preview on.
	func validateMenuItem(_ item: NSMenuItem) -> Bool {
		if item.action == #selector(showAsk(_:)) {
			item.isHidden = !askOn()
			return !item.isHidden
		}
		return true
	}

	func panelRow(_ r: [String: Any]) -> PanelRow {
		let acts = acts(r)
		let fallback = acts.first(where: { $0["d"] as? Bool == true })
		let name = r["n"] as? String ?? ""
		// Its folder and name: what the panel remembers it unfolded by, so a line break, which a plist keeps.
		return PanelRow(id: (r["f"] as? String ?? r["u"] as? String ?? "") + "\n" + name, name: name,
		                acts: acts.enumerated().map { n, a in
		                	PanelAct(id: n, icon: icon(a), label: label(a), isDefault: a["d"] as? Bool == true) { [weak self] in self?.run(a) }
		                },
		                threads: (r["t"] as? [[String: Any]] ?? []).map(panelRow),
		                open: fallback.map { a in { [weak self] in self?.run(a) } }, live: r["s"] as? String)
	}

	// MARK: keep awake
	// macOS's own power assertions, as caffeinate takes them, held by this
	// process: macOS drops them when the app quits or crashes, so nothing is
	// left keeping the Mac awake. System sleep only, unless *Display stays on
	// too*. A closed lid without an external display still sleeps: only root
	// can stop that (pmset disablesleep), and this does not try.

	func setAwake(_ mode: Awake, remember: Bool = true) {
		awake = mode
		if remember { defaults.set(mode == .whileWorking, forKey: kAwakeWorking) }
		agentsBusy = nil
		awakeTimer?.invalidate()
		awakeTimer = mode == .off ? nil : Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.awakeTick() }
		awakeTick()
	}

	// Once a minute while a mode is on: end a timed one that has run out, or ask
	// agents_working.py whether an assistant is mid-turn.
	func awakeTick() {
		switch awake {
		case .off: hold(false)
		case .on: hold(true)
		case .until(let end): if end.timeIntervalSinceNow <= 0 { setAwake(.off) } else { hold(true) }
		case .whileWorking:
			let p = Process()
			p.executableURL = URL(fileURLWithPath: python)
			p.arguments = [agentsCheck.path]
			p.standardOutput = FileHandle.nullDevice
			p.standardError = FileHandle.nullDevice
			p.terminationHandler = { proc in
				DispatchQueue.main.async {
					guard self.awake == .whileWorking else { return }
					let status = proc.terminationStatus
					self.agentsBusy = status == 0 ? true : status == 1 ? false : nil
					self.hold(status == 0)
				}
			}
			do { try p.run() } catch { agentsBusy = nil; hold(false) }
		}
	}

	func hold(_ on: Bool) {
		var wanted: [String] = []
		if on {
			wanted.append(kIOPMAssertionTypePreventUserIdleSystemSleep as String)
			if defaults.bool(forKey: kAwakeDisplay) { wanted.append(kIOPMAssertionTypePreventUserIdleDisplaySleep as String) }
		}
		let was = !held.isEmpty
		for (type, id) in held where !wanted.contains(type) {
			IOPMAssertionRelease(id)
			held[type] = nil
		}
		for type in wanted where held[type] == nil {
			var id = IOPMAssertionID(0)
			if IOPMAssertionCreateWithName(type as CFString, IOPMAssertionLevel(kIOPMAssertionLevelOn),
			                               "Garrick: Keep awake" as CFString, &id) == kIOReturnSuccess { held[type] = id }
		}
		if was != !held.isEmpty && statusItem != nil { showStatusItem() }
		if was != !held.isEmpty { edgePanel?.refresh() }
	}

	// The menu's Keep awake row: its title says the state, its submenu the choices.
	func awakeItem() -> NSMenuItem {
		let item = NSMenuItem(title: "Keep Awake" + awakeState(), action: nil, keyEquivalent: "")
		show(item, symbol(held.isEmpty ? "cup.and.saucer" : "cup.and.saucer.fill"))
		let sub = NSMenu()
		func choice(_ title: String, _ tag: Int, _ on: Bool) {
			let i = NSMenuItem(title: title, action: #selector(pickAwake(_:)), keyEquivalent: "")
			i.target = self
			i.tag = tag
			i.state = on ? .on : .off
			sub.addItem(i)
		}
		choice("Off", 0, awake == .off)
		choice("For 1 Hour", 1, false)
		choice("For 3 Hours", 2, false)
		choice("Until Turned Off", 3, awake == .on)
		choice("While an Agent Is Working", 4, awake == .whileWorking)
		sub.addItem(.separator())
		choice("Display Stays On Too", 5, defaults.bool(forKey: kAwakeDisplay))
		item.submenu = sub
		return item
	}

	func awakeState() -> String {
		switch awake {
		case .off: return ""
		case .on: return " · On"
		case .until(let end):
			let m = max(1, Int(ceil(end.timeIntervalSinceNow / 60)))
			return " · " + (m >= 60 ? "\(m / 60) h \(m % 60) min" : "\(m) min") + " left"
		case .whileWorking:
			switch agentsBusy {
			case true?: return " · An Agent Is Working"
			case false?: return " · No Agent Working"
			case nil: return held.isEmpty ? " · Checking Agents" : " · Agents Unseen"
			}
		}
	}

	@objc func pickAwake(_ sender: NSMenuItem) { pickAwake(tag: sender.tag) }

	func pickAwake(tag: Int) {
		defer { edgePanel?.refresh() }
		switch tag {
		case 1: setAwake(.until(Date().addingTimeInterval(3600)))
		case 2: setAwake(.until(Date().addingTimeInterval(3 * 3600)))
		case 3: setAwake(.on)
		case 4: setAwake(.whileWorking)
		case 5:
			defaults.set(!defaults.bool(forKey: kAwakeDisplay), forKey: kAwakeDisplay)
			awakeTick()
		default: setAwake(.off)
		}
	}

	// System-wide shortcuts through Carbon's hot keys, which need no
	// Accessibility permission: the menu's (Settings › Hotkey), which opens the
	// menu, or the window when the icon is off, and the Ask box's (Settings ›
	// Ask hotkey) while the preview ask is on. Never the same key: Settings
	// refuses that, and ⌘G, the Ask box's until you choose, gives way to a
	// menu hotkey set to ⌘G. Both let go while a field in Settings records a
	// key, so the field gets it. Held globally, a key no longer reaches other
	// apps, which is why the Ask box's goes with the preview.
	func register(_ spec: [String: Any], _ n: UInt32, _ ref: inout EventHotKeyRef?) -> OSStatus {
		guard let code = spec["code"] as? String, let vk = keyCodes[code] else { return OSStatus(paramErr) }
		var mods: UInt32 = 0
		for m in spec["mods"] as? [String] ?? [] {
			switch m {
			case "cmd": mods |= UInt32(cmdKey)
			case "alt": mods |= UInt32(optionKey)
			case "ctrl": mods |= UInt32(controlKey)
			case "shift": mods |= UInt32(shiftKey)
			default: break
			}
		}
		listenForHotKeys()
		let id = EventHotKeyID(signature: OSType(0x4752_4B53), id: n)   // 'GRKS'
		return RegisterEventHotKey(UInt32(vk), mods, id, GetApplicationEventTarget(), 0, &ref)
	}

	// Whether macOS would let this app take the key now: taken and let go at once.
	func available(_ spec: [String: Any]) -> OSStatus {
		var ref: EventHotKeyRef?
		let status = register(spec, 9, &ref)
		if let ref { UnregisterEventHotKey(ref) }
		return status
	}

	func applyHotKeys() {
		if let old = hotKey { UnregisterEventHotKey(old); hotKey = nil }
		keySpec = nil
		if !recording && !checking, let spec = defaults.dictionary(forKey: kHotkey), spec["code"] != nil,
		   register(spec, 1, &hotKey) == noErr {
			keySpec = spec
		}
		syncAskKey()
	}

	// A key from a field in Settings: saved and taken, or refused, with why
	// said under the field and in the toast.
	func setKey(_ store: String, _ field: String, _ spec: [String: Any]?) {
		let menu = store == kHotkey
		let other = menu ? (defaults.dictionary(forKey: kAskHotkey).flatMap { $0["code"] == nil ? nil : $0 }) : defaults.dictionary(forKey: kHotkey)
		let label = spec?["label"] as? String ?? "That"
		var refusal: String?
		if let spec {
			if sameKey(spec, other) {
				refusal = "\(label) is already the \(menu ? "Ask" : "menu's") hotkey. Clear it there, or pick another."
			} else {
				let status = available(spec)
				if status == OSStatus(eventHotKeyExistsErr) {
					refusal = "Another app already uses \(label). Try another."
				} else if status != noErr {
					refusal = "macOS does not let an app take \(label). Use ⌘ or ⌃ with the key."
				}
			}
		}
		if let refusal {
			keySaid[field] = refusal
			toast(refusal)
			return
		}
		keySaid[field] = nil
		let gaveWay = menu && sameKey(spec, askDefault) && defaults.object(forKey: kAskHotkey) == nil
		defaults.set(spec ?? [:], forKey: store)          // an empty key: none, which for the Ask box is not ⌘G
		if menu && spec == nil { defaults.removeObject(forKey: kHotkey) }
		applyHotKeys()
		if menu {
			toast(spec == nil ? "No hotkey for the menu." : "\(label) opens the menu from any app."
			      + (gaveWay ? " The Ask box has no hotkey now; set one under Ask hotkey." : ""))
		} else {
			toast(spec == nil ? "No hotkey for the Ask box." : "\(label) opens the Ask box from any app" + (askOn() ? "." : ", with the preview ask on."))
		}
	}

	// One handler for both hot keys; the key's id says which was pressed.
	func listenForHotKeys() {
		guard hotKeyHandler == nil else { return }
		var pressed = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
		InstallEventHandler(GetApplicationEventTarget(), { _, event, _ in
			var key = EventHotKeyID()
			GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil,
			                  MemoryLayout<EventHotKeyID>.size, nil, &key)
			let which = key.id
			DispatchQueue.main.async { (NSApp.delegate as? StatusApp)?.hotKeyPressed(which) }
			return noErr
		}, 1, &pressed, nil, &hotKeyHandler)
	}

	// The Ask box's key, held from any app while the preview ask is on, as
	// File › Ask Garrick… shows it with the window in front. Checked at launch
	// and at every load of the page, so switching the preview needs no restart.
	// A key another app already holds this way is left to it.
	func syncAskKey() {
		let wanted = askOn() && !checking && !recording ? askSpec() : nil
		let (key, mods) = keyEquivalent(recording ? nil : askSpec())
		askMenuItem?.keyEquivalent = key
		askMenuItem?.keyEquivalentModifierMask = mods
		if sameKey(wanted, askKeySpec) && (askKey != nil) == (wanted != nil) { return }
		if let ask = askKey { UnregisterEventHotKey(ask); askKey = nil }
		askKeySpec = nil
		guard let wanted else { return }
		if register(wanted, 2, &askKey) == noErr { askKeySpec = wanted } else { askKey = nil }
	}

	// The Ask hotkey opens the Ask box. The hotkey opens the panel with the cursor in its
	// field, or the icon's menu with the cursor in its own: both find and ask.
	func hotKeyPressed(_ which: UInt32) {
		if which == 2 { return showAsk() }     // the one window, brought forward with the exchange it holds
		if let panel = edgePanel {
			if askOn() && !panel.shown { askCall(["warm"]) { _ in } }
			panel.toggle()
		} else if let button = statusItem?.button {
			if askOn() { askCall(["warm"]) { _ in } }
			button.performClick(nil)
		} else { showWindow() }
	}

	// MARK: links

	func webView(_ webView: WKWebView, decidePolicyFor nav: WKNavigationAction,
	             decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
		guard let url = nav.request.url else { return decisionHandler(.cancel) }
		if url.isFileURL && url.standardizedFileURL.path == page.standardizedFileURL.path {
			return decisionHandler(.allow)
		}
		decisionHandler(.cancel)
		if checking { return heard.append("link:" + (url.scheme ?? "")) }
		if openJobLog(url) { return }
		NSWorkspace.shared.open(url)
	}

	// A job's log, from its panel's Open log (#273), opens in the app this Mac
	// uses for plain text, TextEdit failing that, not in Console, which .log
	// goes to by default and which shows its own system log first. Only a .log
	// in the jobs folder; any other file opens as before.
	func openJobLog(_ url: URL) -> Bool {
		guard url.isFileURL, url.pathExtension == "log",
		      url.resolvingSymlinksInPath().deletingLastPathComponent().path == jobsDir.resolvingSymlinksInPath().path,
		      let app = NSWorkspace.shared.urlForApplication(toOpen: UTType.plainText)
		          ?? NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.TextEdit") else { return false }
		NSWorkspace.shared.open([url], withApplicationAt: app, configuration: NSWorkspace.OpenConfiguration())
		return true
	}

	// target=_blank and window.open land here; nothing opens a second window.
	func webView(_ webView: WKWebView, createWebViewWith config: WKWebViewConfiguration,
	             for nav: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
		if let url = nav.request.url, !checking { NSWorkspace.shared.open(url) }
		return nil
	}

	// A crashed or reclaimed web process leaves a blank view; read the file again.
	func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { load() }

	// The stored key alternates, so a second --check shows whether the first
	// one's write survived the quit.
	func webView(_ webView: WKWebView, didFinish nav: WKNavigation!) {
		guard checking else {
			pageLoaded = Date()
			if let asked = settingsAsked {
				settingsAsked = nil
				if -asked.timeIntervalSinceNow < 60 { openSettings(nil) }
			}
			return
		}
		web.evaluateJavaScript("""
			(function(){var k='garrick-app-check',p=null;
			try{p=localStorage.getItem(k);if(p)localStorage.removeItem(k);else localStorage.setItem(k,String(Date.now()))}catch(e){p='error: '+e}
			var row=document.querySelector('[data-card]');if(row&&window.Panel){var d=document.createElement('div');
			d.innerHTML=Panel.acts(JSON.parse(row.dataset.card));document.body.appendChild(d);
			[].forEach.call(d.querySelectorAll('button'),function(b){b.click()});d.remove()}
			var a=document.createElement('a');a.href='obsidian://check';document.body.appendChild(a);a.click();a.remove();
			var rb=document.getElementById('rebuild');
			return JSON.stringify({title:document.title,host:!!(window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick),
			rebuild:rb?rb.title:null,stored:p,
			cmux:[].filter.call(document.querySelectorAll('[data-card]'),function(r){return JSON.parse(r.dataset.card).f}).length})})()
			""") { result, error in
			DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
				print(result as? String ?? "error: \(String(describing: error))")
				// What a normal launch shows first, before the page answers: the menu as last saved.
				let saved = (savedMenu()?["data"] as? [String: Any])?["zones"] as? [[String: Any]] ?? []
				print("saved menu: " + (saved.isEmpty ? "none" : saved.map { "\($0["z"] as? String ?? "?") \(($0["p"] as? [[String: Any]] ?? []).count)" }
				      .joined(separator: ", ") + ", showing \(savedMenu()?["place"] as? String ?? "")"))
				// The menu bar's menu, filled from what the page sent, and its first thread pressed.
				if self.menuState != nil {
					let m = NSMenu()
					self.fill(m)
					let rows = m.items.compactMap { $0.view as? RowView }
					let threads = m.items.flatMap { $0.submenu?.items ?? [] }.filter { $0.view is RowView }.count
					print("menu: \(rows.count) projects, \(threads) threads in \(self.shownZones().count) zone(s)"
					      + (m.items.first?.view is MenuField ? ", under its field" : ", no field"))
					if let inbox = m.items.first(where: { $0.action == #selector(self.processInbox(_:)) }) {
						print("inbox: \(inbox.attributedTitle?.string ?? inbox.title), via \((inbox.representedObject as? [String: String])?["k"] ?? "?")")
					} else {
						print("inbox: none")
					}
					// The field: a thread's name finds it and Return opens it; words that find nothing ask.
					let first = self.shownZones().flatMap { $0["p"] as? [[String: Any]] ?? [] }
						.flatMap { $0["t"] as? [[String: Any]] ?? [] }.first?["n"] as? String
					if let first {
						self.fillRows(m, first)
						print("menu, finding \(first.count) letters: \(m.items.filter { $0.view is RowView }.count) rows"
						      + (m.items.contains { $0.action == #selector(self.askRow(_:)) } ? ", Ask Garrick first" : ""))
						self.enter(first, closing: nil)
					}
					self.enter("\u{2042} nothing has this name", closing: nil)
					let panel = PanelModel()
					self.fillPanel(panel)
					let projects = panel.zones.flatMap { $0.rows }
					print("panel: \(projects.count) projects, \(projects.reduce(0) { $0 + $1.threads.count }) threads, "
					      + "\(projects.filter { panel.unfolded.contains($0.id) }.count) unfolded")
					rows.first?.click()
					projects.first?.open?()
					panel.ask?("what's open")
				} else {
					print("menu: none")
				}
				self.startDictation()      // what the Ask box would start, heard rather than pressed
				print("heard: \(self.heard)")
				print("page errors: \(self.pageErrors.count)" + self.pageErrors.map { " line \($0["line"] ?? "?"): \($0["msg"] ?? "")" }.joined(separator: ";"))
				exit(0)
			}
		}
	}

	// MARK: menu

	@objc func reloadPage(_ sender: Any?) { reload() }
	@objc func rebuildPage(_ sender: Any?) { freshen(force: true) }
	@objc func openSettings(_ sender: Any?) { web.evaluateJavaScript("window.StatusSettings && window.StatusSettings.open()") }
	@objc func openInBrowser(_ sender: Any?) { NSWorkspace.shared.open(page) }
	@objc func actualSize(_ sender: Any?) { web.pageZoom = 1 }
	@objc func zoomIn(_ sender: Any?) { web.pageZoom = min(web.pageZoom + 0.1, 3) }
	@objc func zoomOut(_ sender: Any?) { web.pageZoom = max(web.pageZoom - 0.1, 0.5) }

	func menu() -> NSMenu {
		let bar = NSMenu()
		func sub(_ title: String, _ items: [NSMenuItem]) {
			let m = NSMenu(title: title)
			items.forEach(m.addItem)
			let top = NSMenuItem(title: title, action: nil, keyEquivalent: "")
			top.submenu = m
			bar.addItem(top)
		}
		func item(_ title: String, _ sel: Selector?, _ key: String, _ mods: NSEvent.ModifierFlags = .command) -> NSMenuItem {
			let i = NSMenuItem(title: title, action: sel, keyEquivalent: key)
			i.keyEquivalentModifierMask = mods
			return i
		}
		sub("Garrick", [
			item("About Garrick", #selector(NSApplication.orderFrontStandardAboutPanel(_:)), ""),
			item("Settings…", #selector(openSettings(_:)), ","),
			.separator(),
			item("Hide Garrick", #selector(NSApplication.hide(_:)), "h"),
			item("Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
			item("Show All", #selector(NSApplication.unhideAllApplications(_:)), ""),
			.separator(),
			item("Quit Garrick", #selector(NSApplication.terminate(_:)), "q"),
		])
		let ask = item("Ask Garrick…", #selector(showAsk(_:)), "g")   // the key Settings › Ask hotkey sets, from syncAskKey()
		askMenuItem = ask
		sub("File", [
			ask,
			item("Catch Up…", #selector(openCatchUp(_:)), ""),     // the page's Catch up, period and threads (#27)
			item("Open in Browser", #selector(openInBrowser(_:)), "o"),
			.separator(),
			item("Close Window", #selector(NSWindow.performClose(_:)), "w"),
		])
		// The standard actions, so ⌘V and the rest reach a text field: the page's
		// own (adding a Todo line, the panel's filter) and the Ask box. AppKit
		// sends each to whatever has the keyboard.
		sub("Edit", [
			item("Undo", Selector(("undo:")), "z"),
			item("Redo", Selector(("redo:")), "z", [.command, .shift]),
			.separator(),
			item("Cut", #selector(NSText.cut(_:)), "x"),
			item("Copy", #selector(NSText.copy(_:)), "c"),
			item("Paste", #selector(NSText.paste(_:)), "v"),
			item("Select All", #selector(NSText.selectAll(_:)), "a"),
		])
		sub("View", [
			item("Reload", #selector(reloadPage(_:)), "r"),
			item("Rebuild", #selector(rebuildPage(_:)), "r", [.command, .shift]),
			.separator(),
			item("Actual Size", #selector(actualSize(_:)), "0"),
			item("Zoom In", #selector(zoomIn(_:)), "+"),
			item("Zoom Out", #selector(zoomOut(_:)), "-"),
			.separator(),
			item("Enter Full Screen", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control]),
		])
		sub("Window", [
			item("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m"),
			item("Zoom", #selector(NSWindow.performZoom(_:)), ""),
		])
		return bar
	}
}

// Fn as the keyboard sends it: not a key going down and up, but the Fn flag set
// on key code 63 and cleared 80 ms later. Posted at the HID tap, so a tool that
// watches the keyboard sees it as it sees the real key.
func tapFn() {
	func flags(_ down: Bool) {
		guard let e = CGEvent(keyboardEventSource: CGEventSource(stateID: .hidSystemState), virtualKey: 63, keyDown: down) else { return }
		e.type = .flagsChanged
		e.flags = down ? .maskSecondaryFn : []
		e.post(tap: .cghidEventTap)
	}
	flags(true)
	DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) { flags(false) }
}

// A recorded shortcut, pressed and let go with its modifiers held, at the same tap.
func press(_ spec: [String: Any]) {
	guard let code = spec["code"] as? String, let vk = keyCodes[code] else { return }
	var mods: CGEventFlags = []
	for m in spec["mods"] as? [String] ?? [] {
		switch m {
		case "cmd": mods.insert(.maskCommand)
		case "alt": mods.insert(.maskAlternate)
		case "ctrl": mods.insert(.maskControl)
		case "shift": mods.insert(.maskShift)
		default: break
		}
	}
	let source = CGEventSource(stateID: .hidSystemState)
	for down in [true, false] {
		guard let e = CGEvent(keyboardEventSource: source, virtualKey: CGKeyCode(vk), keyDown: down) else { return }
		e.flags = mods
		e.post(tap: .cghidEventTap)
	}
}

// MARK: the panel
// The menu as a panel that slides out from the left or right edge of the
// screen, or down from under the notch. It holds the same rows as the menu and
// runs them the same way; StatusApp.fillPanel fills it from the page's menu.
// It opens when the pointer rests at its edge for a moment, or with the
// hotkey, and never takes the app forward: the app you were in stays in
// front. Seeing the pointer needs no permission; only keys would.

struct PanelAct: Identifiable {
	let id: Int
	let icon: NSImage
	let label: String
	let isDefault: Bool
	let run: () -> Void
}

struct PanelRow: Identifiable {
	let id: String
	let name: String
	let acts: [PanelAct]
	let threads: [PanelRow]
	let open: (() -> Void)?
	var live: String? = nil
}

struct PanelZone: Identifiable {
	var id: String { name }
	let name: String
	let rows: [PanelRow]
}

struct PanelInbox {
	let title: String
	let note: String
	let places: String
	let run: () -> Void
}

final class PanelModel: ObservableObject {
	@Published var zones: [PanelZone] = []
	@Published var inbox: PanelInbox?
	@Published var trouble = false
	@Published var mark = NSImage()
	@Published var awakeLabel = "Keep Awake"
	@Published var awakeHeld = false
	@Published var awakeTag = 0
	@Published var display = false
	@Published var filter = ""
	@Published var inset = NSEdgeInsets()    // room for the curves that meet the screen's edge, and for the notch
	@Published var typing = 0                // bumped when the hotkey opens it, to put the cursor in the filter
	var pickAwake: (Int) -> Void = { _ in }
	var openApp: () -> Void = {}
	var openSettings: () -> Void = {}
	var ask: ((String) -> Void)?
	@Published var askVia = ""               // the assistant a question opens in, by name
	@Published var answersHere = false       // preview ask: the panel answers, and stays
	@Published var answering = false
	@Published var answer = ""
	var after: () -> Void = {}
	// Close first, then act, so the app that opens comes forward over a panel already leaving.
	func perform(_ f: @escaping () -> Void) { after(); f() }
	// The projects whose threads show. A project starts folded; the ones you
	// unfold are kept in the app's defaults, so the panel opens as you left it,
	// after a restart too.
	@Published var unfolded = Set(defaults.stringArray(forKey: kPanelOpen) ?? [])
	var resized: () -> Void = {}
	func fold(_ id: String) {
		if unfolded.contains(id) { unfolded.remove(id) } else { unfolded.insert(id) }
		defaults.set(unfolded.sorted(), forKey: kPanelOpen)
		resized()
	}
}

// One project or thread: its name runs the default, a chevron folds a
// project's threads, and pointing at it shows the icons of its other apps.
struct PanelLine: View {
	let row: PanelRow
	let depth: Int
	let folded: Bool?
	let toggle: () -> Void
	let perform: (@escaping () -> Void) -> Void
	@State private var hover = false

	var body: some View {
		HStack(spacing: 6) {
			if let folded {
				Button(action: toggle) {
					Image(systemName: folded ? "chevron.right" : "chevron.down")
						.font(.system(size: 9, weight: .semibold))
						.foregroundColor(.secondary)
						.frame(width: 12, height: 16)
						.contentShape(Rectangle())
				}
				.buttonStyle(.plain)
			} else {
				Color.clear.frame(width: 12, height: 16)
			}
			Text(row.name)
				.font(.system(size: 13, weight: depth == 0 ? .medium : .regular))
				.foregroundColor(depth == 0 ? .primary : .primary.opacity(0.85))
				.lineLimit(1)
				.truncationMode(.tail)
			// After the name, so every name starts at the same place, open or not.
			if let live = row.live {
				Circle().fill(Color(liveColor(live))).frame(width: 6, height: 6)
					.help(live == "working" ? "A session is open in it, working" : "A session is open in it")
			}
			Spacer(minLength: 8)
			if hover {
				HStack(spacing: 4) {
					ForEach(row.acts) { a in
						Button { perform(a.run) } label: {
							Image(nsImage: a.icon).resizable().frame(width: 18, height: 18)
								.padding(2)
								.background(RoundedRectangle(cornerRadius: 5).fill(a.isDefault ? Color.accentColor.opacity(0.3) : .clear))
						}
						.buttonStyle(.plain)
						.help(a.label)
					}
				}
			}
		}
		.padding(.leading, CGFloat(depth) * 18)
		.padding(.horizontal, 8)
		.padding(.vertical, 4)
		.background(RoundedRectangle(cornerRadius: 6).fill(hover ? Color.primary.opacity(0.09) : .clear))
		.contentShape(Rectangle())
		.onHover { hover = $0 }
		.onTapGesture { if let open = row.open { perform(open) } }
	}
}

struct PanelView: View {
	@ObservedObject var model: PanelModel
	@FocusState private var typing: Bool

	var query: String { model.filter.trimmingCharacters(in: .whitespaces).lowercased() }

	// Filtered: a project whose name matches keeps all its threads; otherwise only the threads that match.
	func shown(_ rows: [PanelRow]) -> [PanelRow] {
		guard !query.isEmpty else { return rows }
		return rows.compactMap { r in
			if r.name.lowercased().contains(query) { return r }
			let t = r.threads.filter { $0.name.lowercased().contains(query) }
			return t.isEmpty ? nil : PanelRow(id: r.id, name: r.name, acts: r.acts, threads: t, open: r.open, live: r.live)
		}
	}

	// Return opens the first thread that matches, or the first project; with
	// nothing matching, it asks.
	func first() -> (() -> Void)? {
		let rows = model.zones.flatMap { shown($0.rows) }
		if !query.isEmpty, let t = rows.flatMap({ $0.threads }).first(where: { $0.name.lowercased().contains(query) }) { return t.open }
		if let open = rows.first?.open { return open }
		return nil
	}

	// Asking closes the panel when the assistant opens elsewhere; answered
	// here (preview ask), it stays, with the field emptied for a follow-up.
	func submitAsk(_ ask: @escaping () -> Void) {
		if model.answersHere {
			ask()
			model.filter = ""
		} else {
			model.perform(ask)
		}
	}

	func asking() -> (() -> Void)? {
		let text = model.filter.trimmingCharacters(in: .whitespacesAndNewlines)
		guard !text.isEmpty, let ask = model.ask else { return nil }
		return { ask(text) }
	}

	func awake(_ title: String, _ tag: Int, _ on: Bool) -> some View {
		Toggle(title, isOn: Binding(get: { on }, set: { _ in model.pickAwake(tag) }))
	}

	var body: some View {
		VStack(alignment: .leading, spacing: 8) {
			HStack(spacing: 8) {
				// Trouble is the red dot on the mark, as in the menu bar; said in its tooltip and label.
				Image(nsImage: model.mark).resizable().frame(width: 16, height: 16)
					.help(model.trouble ? troubleSaid : "Garrick")
					.accessibilityLabel(model.trouble ? "Garrick: " + troubleSaid.lowercased() : "Garrick")
				Text("Garrick").font(.system(size: 13, weight: .semibold))
				Spacer()
			}
			HStack(spacing: 6) {
				Image(systemName: "magnifyingglass").font(.system(size: 11)).foregroundColor(.secondary)
				TextField(model.ask == nil ? "Find a project or thread" : "Find a thread, or ask Garrick", text: $model.filter)
					.textFieldStyle(.plain)
					.font(.system(size: 12))
					.focused($typing)
					.onSubmit {
						if let open = first() { model.perform(open) } else if let ask = asking() { submitAsk(ask) }
					}
			}
			.padding(.horizontal, 10)
			.padding(.vertical, 6)
			.background(Capsule().fill(Color.primary.opacity(0.08)))
			if model.answering || !model.answer.isEmpty {
				Text(model.answering ? "…" : model.answer)
					.font(.system(size: 12))
					.foregroundColor(.secondary)
					.textSelection(.enabled)
					.fixedSize(horizontal: false, vertical: true)
					.padding(.horizontal, 8)
			}
			ScrollView {
				VStack(alignment: .leading, spacing: 1) {
					if let ask = asking() {
						HStack(alignment: .firstTextBaseline, spacing: 6) {
							Image(systemName: "text.bubble").frame(width: 12)
							VStack(alignment: .leading, spacing: 2) {
								Text("Ask Garrick").font(.system(size: 13, weight: .medium))
								Text(model.answersHere ? "\u{201C}\(model.filter.trimmingCharacters(in: .whitespacesAndNewlines))\u{201D}: Garrick answers here"
								     : "\u{201C}\(model.filter.trimmingCharacters(in: .whitespacesAndNewlines))\u{201D} in \(model.askVia)")
									.font(.system(size: 11)).foregroundColor(.secondary).lineLimit(2)
							}
							Spacer()
						}
						.padding(.horizontal, 8).padding(.vertical, 5)
						.background(RoundedRectangle(cornerRadius: 6).fill(Color.accentColor.opacity(0.12)))
						.contentShape(Rectangle())
						.onTapGesture { submitAsk(ask) }
						Divider().padding(.vertical, 4)
					}
					if let inbox = model.inbox, query.isEmpty {
						HStack(alignment: .firstTextBaseline, spacing: 6) {
							Image(systemName: "tray.and.arrow.down").frame(width: 12)
							VStack(alignment: .leading, spacing: 2) {
								HStack(spacing: 6) {
									Text(inbox.title).font(.system(size: 13, weight: .medium))
									Text(inbox.note).font(.system(size: 12)).foregroundColor(.secondary)
								}
								if !inbox.places.isEmpty {
									Text(inbox.places).font(.system(size: 11)).foregroundColor(.secondary)
								}
							}
							Spacer()
						}
						.padding(.horizontal, 8).padding(.vertical, 5)
						.contentShape(Rectangle())
						.onTapGesture { model.perform(inbox.run) }
						Divider().padding(.vertical, 4)
					}
					ForEach(model.zones) { zone in
						Text(zone.name.uppercased())
							.font(.system(size: 10, weight: .semibold))
							.foregroundColor(.secondary)
							.padding(.horizontal, 8).padding(.top, 6).padding(.bottom, 2)
						let rows = shown(zone.rows)
						if rows.isEmpty {
							Text(query.isEmpty ? "No live projects" : "Nothing matches")
								.font(.system(size: 12)).foregroundColor(.secondary).padding(.horizontal, 8)
						}
						ForEach(rows) { r in
							let shut = query.isEmpty && !model.unfolded.contains(r.id)     // a search shows every thread it finds
							PanelLine(row: r, depth: 0, folded: r.threads.isEmpty ? nil : shut,
							          toggle: { model.fold(r.id) }, perform: model.perform)
							if !shut {
								ForEach(r.threads) { t in
									PanelLine(row: t, depth: 1, folded: nil, toggle: {}, perform: model.perform)
								}
							}
						}
					}
				}
			}
			Divider()
			HStack(spacing: 12) {
				// Beside the menu, not in its label: a macOS menu button draws only the label's text.
				Image(systemName: model.awakeHeld ? "cup.and.saucer.fill" : "cup.and.saucer")
					.font(.system(size: 12))
					.foregroundColor(model.awakeHeld ? .orange : .secondary)
					.padding(.trailing, -7)
				Menu {
					awake("Off", 0, model.awakeTag == 0)
					awake("For 1 Hour", 1, false)
					awake("For 3 Hours", 2, false)
					awake("Until Turned Off", 3, model.awakeTag == 3)
					awake("While an Agent Is Working", 4, model.awakeTag == 4)
					Divider()
					awake("Display Stays On Too", 5, model.display)
				} label: {
					Text(model.awakeLabel).font(.system(size: 12))
				}
				.menuStyle(.borderlessButton)
				.fixedSize()
				Spacer()
				Button { model.perform(model.openApp) } label: {
					Image(nsImage: model.mark).resizable().frame(width: 15, height: 15)
				}
				.help("Open Garrick")
				Button { model.perform(model.openSettings) } label: { Image(systemName: "gearshape") }
					.help("Settings")
				Button { NSApp.terminate(nil) } label: { Image(systemName: "power") }
					.help("Quit Garrick")
			}
			.buttonStyle(.plain)
		}
		.padding(12)
		.padding(.top, model.inset.top)
		.padding(.leading, model.inset.left)
		.padding(.bottom, model.inset.bottom)
		.padding(.trailing, model.inset.right)
		.onReceive(model.$typing.dropFirst()) { _ in typing = true }
	}
}

// The panel's outline. It is flush with the screen edge it comes out of and
// meets that edge in two concave curves, as the notch meets the top of the
// screen, with round corners on the side facing in. The top one is black,
// like the notch; the side ones are the frosted material of a popover.
final class EdgeShape: NSView {
	static let ear: CGFloat = 16, corner: CGFloat = 22
	let edge: PanelEdge
	let effect: NSVisualEffectView?

	init(_ edge: PanelEdge) {
		self.edge = edge
		if edge == .top {
			effect = nil
		} else {
			let v = NSVisualEffectView()
			v.material = .popover
			v.blendingMode = .behindWindow
			v.state = .active
			effect = v
		}
		super.init(frame: .zero)
		if let effect { addSubview(effect) }
	}
	required init?(coder: NSCoder) { nil }

	// Drawn as if it hung from the top of the screen, w along the edge and
	// h away from it, then turned to the edge it belongs to.
	func outline(_ size: NSSize) -> NSBezierPath {
		let along = edge == .top ? size.width : size.height, depth = edge == .top ? size.height : size.width
		let e = min(EdgeShape.ear, depth / 2, along / 4)
		let c = max(0, min(EdgeShape.corner, depth - e, (along - 2 * e) / 2))
		let w = along, h = depth
		let p = NSBezierPath()
		p.move(to: NSPoint(x: 0, y: h))
		p.appendArc(withCenter: NSPoint(x: 0, y: h - e), radius: e, startAngle: 90, endAngle: 0, clockwise: true)
		p.line(to: NSPoint(x: e, y: c))
		p.appendArc(withCenter: NSPoint(x: e + c, y: c), radius: c, startAngle: 180, endAngle: 270, clockwise: false)
		p.line(to: NSPoint(x: w - e - c, y: 0))
		p.appendArc(withCenter: NSPoint(x: w - e - c, y: c), radius: c, startAngle: 270, endAngle: 360, clockwise: false)
		p.line(to: NSPoint(x: w - e, y: h - e))
		p.appendArc(withCenter: NSPoint(x: w, y: h - e), radius: e, startAngle: 180, endAngle: 90, clockwise: true)
		p.close()
		let t = NSAffineTransform()
		switch edge {
		case .top: break
		case .right: t.transformStruct = NSAffineTransformStruct(m11: 0, m12: 1, m21: 1, m22: 0, tX: 0, tY: 0)        // its top on the right
		case .left: t.transformStruct = NSAffineTransformStruct(m11: 0, m12: 1, m21: -1, m22: 0, tX: depth, tY: 0)   // its top on the left
		}
		p.transform(using: t as AffineTransform)
		return p
	}

	override func setFrameSize(_ size: NSSize) {
		super.setFrameSize(size)
		if let effect {
			effect.frame = bounds
			effect.maskImage = NSImage(size: size, flipped: false) { [weak self] _ in
				NSColor.black.setFill()
				self?.outline(size).fill()
				return true
			}
		}
		needsDisplay = true
	}

	override func draw(_ dirty: NSRect) {
		guard effect == nil else { return }
		NSColor.black.setFill()
		outline(bounds.size).fill()
	}
}

// A borderless panel that can take the keys for the filter without bringing the app forward.
final class SlidePanel: NSPanel {
	override var canBecomeKey: Bool { true }
	override var canBecomeMain: Bool { false }
}

final class EdgePanel: NSObject, NSWindowDelegate {
	let edge: PanelEdge
	let model = PanelModel()
	let panel: SlidePanel
	let clip: EdgeShape
	let host: NSHostingView<PanelView>
	let fill: (PanelModel) -> Void
	let width: CGFloat = 290
	var monitors: [Any] = []
	var dwell: DispatchWorkItem?
	var watch: Timer?
	var away: Date?            // when the pointer left the open panel
	var shut = NSRect.zero     // where it slides back to
	var shown = false, byKey = false

	init(_ edge: PanelEdge, fill: @escaping (PanelModel) -> Void) {
		self.edge = edge
		self.fill = fill
		panel = SlidePanel(contentRect: NSRect(x: 0, y: 0, width: 340, height: 400),
		                   styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: true)
		panel.level = .statusBar               // over the menu bar, so the top one grows out of the notch
		panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
		panel.isOpaque = false
		panel.backgroundColor = .clear
		panel.hasShadow = true
		panel.hidesOnDeactivate = false
		panel.isReleasedWhenClosed = false
		panel.isFloatingPanel = true
		panel.acceptsMouseMovedEvents = true
		clip = EdgeShape(edge)
		if edge == .top { panel.appearance = NSAppearance(named: .darkAqua) }   // white on the notch's black
		host = NSHostingView(rootView: PanelView(model: model))
		if #available(macOS 13, *) { host.sizingOptions = [] }   // the panel sizes itself; the content follows
		// Pinned to the side it slides from, so a narrower panel shows its inner edge first.
		switch edge {
		case .left: host.autoresizingMask = [.minXMargin]
		case .right: host.autoresizingMask = [.maxXMargin]
		case .top: host.autoresizingMask = [.maxYMargin, .minXMargin, .maxXMargin]
		}
		super.init()
		clip.autoresizingMask = [.width, .height]
		clip.addSubview(host)
		panel.contentView = clip
		panel.delegate = self
		model.after = { [weak self] in self?.close(animated: true) }
		model.resized = { [weak self] in self?.relayout() }
		arm()
	}

	// The notch, where the screen has one: the gap between the two parts of the menu bar beside it.
	func notch(_ s: NSScreen) -> NSRect? {
		guard #available(macOS 12, *), s.safeAreaInsets.top > 0,
		      let l = s.auxiliaryTopLeftArea, let r = s.auxiliaryTopRightArea, r.minX > l.maxX else { return nil }
		return NSRect(x: l.maxX, y: s.frame.maxY - s.safeAreaInsets.top, width: r.minX - l.maxX, height: s.safeAreaInsets.top)
	}

	// As tall as what it lists, up to most of the screen: a guess from the
	// rows, since a scrolling list has no height of its own. Only an unfolded
	// project's threads count.
	func contentHeight() -> CGFloat {
		let rows = model.zones.reduce(0) { n, z in
			n + max(1, z.rows.count) + z.rows.reduce(0) { $0 + (model.unfolded.contains($1.id) ? $1.threads.count : 0) }
		}
		return 24 + 36 + (model.inbox == nil ? 0 : 52) + CGFloat(model.zones.count) * 24 + CGFloat(rows) * 25 + 44 + 24
	}

	// Where it rests open on a screen, where it slides from, and the room its curves and the notch take.
	func frames(_ s: NSScreen) -> (open: NSRect, shut: NSRect, inset: NSEdgeInsets) {
		let f = s.frame, v = s.visibleFrame, e = EdgeShape.ear
		switch edge {
		case .left, .right:
			let h = min(contentHeight() + 2 * e, v.height - 16)
			let y = max(v.minY + 8, v.maxY - 8 - h)   // hung from the top, over the third of the edge that opens it
			let x = edge == .left ? f.minX : f.maxX - width
			let r = NSRect(x: x, y: y, width: width, height: h)
			let from = NSRect(x: edge == .left ? f.minX : f.maxX - 1, y: y, width: 1, height: h)
			return (r, from, NSEdgeInsets(top: e, left: edge == .left ? 0 : 4, bottom: e, right: edge == .right ? 0 : 4))
		case .top:
			let n = notch(s)
			let lid = n?.height ?? 0
			let h = min(contentHeight(), v.height * 0.75) + lid
			let w = max(width + 80, (n?.width ?? 0) + 80) + 2 * e
			let mid = n?.midX ?? f.midX
			let top = n == nil ? v.maxY : f.maxY
			let r = NSRect(x: mid - w / 2, y: top - h, width: w, height: h)
			// Out of the notch itself where there is one, so it seems to grow from it.
			let from = n.map { NSRect(x: $0.minX - e, y: $0.minY, width: $0.width + 2 * e, height: $0.height) }
				?? NSRect(x: r.minX, y: r.maxY - 1, width: r.width, height: 1)
			return (r, from, NSEdgeInsets(top: lid, left: e, bottom: 4, right: e))
		}
	}

	// The pointer at the panel's edge: an outer edge of the screen, not one
	// that leads to another display. On a side, only its top third, which
	// leaves the rest of the edge to other apps that live there; for the
	// top, only across the notch (or the middle of the menu bar on a screen
	// without one), where the menu bar has no items.
	func atEdge(_ p: NSPoint) -> Bool {
		guard let s = NSScreen.screens.first(where: { NSMouseInRect(p, $0.frame, false) }) else { return false }
		let f = s.frame
		func outer(_ q: NSPoint) -> Bool { !NSScreen.screens.contains { NSMouseInRect(q, $0.frame, false) } }
		switch edge {
		case .left: return p.x <= f.minX + 1 && topThird(p, s) && outer(NSPoint(x: f.minX - 2, y: p.y))
		case .right: return p.x >= f.maxX - 2 && topThird(p, s) && outer(NSPoint(x: f.maxX + 2, y: p.y))
		case .top:
			guard p.y >= f.maxY - 2, outer(NSPoint(x: p.x, y: f.maxY + 2)) else { return false }
			let n = notch(s) ?? NSRect(x: f.midX - 100, y: f.maxY, width: 200, height: 0)
			return p.x >= n.minX && p.x <= n.maxX
		}
	}

	// The pointer, from wherever it is: other apps' events for the edge, this
	// app's own when its window is in front. Escape closes it, and a click in
	// another app does too.
	func arm() {
		if let m = NSEvent.addGlobalMonitorForEvents(matching: [.mouseMoved, .leftMouseDragged], handler: { [weak self] _ in self?.moved() }) { monitors.append(m) }
		if let m = NSEvent.addLocalMonitorForEvents(matching: [.mouseMoved], handler: { [weak self] e in self?.moved(); return e }) { monitors.append(m) }
		if let m = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown], handler: { [weak self] _ in self?.close(animated: true) }) { monitors.append(m) }
		if let m = NSEvent.addLocalMonitorForEvents(matching: [.keyDown], handler: { [weak self] e in
			guard let self, self.shown, e.keyCode == 53 else { return e }   // Escape
			self.close(animated: true)
			return nil
		}) { monitors.append(m) }
	}

	func topThird(_ p: NSPoint, _ s: NSScreen) -> Bool {
		let v = s.visibleFrame
		return p.y < v.maxY && p.y >= v.maxY - v.height / 3
	}

	// Resting at the edge for a quarter of a second opens it, so passing by does not.
	func moved() {
		guard !shown else { return }
		if atEdge(NSEvent.mouseLocation) {
			guard dwell == nil else { return }
			let work = DispatchWorkItem { [weak self] in
				guard let self else { return }
				self.dwell = nil
				if !self.shown && self.atEdge(NSEvent.mouseLocation) { self.open(byKey: false) }
			}
			dwell = work
			DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: work)
		} else {
			dwell?.cancel()
			dwell = nil
		}
	}

	func refresh() { fill(model) }

	// A project folded or unfolded while open: the panel takes the height its list now needs.
	func relayout() {
		guard shown, let s = panel.screen ?? NSScreen.main else { return }
		let (to, from, _) = frames(s)
		shut = from
		panel.setFrame(to, display: true)
		host.frame = clip.bounds
		panel.invalidateShadow()
	}

	func toggle() { if shown { close(animated: true) } else { open(byKey: true) } }

	func open(byKey: Bool) {
		fill(model)
		let p = NSEvent.mouseLocation
		guard let s = NSScreen.screens.first(where: { NSMouseInRect(p, $0.frame, false) }) ?? NSScreen.main else { return }
		let (to, from, inset) = frames(s)
		model.inset = inset
		// Laid out open, then shrunk to where it slides from, so the content keeps its place.
		panel.setFrame(to, display: false)
		host.frame = clip.bounds
		panel.setFrame(from, display: false)
		shut = from
		shown = true
		self.byKey = byKey
		away = nil
		panel.orderFrontRegardless()
		if byKey {
			panel.makeKey()
			model.typing += 1
		}
		NSAnimationContext.runAnimationGroup { c in
			c.duration = 0.2
			c.timingFunction = CAMediaTimingFunction(name: .easeOut)
			panel.animator().setFrame(to, display: true)
		} completionHandler: { [weak self] in self?.panel.invalidateShadow() }
		if !byKey {
			watch = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in self?.stillHere() }
		}
	}

	// Opened by the pointer, it closes when the pointer has been away a moment.
	func stillHere() {
		let p = NSEvent.mouseLocation
		if panel.frame.insetBy(dx: -16, dy: -16).contains(p) || atEdge(p) || panel.isKeyWindow {
			away = nil
		} else if let a = away {
			if -a.timeIntervalSinceNow > 0.35 { close(animated: true) }
		} else {
			away = Date()
		}
	}

	func windowDidResignKey(_ note: Notification) { if shown { close(animated: true) } }

	func close(animated: Bool = false) {
		watch?.invalidate()
		watch = nil
		guard shown || !animated else { return }
		if !animated {
			monitors.forEach(NSEvent.removeMonitor)
			monitors = []
			dwell?.cancel()
			shown = false
			panel.orderOut(nil)
			return
		}
		shown = false
		model.filter = ""
		model.answer = ""
		NSAnimationContext.runAnimationGroup { c in
			c.duration = 0.15
			c.timingFunction = CAMediaTimingFunction(name: .easeIn)
			panel.animator().setFrame(shut, display: true)
		} completionHandler: { [weak self] in
			guard let self, !self.shown else { return }
			self.panel.orderOut(nil)
		}
	}
}

let app = NSApplication.shared
let delegate = StatusApp()
app.delegate = delegate
// Regular from the start, as Info.plist launches it: made an accessory here and a
// regular app again a moment later, a launch from the Finder or the Dock showed the
// Dock icon, took it away and brought it back before the window. A login launch that
// stays out of sight turns accessory in applicationDidFinishLaunching, the first point
// it can tell a login launch from yours.
app.setActivationPolicy(checking ? .prohibited : .regular)
app.run()

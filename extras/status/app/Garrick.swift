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
//   - with the preview menu-bar on, an icon in the menu bar listing the live
//     threads of the zone the graph shows, each opening a session, with a red
//     dot when the Status tab has one, and Keep awake: for a time, until
//     turned off, or while an assistant is working (agents_working.py). Settings › Menu bar switches it on,
//     opens the app at login and sets a hotkey for the menu; the app keeps
//     those three in its own defaults, as it keeps the menu between launches;
//   - instead of the icon, the same menu as a panel that slides out from the
//     left or right edge of the screen, or down from under the notch, when the
//     pointer rests there or the hotkey is pressed (Settings › Menu bar › Shows as).
// Nothing here changes a file in the workspace, as nothing on the page does.
import AppKit
import Carbon.HIToolbox
import IOKit.pwr_mgt
import ServiceManagement
import SwiftUI
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
let maxAge: TimeInterval = 30 * 60
// --check loads the page out of sight, acts on nothing, prints what it found
// and quits: the test that the page loads, sees the app and is answered.
let checking = CommandLine.arguments.contains("--check")

// What the app keeps between launches, in its own defaults: the three menu bar
// settings, the menu as the page last gave it, and whether the window was open.
let defaults = UserDefaults.standard
let kMenuBar = "menuBar", kHotkey = "hotkey", kMenu = "menu", kWindowShown = "windowShown"
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
func savedMenu() -> [String: Any]? {
	defaults.data(forKey: kMenu).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
}
// Left in the menu bar with the window closed, it starts that way again.
let startHidden = !checking && defaults.bool(forKey: kMenuBar) && savedMenu() != nil
	&& defaults.object(forKey: kWindowShown) as? Bool == false

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

func modified(_ url: URL) -> Date? {
	(try? FileManager.default.attributesOfItem(atPath: url.path))?[.modificationDate] as? Date
}

// A menu row that is both a button and a submenu: AppKit gives a plain item
// with a submenu no action, so the row is a view that draws itself, runs its
// default on a click and leaves the hover to open its submenu.
final class RowView: NSView {
	let title: String
	let click: () -> Void
	init(_ title: String, click: @escaping () -> Void) {
		self.title = title
		self.click = click
		let width = (title as NSString).size(withAttributes: [.font: NSFont.menuFont(ofSize: 0)]).width
		super.init(frame: NSRect(x: 0, y: 0, width: max(200, ceil(width) + 60), height: 22))
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
		(title as NSString).draw(at: NSPoint(x: 21, y: (bounds.height - h) / 2), withAttributes: attrs)
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

final class StatusApp: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
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
	var hotKey: EventHotKeyRef?
	var hotKeyHandler: EventHandlerRef?
	var hourly: Timer?
	var awake: Awake = .off
	var held: [String: IOPMAssertionID] = [:]   // the sleep assertions this app holds, by type
	var agentsBusy: Bool?                       // the last check: nil when it could not tell
	var awakeTimer: Timer?

	func applicationDidFinishLaunching(_ note: Notification) {
		NSApp.mainMenu = menu()
		let config = WKWebViewConfiguration()
		config.userContentController.add(self, name: "garrick")
		config.userContentController.addUserScript(appScript())
		web = WKWebView(frame: .zero, configuration: config)
		web.navigationDelegate = self
		web.uiDelegate = self
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
		_ = setHotKey(defaults.dictionary(forKey: kHotkey))
		if resident && defaults.bool(forKey: kAwakeWorking) { setAwake(.whileWorking) }
		// Out of sight, nothing brings the app forward to check the page's age.
		hourly = Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { [weak self] _ in self?.freshen() }
		if !startHidden { showWindow() }

		watch()
		if FileManager.default.fileExists(atPath: page.path) { load() }
		freshen()
	}

	// With the icon in the menu bar, or the panel at an edge, closing the window leaves the app there.
	func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { edgePanel == nil && statusItem == nil }

	func applicationShouldHandleReopen(_ app: NSApplication, hasVisibleWindows: Bool) -> Bool {
		if !hasVisibleWindows { showWindow() }
		return true
	}

	func windowWillClose(_ note: Notification) {
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

	// Left in the Dock for days, it still checks the page's age when it comes forward.
	func applicationDidBecomeActive(_ note: Notification) { if !checking { freshen() } }

	func load() {
		shown = modified(page)
		web.loadFileURL(page, allowingReadAccessTo: generated)
	}

	func reload() {
		guard modified(page) != nil else { return }
		if web.url == nil { return load() }
		shown = modified(page)
		web.reload()
	}

	func freshen(force: Bool = false) {
		let age = modified(page).map { -$0.timeIntervalSinceNow } ?? .infinity
		if force || age >= maxAge { rebuild() }
	}

	func rebuild() {
		guard !rebuilding else { return }
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

	func toast(_ text: String) {
		let quoted = (try? String(data: JSONSerialization.data(withJSONObject: [text]), encoding: .utf8)) ?? "[\"\"]"
		web.evaluateJavaScript("""
			(function(s){var t=document.getElementById('toast');if(!t)return;t.textContent=s;t.style.opacity=1;
			setTimeout(function(){t.style.opacity=0},4000)})(\(quoted)[0])
			""")
	}

	// MARK: the page's buttons

	func userContentController(_ c: WKUserContentController, didReceive message: WKScriptMessage) {
		guard let body = message.body as? [String: Any] else { return }
		if let m = body["menu"] {
			if checking { menuState = m as? [String: Any]; return heard.append("menu") }
			return setMenu(m as? [String: Any])
		}
		if checking { return heard.append(body.keys.sorted().joined(separator: "+")) }
		if let request = body["app"] as? [String: Any] { return setting(request) }
		if let text = body["copy"] as? String, !text.isEmpty {
			NSPasteboard.general.clearContents()
			NSPasteboard.general.setString(text, forType: .string)
		}
		if let app = body["launch"] as? String, let folder = body["folder"] as? String {
			launch(app, folder, phrase: body["phrase"] as? String ?? "")
		} else if let folder = body["cmux"] as? String {
			openInCmux(folder)                 // a page built before Open in Claude and Codex
		}
		if body["rebuild"] as? Bool == true { freshen(force: true) }
		if let request = body["act"] as? [String: Any] { act(request) }
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

	func copyText(_ text: String) {
		guard !text.isEmpty else { return }
		NSPasteboard.general.clearContents()
		NSPasteboard.general.setString(text, forType: .string)
	}

	// Open a project or thread folder in Claude, Codex or cmux, or show it in Finder. Claude gets the
	// phrase typed into a new session, for you to send; Codex and cmux get the
	// folder, and the phrase goes on the clipboard. Nothing is sent and no
	// command is typed into a terminal.
	func launch(_ app: String, _ path: String, phrase: String) {
		guard let folder = inWorkspace(path) else { return }
		switch app {
		case "claude":
			guard NSWorkspace.shared.urlForApplication(withBundleIdentifier: claudeBundle) != nil else {
				toast("Claude is not installed here any more. Rebuilding the page without it.")
				return freshen(force: true)
			}
			var c = URLComponents()
			c.scheme = "claude"; c.host = "code"; c.path = "/new"
			c.queryItems = [URLQueryItem(name: "folder", value: folder.path)] + (phrase.isEmpty ? [] : [URLQueryItem(name: "q", value: phrase)])
			if let url = c.url { NSWorkspace.shared.open(url) }
		case "codex":
			guard let codex = NSWorkspace.shared.urlForApplication(withBundleIdentifier: codexBundle) else {
				toast("Codex is not installed here any more. Rebuilding the page without it.")
				return freshen(force: true)
			}
			let cli = ["Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex", "Contents/Resources/codex", "Contents/Resources/bin/codex"]
				.map { codex.appendingPathComponent($0) }
				.first { FileManager.default.isExecutableFile(atPath: $0.path) }
			guard let cli else { return toast("Codex's own launcher is missing; reinstall the Codex app.") }
			copyText(phrase)
			let p = Process()
			p.executableURL = cli
			p.arguments = ["app", folder.path]
			p.standardOutput = FileHandle.nullDevice
			p.standardError = FileHandle.nullDevice
			do { try p.run() } catch { toast("Codex did not open that folder.") }
		case "cmux":
			copyText(phrase)
			openInCmux(folder.path)
		case "finder":
			NSWorkspace.shared.activateFileViewerSelecting([folder])
		default:
			return
		}
	}

	// A button that changes something (preview, page-actions): page_action.py,
	// beside status.py, does it and commits it, and says what it did. The app
	// only passes the request on; the script checks every part of it.
	func act(_ request: [String: Any]) {
		guard let data = try? JSONSerialization.data(withJSONObject: request) else { return }
		let script = builder.deletingLastPathComponent().appendingPathComponent("page_action.py")
		guard FileManager.default.fileExists(atPath: script.path) else {
			return toast("This page's actions need page_action.py beside status.py.")
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
				self.toast(said?["say"] as? String ?? "That did not work.")
				self.freshen(force: true)
			}
		}
		do {
			try p.run()
			input.fileHandleForWriting.write(data)
			input.fileHandleForWriting.closeFile()
		} catch {
			toast("Cannot run \(python)")
		}
	}

	// Only a folder inside this workspace, and only through Launch Services, as
	// Finder's Open With would: no socket, no password, no command typed.
	func openInCmux(_ path: String) {
		guard let folder = inWorkspace(path) else { return }
		guard let cmux = NSWorkspace.shared.urlForApplication(withBundleIdentifier: cmuxBundle) else {
			toast("cmux is not installed here any more. Rebuilding the page without it.")
			return freshen(force: true)
		}
		NSWorkspace.shared.open([folder], withApplicationAt: cmux, configuration: NSWorkspace.OpenConfiguration()) { _, error in
			if error != nil { DispatchQueue.main.async { self.toast("cmux did not open that folder.") } }
		}
	}

	// MARK: the menu bar (preview, menu-bar)

	// Settings › Menu bar shows the app's own values: they are put in the page
	// before it runs, and again whenever one changes.
	func appState() -> [String: Any] {
		var login: Any = NSNull()             // null: this macOS cannot add a login item this way
		if #available(macOS 13, *) { login = SMAppService.mainApp.status == .enabled }
		return ["menubar": defaults.bool(forKey: kMenuBar), "style": savedEdge()?.rawValue ?? "icon", "login": login,
		        "hotkey": defaults.dictionary(forKey: kHotkey)?["label"] as? String ?? ""]
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

	func appScript() -> WKUserScript {
		WKUserScript(source: """
			window.GarrickApp=\(appJSON());(function(i){var r=document.documentElement;r.classList.add('appicons');
			for(var k in i)r.style.setProperty('--icon-'+k,i[k])})(\(iconJSON));
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
				toast(on ? "Rebuilding the page for the menu." : "Taken out of the menu bar.")
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
		if let key = request["hotkey"] {
			let spec = key as? [String: Any]
			if setHotKey(spec) {
				defaults.set(spec, forKey: kHotkey)
				toast(spec == nil ? "No hotkey." : "\(spec?["label"] as? String ?? "That") opens the menu from any app.")
			} else {
				_ = setHotKey(defaults.dictionary(forKey: kHotkey))   // keep the one that worked
				toast("Another app already uses that shortcut. Try another.")
			}
		}
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
			item.button?.toolTip = "Garrick"
			statusItem = item
		}
		let trouble = (menuState?["data"] as? [String: Any])?["trouble"] as? Bool == true
		statusItem?.button?.image = icon(trouble: trouble, awake: !held.isEmpty)
		statusItem?.button?.setAccessibilityLabel((trouble ? "Garrick: something failed" : "Garrick") + (held.isEmpty ? "" : ", keeping the Mac awake"))
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

	// A view-backed row repaints only when told: the highlight moves here.
	func menu(_ menu: NSMenu, willHighlight item: NSMenuItem?) {
		menu.items.forEach { $0.view?.needsDisplay = true }
	}

	// The zone the graph shows: All shows every zone; a wiki, or a zone gone
	// since, falls back to Work, as the graph does, or to every zone.
	func shownZones() -> [[String: Any]] {
		let zones = (menuState?["data"] as? [String: Any])?["zones"] as? [[String: Any]] ?? []
		let place = menuState?["place"] as? String ?? ""
		if place != "*", let z = zones.first(where: { $0["z"] as? String == place }) { return [z] }
		if place != "*", let z = zones.first(where: { $0["z"] as? String == "Work" }) { return [z] }
		return zones
	}

	// A row's actions, as its card offers them: the note's own link, then each
	// app switched on in Settings that can open its folder. The one Settings
	// picks for clicking a thread is the default, and the note where it is not
	// on offer.
	func acts(_ r: [String: Any]) -> [[String: Any]] {
		var out: [[String: Any]] = []
		if menuState?["note"] as? Bool != false, let u = r["u"] as? String { out.append(["k": "note", "u": u]) }
		if let f = r["f"] as? String {
			for k in menuState?["launchers"] as? [String] ?? [] { out.append(["k": k, "f": f, "w": r["w"] as? String ?? ""]) }
		}
		let picked = menuState?["def"] as? String ?? "note"
		let n = out.firstIndex(where: { $0["k"] as? String == picked }) ?? out.firstIndex(where: { $0["k"] as? String == "note" }) ?? 0
		if !out.isEmpty { out[n]["d"] = true }
		return out
	}

	// The menu: Process the Inbox, then the shown zone's projects. Hovering one
	// opens its actions and its threads; hovering a thread opens its actions.
	// Clicking a project or a thread itself runs its default.
	func fill(_ menu: NSMenu) {
		menu.removeAllItems()
		if let inbox = inboxItem() {
			menu.addItem(inbox)
			menu.addItem(.separator())
		}
		for (n, zone) in shownZones().enumerated() {
			if n > 0 { menu.addItem(.separator()) }
			menu.addItem(header(zone["z"] as? String ?? ""))
			let projects = zone["p"] as? [[String: Any]] ?? []
			if projects.isEmpty {
				let none = NSMenuItem(title: "No live projects", action: nil, keyEquivalent: "")
				none.isEnabled = false
				menu.addItem(none)
			}
			projects.forEach { menu.addItem(row($0)) }
		}
		menu.addItem(.separator())
		menu.addItem(awakeItem())
		let open = NSMenuItem(title: "Open Garrick", action: #selector(showWindow(_:)), keyEquivalent: "")
		show(open, mark(16))
		open.target = self
		menu.addItem(open)
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
	func row(_ r: [String: Any]) -> NSMenuItem {
		let acts = acts(r)
		let fallback = acts.first(where: { $0["d"] as? Bool == true })
		let item = NSMenuItem(title: r["n"] as? String ?? "", action: nil, keyEquivalent: "")
		item.view = RowView(item.title) { [weak self] in if let a = fallback { self?.run(a) } }
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
	// card's button opens it.
	func run(_ a: [String: Any]) {
		let k = a["k"] as? String ?? ""
		if checking { return heard.append("menu:" + k) }
		if k == "note" {
			if let u = a["u"] as? String, let url = URL(string: u) { NSWorkspace.shared.open(url) }
		} else if let f = a["f"] as? String {
			let w = a["w"] as? String ?? ""
			launch(k, f, phrase: w.isEmpty ? "" : "open " + w)
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
	// "open X": Claude gets it typed in, Codex and cmux on the clipboard.
	func inbox() -> (title: String, waiting: Int, act: [String: String], where: String)? {
		guard let row = (menuState?["data"] as? [String: Any])?["intake"] as? [String: Any],
		      let folder = row["f"] as? String, let phrase = row["w"] as? String else { return nil }
		let on = menuState?["launchers"] as? [String] ?? []
		let assistants = ["claude", "codex", "cmux"].filter(on.contains)
		let picked = menuState?["def"] as? String ?? ""
		guard let app = assistants.contains(picked) ? picked : assistants.first else { return nil }
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
		item.toolTip = "Opens \(label(["k": app])) at the workspace root with \u{201C}\(phrase)\u{201D}"
		return item
	}

	@objc func processInbox(_ sender: NSMenuItem) {
		guard let r = sender.representedObject as? [String: String], let k = r["k"], let f = r["f"] else { return }
		if checking { return heard.append("menu:inbox") }
		launch(k, f, phrase: r["w"] ?? "")
	}

	// MARK: the panel
	// The menu's rows for the panel: the same zones, rows, actions and Keep
	// awake, each running as its menu item does.
	func fillPanel(_ m: PanelModel) {
		let trouble = (menuState?["data"] as? [String: Any])?["trouble"] as? Bool == true
		m.trouble = trouble
		m.mark = icon(trouble: trouble, awake: !held.isEmpty)
		m.zones = shownZones().map { z in PanelZone(name: z["z"] as? String ?? "", rows: (z["p"] as? [[String: Any]] ?? []).map(panelRow)) }
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
	}

	func panelRow(_ r: [String: Any]) -> PanelRow {
		let acts = acts(r)
		let fallback = acts.first(where: { $0["d"] as? Bool == true })
		let name = r["n"] as? String ?? ""
		return PanelRow(id: (r["f"] as? String ?? r["u"] as? String ?? "") + "\u{0}" + name, name: name,
		                acts: acts.enumerated().map { n, a in
		                	PanelAct(id: n, icon: icon(a), label: label(a), isDefault: a["d"] as? Bool == true) { [weak self] in self?.run(a) }
		                },
		                threads: (r["t"] as? [[String: Any]] ?? []).map(panelRow),
		                open: fallback.map { a in { [weak self] in self?.run(a) } })
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

	// A system-wide shortcut through Carbon's hot keys, which need no
	// Accessibility permission. It opens the menu, or the window when the
	// icon is off. False when the shortcut is someone else's.
	func setHotKey(_ spec: [String: Any]?) -> Bool {
		if let old = hotKey { UnregisterEventHotKey(old); hotKey = nil }
		guard let spec else { return true }
		guard let code = spec["code"] as? String, let vk = keyCodes[code] else { return false }
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
		if hotKeyHandler == nil {
			var pressed = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
			InstallEventHandler(GetApplicationEventTarget(), { _, _, _ in
				DispatchQueue.main.async { (NSApp.delegate as? StatusApp)?.hotKeyPressed() }
				return noErr
			}, 1, &pressed, nil, &hotKeyHandler)
		}
		let id = EventHotKeyID(signature: OSType(0x4752_4B53), id: 1)   // 'GRKS'
		return RegisterEventHotKey(UInt32(vk), mods, id, GetApplicationEventTarget(), 0, &hotKey) == noErr
	}

	func hotKeyPressed() {
		if let panel = edgePanel { panel.toggle() }
		else if let button = statusItem?.button { button.performClick(nil) } else { showWindow() }
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
		NSWorkspace.shared.open(url)
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
		guard checking else { return }
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
				// The menu bar's menu, filled from what the page sent, and its first thread pressed.
				if self.menuState != nil {
					let m = NSMenu()
					self.fill(m)
					let rows = m.items.compactMap { $0.view as? RowView }
					let threads = m.items.flatMap { $0.submenu?.items ?? [] }.filter { $0.view is RowView }.count
					print("menu: \(rows.count) projects, \(threads) threads in \(self.shownZones().count) zone(s)")
					if let inbox = m.items.first(where: { $0.action == #selector(self.processInbox(_:)) }) {
						print("inbox: \(inbox.attributedTitle?.string ?? inbox.title), via \((inbox.representedObject as? [String: String])?["k"] ?? "?")")
					} else {
						print("inbox: none")
					}
					let panel = PanelModel()
					self.fillPanel(panel)
					let projects = panel.zones.flatMap { $0.rows }
					print("panel: \(projects.count) projects, \(projects.reduce(0) { $0 + $1.threads.count }) threads")
					rows.first?.click()
					projects.first?.open?()
				} else {
					print("menu: none")
				}
				print("heard: \(self.heard)")
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
		sub("File", [
			item("Open in Browser", #selector(openInBrowser(_:)), "o"),
			.separator(),
			item("Close Window", #selector(NSWindow.performClose(_:)), "w"),
		])
		sub("Edit", [
			item("Copy", #selector(NSText.copy(_:)), "c"),
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

// MARK: the panel (preview, menu-bar)
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
	var after: () -> Void = {}
	// Close first, then act, so the app that opens comes forward over a panel already leaving.
	func perform(_ f: @escaping () -> Void) { after(); f() }
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
	@State private var folded: Set<String> = []
	@FocusState private var typing: Bool

	var query: String { model.filter.trimmingCharacters(in: .whitespaces).lowercased() }

	// Filtered: a project whose name matches keeps all its threads; otherwise only the threads that match.
	func shown(_ rows: [PanelRow]) -> [PanelRow] {
		guard !query.isEmpty else { return rows }
		return rows.compactMap { r in
			if r.name.lowercased().contains(query) { return r }
			let t = r.threads.filter { $0.name.lowercased().contains(query) }
			return t.isEmpty ? nil : PanelRow(id: r.id, name: r.name, acts: r.acts, threads: t, open: r.open)
		}
	}

	// Return opens the first thread that matches, or the first project.
	func first() -> (() -> Void)? {
		let rows = model.zones.flatMap { shown($0.rows) }
		if !query.isEmpty, let t = rows.flatMap({ $0.threads }).first(where: { $0.name.lowercased().contains(query) }) { return t.open }
		return rows.first?.open
	}

	func awake(_ title: String, _ tag: Int, _ on: Bool) -> some View {
		Toggle(title, isOn: Binding(get: { on }, set: { _ in model.pickAwake(tag) }))
	}

	var body: some View {
		VStack(alignment: .leading, spacing: 8) {
			HStack(spacing: 8) {
				Image(nsImage: model.mark).resizable().frame(width: 16, height: 16)
				Text("Garrick").font(.system(size: 13, weight: .semibold))
				Spacer()
				if model.trouble {
					Text("Something failed").font(.system(size: 11)).foregroundColor(.red)
				}
			}
			HStack(spacing: 6) {
				Image(systemName: "magnifyingglass").font(.system(size: 11)).foregroundColor(.secondary)
				TextField("Find a project or thread", text: $model.filter)
					.textFieldStyle(.plain)
					.font(.system(size: 12))
					.focused($typing)
					.onSubmit { if let open = first() { model.perform(open) } }
			}
			.padding(.horizontal, 10)
			.padding(.vertical, 6)
			.background(Capsule().fill(Color.primary.opacity(0.08)))
			ScrollView {
				VStack(alignment: .leading, spacing: 1) {
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
							let shut = query.isEmpty && folded.contains(r.id)
							PanelLine(row: r, depth: 0, folded: r.threads.isEmpty ? nil : shut,
							          toggle: { if folded.contains(r.id) { folded.remove(r.id) } else { folded.insert(r.id) } },
							          perform: model.perform)
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
	static let ear: CGFloat = 16, corner: CGFloat = 32
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
		arm()
	}

	// The notch, where the screen has one: the gap between the two parts of the menu bar beside it.
	func notch(_ s: NSScreen) -> NSRect? {
		guard #available(macOS 12, *), s.safeAreaInsets.top > 0,
		      let l = s.auxiliaryTopLeftArea, let r = s.auxiliaryTopRightArea, r.minX > l.maxX else { return nil }
		return NSRect(x: l.maxX, y: s.frame.maxY - s.safeAreaInsets.top, width: r.minX - l.maxX, height: s.safeAreaInsets.top)
	}

	// As tall as what it lists, up to most of the screen: a guess from the
	// rows, since a scrolling list has no height of its own.
	func contentHeight() -> CGFloat {
		let rows = model.zones.reduce(0) { $0 + max(1, $1.rows.count) + $1.rows.reduce(0) { $0 + $1.threads.count } }
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
app.setActivationPolicy(checking ? .prohibited : startHidden ? .accessory : .regular)
app.run()

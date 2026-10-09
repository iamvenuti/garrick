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
//     dot when the Status tab has one. Settings › Menu bar switches it on,
//     opens the app at login and sets a hotkey for the menu; the app keeps
//     those three in its own defaults, as it keeps the menu between launches.
// Nothing here changes a file in the workspace, as nothing on the page does.
import AppKit
import Carbon.HIToolbox
import ServiceManagement
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
	var menuState: [String: Any]?     // what the page last said the menu lists
	var hotKey: EventHotKeyRef?
	var hotKeyHandler: EventHandlerRef?
	var hourly: Timer?

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
		if defaults.bool(forKey: kMenuBar) && menuState != nil { showStatusItem() }
		_ = setHotKey(defaults.dictionary(forKey: kHotkey))
		// Out of sight, nothing brings the app forward to check the page's age.
		hourly = Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { [weak self] _ in self?.freshen() }
		if !startHidden { showWindow() }

		watch()
		if FileManager.default.fileExists(atPath: page.path) { load() }
		freshen()
	}

	// With the icon in the menu bar, closing the window leaves the app there.
	func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { statusItem == nil }

	func applicationShouldHandleReopen(_ app: NSApplication, hasVisibleWindows: Bool) -> Bool {
		if !hasVisibleWindows { showWindow() }
		return true
	}

	func windowWillClose(_ note: Notification) {
		guard statusItem != nil else { return }
		defaults.set(false, forKey: kWindowShown)
		NSApp.setActivationPolicy(.accessory)  // no Dock icon while only the menu bar's is there
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
		var isDir: ObjCBool = false
		guard folder.path.hasPrefix(workspace.standardizedFileURL.path + "/"),
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
		return ["menubar": defaults.bool(forKey: kMenuBar), "login": login,
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
		if let on = request["menubar"] as? Bool {
			defaults.set(on, forKey: kMenuBar)
			if on && menuState != nil {
				showStatusItem()
				toast("Garrick is in the menu bar. Close the window and it stays there.")
			} else {
				hideStatusItem()
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
	// off, which takes the icon away and brings the window back if it was hidden.
	func setMenu(_ m: [String: Any]?) {
		menuState = m
		if let m, let data = try? JSONSerialization.data(withJSONObject: m) {
			defaults.set(data, forKey: kMenu)
		} else {
			defaults.removeObject(forKey: kMenu)
		}
		if m != nil && defaults.bool(forKey: kMenuBar) { showStatusItem() } else { hideStatusItem() }
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
		statusItem?.button?.image = icon(trouble: trouble)
		statusItem?.button?.setAccessibilityLabel(trouble ? "Garrick: something failed" : "Garrick")
	}

	func hideStatusItem() {
		guard let item = statusItem else { return }
		NSStatusBar.system.removeStatusItem(item)
		statusItem = nil
		if !window.isVisible { showWindow() }  // never leave the app with nothing to click
	}

	// Garrick's mark, the small cut from status.py on its 64-unit grid: the
	// walls in the menu bar's own text colour, the open compartment in the
	// mark's blue for that ground, and the Status tab's red dot. Drawn at each
	// draw, so it follows the menu bar from light to dark.
	func icon(trouble: Bool) -> NSImage {
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

	// The menu: the shown zone's projects. Hovering one opens its actions and
	// its threads; hovering a thread opens its actions. Clicking a project or a
	// thread itself runs its default.
	func fill(_ menu: NSMenu) {
		menu.removeAllItems()
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
		let open = NSMenuItem(title: "Open Garrick", action: #selector(showWindow(_:)), keyEquivalent: "")
		open.target = self
		menu.addItem(open)
		menu.addItem(NSMenuItem(title: "Quit Garrick", action: #selector(NSApplication.terminate(_:)), keyEquivalent: ""))
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
		if let button = statusItem?.button { button.performClick(nil) } else { showWindow() }
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
					rows.first?.click()
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

let app = NSApplication.shared
let delegate = StatusApp()
app.delegate = delegate
app.setActivationPolicy(checking ? .prohibited : startHidden ? .accessory : .regular)
app.run()

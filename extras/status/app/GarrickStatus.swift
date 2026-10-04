// Garrick's Status.app: the status page in a window of its own, for the Dock
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
//   - every link the page holds (a note in Obsidian, a file, the web) goes to
//     the app macOS uses for it.
// Nothing here changes a file in the workspace, as nothing on the page does.
import AppKit
import WebKit

let info = Bundle.main.infoDictionary ?? [:]
let workspace = URL(fileURLWithPath: info["GarrickWorkspace"] as? String ?? NSHomeDirectory() + "/Garrick", isDirectory: true)
let generated = workspace.appendingPathComponent("System/generated", isDirectory: true)
let page = generated.appendingPathComponent("status.html")
let builder = URL(fileURLWithPath: info["GarrickStatusScript"] as? String ?? workspace.path + "/System/status/status.py")
let python = info["GarrickPython"] as? String ?? "/usr/bin/python3"
let flags = info["GarrickStatusArgs"] as? [String] ?? []
let cmuxBundle = "com.cmuxterm.app"
let maxAge: TimeInterval = 30 * 60
// --check loads the page out of sight, acts on nothing, prints what it found
// and quits: the test that the page loads, sees the app and is answered.
let checking = CommandLine.arguments.contains("--check")

func modified(_ url: URL) -> Date? {
	(try? FileManager.default.attributesOfItem(atPath: url.path))?[.modificationDate] as? Date
}

final class StatusApp: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
	var window: NSWindow!
	var web: WKWebView!
	var watcher: DispatchSourceFileSystemObject?
	var shown: Date?
	var rebuilding = false
	var pendingReload: DispatchWorkItem?
	var heard: [String] = []          // what --check caught instead of acting on

	func applicationDidFinishLaunching(_ note: Notification) {
		NSApp.mainMenu = menu()
		let config = WKWebViewConfiguration()
		config.userContentController.add(self, name: "garrick")
		web = WKWebView(frame: .zero, configuration: config)
		web.navigationDelegate = self
		web.uiDelegate = self
		web.allowsMagnification = true

		window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1400, height: 900),
		                  styleMask: [.titled, .closable, .miniaturizable, .resizable],
		                  backing: .buffered, defer: false)
		window.title = "Garrick's Status"
		window.contentView = web
		window.center()
		window.setFrameAutosaveName("GarrickStatus")
		if checking { return load() }
		window.makeKeyAndOrderFront(nil)

		watch()
		if FileManager.default.fileExists(atPath: page.path) { load() }
		freshen()
		NSApp.activate(ignoringOtherApps: true)
	}

	func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }

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
		if checking { return heard.append(body.keys.sorted().joined(separator: "+")) }
		if let text = body["copy"] as? String, !text.isEmpty {
			NSPasteboard.general.clearContents()
			NSPasteboard.general.setString(text, forType: .string)
		}
		if let folder = body["cmux"] as? String { openInCmux(folder) }
		if body["rebuild"] as? Bool == true { freshen(force: true) }
	}

	// Only a folder inside this workspace, and only through Launch Services, as
	// Finder's Open With would: no socket, no password, no command typed.
	func openInCmux(_ path: String) {
		let folder = URL(fileURLWithPath: path, isDirectory: true).standardizedFileURL
		var isDir: ObjCBool = false
		guard folder.path.hasPrefix(workspace.standardizedFileURL.path + "/"),
		      FileManager.default.fileExists(atPath: folder.path, isDirectory: &isDir), isDir.boolValue else {
			toast("That folder is not in this workspace any more. Rebuilding the page.")
			return freshen(force: true)
		}
		guard let cmux = NSWorkspace.shared.urlForApplication(withBundleIdentifier: cmuxBundle) else {
			toast("cmux is not installed here any more. Rebuilding the page without it.")
			return freshen(force: true)
		}
		NSWorkspace.shared.open([folder], withApplicationAt: cmux, configuration: NSWorkspace.OpenConfiguration()) { _, error in
			if error != nil { DispatchQueue.main.async { self.toast("cmux did not open that folder.") } }
		}
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
			rebuild:rb?rb.textContent:null,stored:p,
			cmux:[].filter.call(document.querySelectorAll('[data-card]'),function(r){return JSON.parse(r.dataset.card).f}).length})})()
			""") { result, error in
			DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
				print(result as? String ?? "error: \(String(describing: error))")
				print("heard: \(self.heard)")
				exit(0)
			}
		}
	}

	// MARK: menu

	@objc func reloadPage(_ sender: Any?) { reload() }
	@objc func rebuildPage(_ sender: Any?) { freshen(force: true) }
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
		sub("Garrick's Status", [
			item("About Garrick's Status", #selector(NSApplication.orderFrontStandardAboutPanel(_:)), ""),
			.separator(),
			item("Hide Garrick's Status", #selector(NSApplication.hide(_:)), "h"),
			item("Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
			item("Show All", #selector(NSApplication.unhideAllApplications(_:)), ""),
			.separator(),
			item("Quit Garrick's Status", #selector(NSApplication.terminate(_:)), "q"),
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
app.setActivationPolicy(checking ? .prohibited : .regular)
app.run()

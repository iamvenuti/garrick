// The rules Garrick.app and its Finder extension share, compiled into both so
// they cannot drift apart: which folder a Finder link may open, and how the
// link is written and read. Foundation only, and no state: a test compiles this
// file alone (tests/test_status_finder.py).
//
// A link is garrick://open?app=<opener>&folder=<path>&t=<token>. The token is
// random per build (make-app.sh puts it in the app's and the extension's
// Info.plist), so a web page that fires a garrick:// link opens nothing.
import Foundation

enum GarrickLink {
	static let openers = ["cmux", "claude", "codex"]
	// Names that are never a project, whatever a folder of that name holds.
	static let reserved = ["Inbox", "Sources", "Deliverables"]

	// True when both strings are equal, whatever the first byte that differs:
	// the time taken does not say how much of a token was right.
	static func sameToken(_ a: String, _ b: String) -> Bool {
		let x = Array(a.utf8), y = Array(b.utf8)
		guard !x.isEmpty, x.count == y.count else { return false }
		var diff: UInt8 = 0
		for i in 0..<x.count { diff |= x[i] ^ y[i] }
		return diff == 0
	}

	// A path as the file system has it, symlinks and ".." resolved; nil if there is none.
	static func real(_ path: String) -> String? {
		guard let c = realpath(path, nil) else { return nil }
		defer { free(c) }
		return String(cString: c)
	}

	// A regular file (not a folder), after symlinks.
	static func isFile(_ path: String) -> Bool {
		var isDir: ObjCBool = false
		return FileManager.default.fileExists(atPath: path, isDirectory: &isDir) && !isDir.boolValue
	}

	// No control character (C0, C1), line or paragraph separator in a name.
	static func clean(_ name: String) -> Bool {
		!name.unicodeScalars.contains { [.control, .lineSeparator, .paragraphSeparator].contains($0.properties.generalCategory) }
	}

	// The folder, resolved, when it is a project (<Zone>/<Project>/ holding <Project>.md)
	// or a thread (<Zone>/<Project>/Threads/<Thread>/ holding <Thread>.md) of the
	// workspace's Zones/; nil for anything else: Sources/, Deliverables/, Inbox/, a zone
	// folder, Wikis/, a folder outside, or a symlink or ".." that leads out. Reads
	// folder names and whether the note exists, never a note's content.
	static func openable(_ path: String, workspace: String) -> URL? {
		guard !path.isEmpty, let zones = real(workspace + "/Zones"), let folder = real(path),
		      folder.hasPrefix(zones + "/") else { return nil }
		let parts = folder.dropFirst(zones.count + 1).split(separator: "/", omittingEmptySubsequences: false).map(String.init)
		// No empty or hidden part, and no control or line-separator character: a name becomes prompt text.
		guard !parts.contains(where: { $0.isEmpty || $0.hasPrefix(".") || !clean($0) }) else { return nil }
		let name: String
		switch parts.count {
		case 2: name = parts[1]                                         // a project
		case 4 where parts[2] == "Threads": name = parts[3]             // a thread
		default: return nil
		}
		// A thread belongs to a project: Sources/Threads/X is no thread, whatever X holds.
		guard !reserved.contains(parts[1]), !reserved.contains(name) else { return nil }
		guard isFile(zones + "/" + parts[0] + "/" + parts[1] + "/" + parts[1] + ".md"),
		      isFile(folder + "/" + name + ".md") else { return nil }
		return URL(fileURLWithPath: folder, isDirectory: true)
	}

	// What a session is told to open: "open Project, Thread" for a thread and "open Project" for a project,
	// as page_action.cmux_folder says it, so two projects with a thread of one name are told apart.
	// Takes a folder openable() accepted.
	static func phrase(for folder: URL) -> String {
		let up = folder.deletingLastPathComponent()
		guard up.lastPathComponent == "Threads" else { return "open " + folder.lastPathComponent }
		return "open " + up.deletingLastPathComponent().lastPathComponent + ", " + folder.lastPathComponent
	}

	private static let safe = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")

	static func url(app: String, folder: String, token: String) -> URL? {
		func e(_ s: String) -> String? { s.addingPercentEncoding(withAllowedCharacters: safe) }
		guard let a = e(app), let f = e(folder), let t = e(token) else { return nil }
		return URL(string: "garrick://open?app=\(a)&folder=\(f)&t=\(t)")
	}

	// The opener and folder a link names, only when its token is the build's own;
	// nil, and nothing said, for anything else. A key given twice is refused.
	static func parse(_ url: URL, token: String) -> (app: String, folder: String)? {
		guard url.scheme == "garrick", url.host == "open",
		      let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.percentEncodedQuery else { return nil }
		var found: [String: String] = [:]
		for pair in query.split(separator: "&", omittingEmptySubsequences: false) {
			let kv = pair.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
			guard kv.count == 2, let key = kv[0].removingPercentEncoding, let value = kv[1].removingPercentEncoding,
			      found[key] == nil else { return nil }
			found[key] = value
		}
		guard let given = found["t"], sameToken(given, token),
		      let app = found["app"], openers.contains(app), let folder = found["folder"] else { return nil }
		return (app, folder)
	}
}

// A new session in the Claude or Codex desktop app (#652). The link comes from page_action.py's session-url,
// built from the folder the workspace holds; the app opens it only when it is the one its key allows, and
// falls back when the app does not take it. No state, and no app is touched here: the opener, the app and
// the clipboard are passed in, so a test stubs them.
enum GarrickSession {
	// The scheme, host, path and query names each key's link must have.
	static let routes = [
		"claude-new": (scheme: "claude", host: "code", path: "/new", names: ["folder", "q"]),
		"codex-new": (scheme: "codex", host: "threads", path: "/new", names: ["path", "prompt"])]

	// The link, when its scheme, host and path are its key's own, its query names exactly that key's two, each once,
	// and it carries nothing else; nil for anything else, a link to any other app, host or route included.
	static func link(key: String, text: String) -> URL? {
		guard let route = routes[key], let url = URL(string: text), url.scheme == route.scheme, url.host == route.host,
		      url.path == route.path, url.user == nil, url.password == nil, url.port == nil, url.fragment == nil,
		      let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems,
		      items.map({ $0.name }).sorted() == route.names.sorted() else { return nil }
		return url
	}

	// Opens the link. When the app does not take it, opens the app instead, puts the prompt on the clipboard,
	// and says false, so the caller tells the user in one sentence. Opens nothing twice.
	static func open(_ url: URL, prompt: String, opener: (URL) -> Bool, openApp: () -> Void, copy: (String) -> Void) -> Bool {
		if opener(url) { return true }
		copy(prompt)
		openApp()
		return false
	}
}

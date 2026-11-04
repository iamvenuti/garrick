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

	// The folder, resolved, when it is a project (<Zone>/<Project>/ holding <Project>.md)
	// or a thread (<Zone>/<Project>/Threads/<Thread>/ holding <Thread>.md) of the
	// workspace's Zones/; nil for anything else: Sources/, Deliverables/, Inbox/, a zone
	// folder, Wikis/, a folder outside, or a symlink or ".." that leads out. Reads
	// folder names and whether the note exists, never a note's content.
	static func openable(_ path: String, workspace: String) -> URL? {
		guard !path.isEmpty, let zones = real(workspace + "/Zones"), let folder = real(path),
		      folder.hasPrefix(zones + "/") else { return nil }
		let parts = folder.dropFirst(zones.count + 1).split(separator: "/", omittingEmptySubsequences: false).map(String.init)
		guard !parts.contains(where: { $0.isEmpty || $0.hasPrefix(".") }) else { return nil }
		let name: String
		switch parts.count {
		case 2: name = parts[1]                                         // a project
		case 4 where parts[2] == "Threads": name = parts[3]             // a thread
		default: return nil
		}
		guard !reserved.contains(name) else { return nil }
		var isDir: ObjCBool = false
		let note = folder + "/" + name + ".md"
		guard FileManager.default.fileExists(atPath: note, isDirectory: &isDir), !isDir.boolValue else { return nil }
		return URL(fileURLWithPath: folder, isDirectory: true)
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

// Garrick's Finder extension (#346): right-click a project or a thread folder in the
// workspace's Zones/ and Finder offers Garrick > Open in cmux, Claude or Codex.
//
// It is sandboxed (the App Sandbox entitlement is the only one it has), so it opens
// nothing itself: a choice becomes a garrick://open link that only Garrick.app, the app
// that holds this build's token, answers. The app checks the folder and the opener again.
//
// It reads folder names and whether a hub note or a thread note exists, never a note's
// content. Which openers are on is told by files the app keeps in the folder named by
// GarrickFinderState in this extension's Info.plist: one empty file for each opener
// that is switched on in Settings and installed. The extension reads whether the file is
// there, so turning an opener off needs no rebuild. Checked on macOS 27 with a scratch build: the
// sandbox lets this extension stat a path outside its container, anywhere (/tmp, the home folder,
// Library/Application Support), so it sees that a file exists, but it denies reading one and listing a
// folder. So it asks only whether a file exists.
import Cocoa
import FinderSync

final class GarrickFinder: FIFinderSync {
	private let info = Bundle.main.infoDictionary ?? [:]
	private var workspace: String { info["GarrickWorkspace"] as? String ?? "" }
	private var token: String { info["GarrickLinkToken"] as? String ?? "" }
	private var state: String { info["GarrickFinderState"] as? String ?? "" }
	// The most folders one right-click opens at once.
	private let most = 5

	override init() {
		super.init()
		let zones = workspace + "/Zones"
		var watched = [URL(fileURLWithPath: zones, isDirectory: true)]
		if let real = GarrickLink.real(zones), real != zones { watched.append(URL(fileURLWithPath: real, isDirectory: true)) }
		FIFinderSyncController.default().directoryURLs = Set(watched)
	}

	private func folders() -> [URL] {
		guard !workspace.isEmpty, !token.isEmpty,
		      let chosen = FIFinderSyncController.default().selectedItemURLs(), !chosen.isEmpty, chosen.count <= most else { return [] }
		let found = chosen.compactMap { GarrickLink.openable($0.path, workspace: workspace) }
		return found.count == chosen.count ? found : []      // every one a project or a thread, or none
	}

	override func menu(for menuKind: FIMenuKind) -> NSMenu? {
		guard menuKind == .contextualMenuForItems, !folders().isEmpty, !state.isEmpty else { return nil }
		let on = GarrickLink.openers.filter { FileManager.default.fileExists(atPath: state + "/" + $0) }
		guard !on.isEmpty else { return nil }
		let sub = NSMenu(title: "Garrick")
		for k in on {
			let item = NSMenuItem(title: "Open in " + (k == "cmux" ? "cmux" : k.capitalized), action: #selector(open(_:)), keyEquivalent: "")
			item.target = self
			// Finder copies this menu into its own process and keeps an item's title, action and tag, not its
			// representedObject: the opener travels as its place in GarrickLink.openers, plus one, since 0 is no tag.
			item.tag = (GarrickLink.openers.firstIndex(of: k) ?? -1) + 1
			sub.addItem(item)
		}
		let top = NSMenuItem(title: "Garrick", action: nil, keyEquivalent: "")
		if let icon = Bundle.main.image(forResource: "AppIcon") {
			icon.size = NSSize(width: 16, height: 16)
			top.image = icon
		}
		top.submenu = sub
		let menu = NSMenu(title: "")
		menu.addItem(top)
		return menu
	}

	@objc func open(_ sender: NSMenuItem) {
		// Garrick.app is three folders up: <app>/Contents/PlugIns/<this>.appex. Only that app is sent the link.
		let app = Bundle.main.bundleURL.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
		let i = sender.tag - 1
		guard GarrickLink.openers.indices.contains(i), app.pathExtension == "app" else { return }
		let opener = GarrickLink.openers[i]
		for folder in folders() {
			guard let link = GarrickLink.url(app: opener, folder: folder.path, token: token) else { continue }
			NSWorkspace.shared.open([link], withApplicationAt: app, configuration: NSWorkspace.OpenConfiguration())
		}
	}
}

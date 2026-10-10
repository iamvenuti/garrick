// Garrick for Obsidian: the status page in an Obsidian tab, with its buttons
// working as they do in Garrick.app. Desktop only. Copy this folder into a
// vault's .obsidian/plugins/garrick-status/ and switch it on under Community
// plugins. See docs/extras/status-page.md, "In Obsidian".
//
// The page lives outside every vault, in System/generated/status.html. The
// workspace is the first folder at or above the vault that holds
// System/rules.md and Zones/, or the folder named in the plugin's settings.
//
// What it adds to the page, and only that, as the app does:
//   - a <webview>, not an iframe, so the page keeps its own file:// storage
//     (folds, layout, theme) and a reload rereads the file;
//   - the page's `garrick` bridge. The page posts to
//     window.webkit.messageHandlers.garrick, which only Garrick.app has. The
//     plugin shows a copy of the page, status-obsidian.html beside it, with a
//     few lines at the top of its <head> that define that bridge and pass each
//     message out through the console, marked with a random word, so nothing
//     else the page logs is taken for one. The plugin answers as the app does:
//     Copy, Rebuild, the ways to open a thread (Finder, cmux, Codex, Claude),
//     and page_action.py for a button that changes something (preview
//     page-actions), then a toast on the page and a rebuild;
//   - every link on the page: a note in this vault opens in a new tab here,
//     anything else goes to macOS, as from a browser;
//   - a rebuild when the page is over 30 minutes old, as the tab opens and
//     each hour while it is open, and a reload whenever the page is rewritten;
//   - parked projects and threads hidden in the file explorer, read from
//     each hub and thread note's `status: parked`, kept current as notes change.
// Garrick.app's own settings (the menu bar, the hotkey) do nothing here.
const { Plugin, ItemView, Notice, PluginSettingTab, Setting, addIcon } = require("obsidian");
const { execFile, spawn } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { pathToFileURL, fileURLToPath } = require("url");
const { shell, clipboard } = require("electron");

const VIEW = "garrick-status";
const MAX_AGE_MS = 30 * 60 * 1000;
// Every kind of message the page posts to the bridge. tests/test_obsidian.py
// reads status.py's postMessage calls and fails when one is missing here.
const KINDS = ["act", "app", "copy", "cmux", "launch", "menu", "rebuild"];
const BUNDLES = { claude: "com.anthropic.claudefordesktop", codex: "com.openai.codex", cmux: "com.cmuxterm.app" };
const NAMES = { claude: "Claude", codex: "Codex", cmux: "cmux" };
const CODEX_CLI = ["Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex", "Contents/Resources/codex", "Contents/Resources/bin/codex"];
// Garrick's mark, from docs/assets/garrick-mark-favicon.svg on its 64-unit
// grid, scaled to Obsidian's 100-unit icons. The walls take the ribbon's text
// colour, light or dark; the open compartment keeps the mark's blue.
const MARK_WALLS = "M24 4V60H6C4.9 60 4 59.1 4 58V6C4 4.9 4.9 4 6 4ZM28 32H60V58C60 59.1 59.1 60 58 60H28Z";
const MARK_OPEN = "M28 4H58C59.1 4 60 4.9 60 6V28H28Z";
const DEFAULTS = { workspace: "", python: "/usr/bin/python3", script: "", flags: "", hideParked: true };

// The bridge, put at the top of the copy's <head> so it is there before the
// page's own scripts look for it. NONCE is replaced with this session's word.
const BRIDGE = `(function(){var tag=NONCE;
function out(kind,body){try{console.log(tag+kind+':'+JSON.stringify(body))}catch(e){}}
window.webkit={messageHandlers:{garrick:{postMessage:function(m){out('post',m)}}}};
window.addEventListener('click',function(e){if(e.defaultPrevented||e.button!==0)return;
var a=e.target&&e.target.closest&&e.target.closest('a[href]');if(!a)return;var h=a.getAttribute('href')||'';
if(!h||h.charAt(0)==='#'||/^javascript:/i.test(h))return;e.preventDefault();out('link',a.href)});})();`;

function quoted(s) {
	return JSON.stringify(String(s)).replace(/</g, "\\u003c");
}

class StatusView extends ItemView {
	constructor(leaf, plugin) {
		super(leaf);
		this.plugin = plugin;
	}
	getViewType() { return VIEW; }
	getDisplayText() { return "Garrick"; }
	getIcon() { return "garrick-mark"; }

	async onOpen(again) {
		this.contentEl.empty();
		this.contentEl.style.padding = "0";
		this.contentEl.style.overflow = "hidden";
		const root = this.plugin.root();
		if (!root) {
			this.contentEl.createEl("p", { text: "No Garrick workspace at or above this vault. Name it in Settings › Garrick." });
			return;
		}
		const page = this.plugin.copyPage();
		if (!page) {
			this.contentEl.createEl("p", { text: again ? "The status page did not build. Check that status.py is where Settings › Garrick says."
				: "No status page yet. Rebuilding it…" });
			if (again) return;
			await this.plugin.rebuild();
			return this.onOpen(true);
		}
		this.web = this.contentEl.createEl("webview", {
			attr: { src: pathToFileURL(page).href, style: "width:100%;height:100%" },
		});
		this.web.addEventListener("console-message", (e) => this.heard(e.message || ""));
		this.web.addEventListener("will-frame-navigate", (e) => {
			if (e.isMainFrame && !e.url.startsWith("file:")) this.plugin.follow(e.url);
		});
		this.addAction("external-link", "Open in browser", () => shell.openPath(this.plugin.page()));
		this.addAction("refresh-cw", "Rebuild", () => this.plugin.rebuild());
	}

	// A message the bridge passed out, marked with this session's word.
	heard(line) {
		const tag = this.plugin.nonce;
		if (!line.startsWith(tag)) return;
		const rest = line.slice(tag.length);
		const at = rest.indexOf(":");
		let body;
		try { body = JSON.parse(rest.slice(at + 1)); } catch (e) { return; }
		if (rest.slice(0, at) === "link" && typeof body === "string") return this.plugin.follow(body);
		if (rest.slice(0, at) === "post" && body && typeof body === "object") this.plugin.handle(this, body);
	}

	// As the app's toast(): the page's own #toast, for four seconds.
	toast(text) {
		if (!this.web) return new Notice(text);
		this.web.executeJavaScript(`(function(s){var t=document.getElementById('toast');if(!t)return;t.textContent=s;t.style.opacity=1;
setTimeout(function(){t.style.opacity=0},4000)})(${quoted(text)})`).catch(() => {});
	}

	reload() {
		try { this.web && this.web.reload(); } catch (e) {}
	}
}

class GarrickSettings extends PluginSettingTab {
	constructor(app, plugin) {
		super(app, plugin);
		this.plugin = plugin;
	}

	display() {
		const el = this.containerEl;
		el.empty();
		const text = (name, desc, key, hint) => new Setting(el).setName(name).setDesc(desc).addText((t) =>
			t.setPlaceholder(hint).setValue(this.plugin.settings[key]).onChange(async (v) => {
				this.plugin.settings[key] = v.trim();
				await this.plugin.saveData(this.plugin.settings);
			}));
		text("Workspace", "The Garrick workspace's folder. Leave it empty to use the first folder at or above this vault that holds System/rules.md and Zones/.",
			"workspace", this.plugin.root() || "~/Garrick");
		text("Python", "The python3 that runs status.py and page_action.py.", "python", "/usr/bin/python3");
		text("status.py", "Leave it empty for System/status/status.py in the workspace.", "script", "System/status/status.py");
		text("Flags", "Passed to status.py when the page is rebuilt, such as --no-graph.", "flags", "");
		new Setting(el).setName("Hide parked projects and threads")
			.setDesc("In the file explorer: a thread whose note says status: parked, and a project whose hub does or whose threads all do.")
			.addToggle((t) => t.setValue(this.plugin.settings.hideParked).onChange(async (v) => {
				this.plugin.settings.hideParked = v;
				await this.plugin.saveData(this.plugin.settings);
				this.plugin.hideParked();
			}));
	}
}

module.exports = class GarrickStatusPlugin extends Plugin {
	async onload() {
		this.settings = Object.assign({}, DEFAULTS, await this.loadData());
		this.nonce = "garrick-" + crypto.randomBytes(9).toString("hex") + ":";
		addIcon("garrick-mark", `<g transform="scale(1.5625)"><path d="${MARK_WALLS}" style="fill:currentColor;stroke:none"/>`
			+ `<path d="${MARK_OPEN}" style="fill:#3D73E0;stroke:none"/></g>`);
		this.registerView(VIEW, (leaf) => new StatusView(leaf, this));
		this.addRibbonIcon("garrick-mark", "Open Garrick", () => this.open(false));
		this.addCommand({ id: "open", name: "Open", callback: () => this.open(false) });
		this.addCommand({ id: "rebuild-open", name: "Rebuild and open", callback: () => this.open(true) });
		this.addCommand({ id: "open-browser", name: "Open in browser", callback: () => shell.openPath(this.page()) });
		this.addSettingTab(new GarrickSettings(this.app, this));

		// The page and the file list follow the workspace: a reload whenever the
		// page is rewritten, debounced so one rebuild is one reload.
		this.app.workspace.onLayoutReady(() => {
			this.watch();
			this.hideParked();
		});
		this.registerEvent(this.app.metadataCache.on("changed", () => this.soon("parked", () => this.hideParked(), 1000)));
		this.registerEvent(this.app.vault.on("rename", () => this.soon("parked", () => this.hideParked(), 1000)));
		this.registerInterval(window.setInterval(() => { if (this.views().length) this.freshen(false); }, 60 * 60 * 1000));
	}

	onunload() {
		if (this.watcher) this.watcher.close();
		if (this.style) this.style.remove();
	}

	soon(name, fn, ms) {
		this.timers = this.timers || {};
		clearTimeout(this.timers[name]);
		this.timers[name] = setTimeout(fn, ms);
	}

	// MARK: where things are

	vaultPath() {
		return this.app.vault.adapter.getBasePath();
	}

	root() {
		const set = this.settings.workspace;
		if (set) {
			const r = path.resolve(set.replace(/^~(?=$|\/)/, os.homedir()));
			return this.isWorkspace(r) ? r : null;
		}
		for (let d = path.resolve(this.vaultPath()); ; d = path.dirname(d)) {
			if (this.isWorkspace(d)) return d;
			if (path.dirname(d) === d) return null;
		}
	}

	isWorkspace(d) {
		try { return fs.statSync(path.join(d, "System", "rules.md")).isFile() && fs.statSync(path.join(d, "Zones")).isDirectory(); }
		catch (e) { return false; }
	}

	page() { return path.join(this.root() || "", "System", "generated", "status.html"); }
	copy() { return path.join(this.root() || "", "System", "generated", "status-obsidian.html"); }
	script() {
		const s = this.settings.script;
		return s ? path.resolve(this.root(), s.replace(/^~(?=$|\/)/, os.homedir())) : path.join(this.root(), "System", "status", "status.py");
	}
	python() { return this.settings.python || DEFAULTS.python; }
	views() { return this.app.workspace.getLeavesOfType(VIEW).map((l) => l.view).filter((v) => v instanceof StatusView); }

	// The page with the bridge in it, written beside the page and renamed
	// over the last copy, so a reload never reads half a file. Null with no page.
	copyPage() {
		let html;
		try { html = fs.readFileSync(this.page(), "utf8"); } catch (e) { return null; }
		const bridge = "<script>" + BRIDGE.replace("NONCE", quoted(this.nonce)) + "</script>";
		html = /<head[^>]*>/i.test(html) ? html.replace(/<head[^>]*>/i, (m) => m + bridge) : bridge + html;
		const out = this.copy();
		const tmp = out + ".tmp";
		try {
			fs.writeFileSync(tmp, html);
			fs.renameSync(tmp, out);
		} catch (e) {
			return null;
		}
		return out;
	}

	watch() {
		if (this.watcher) this.watcher.close();
		this.watcher = null;
		const root = this.root();
		if (!root) return;
		try {
			this.watcher = fs.watch(path.dirname(this.page()), (_, name) => {
				if (name !== path.basename(this.page())) return;
				this.soon("reload", () => {
					if (!this.copyPage()) return;
					this.views().forEach((v) => v.reload());
					this.hideParked();
				}, 500);
			});
		} catch (e) {}
	}

	// MARK: opening and rebuilding

	async open(force) {
		await this.freshen(force);
		const leaf = this.app.workspace.getLeavesOfType(VIEW)[0] || this.app.workspace.getLeaf("tab");
		if (leaf.view.getViewType() !== VIEW) await leaf.setViewState({ type: VIEW, active: true });
		this.app.workspace.revealLeaf(leaf);
	}

	async freshen(force) {
		let age = Infinity;
		try { age = Date.now() - fs.statSync(this.page()).mtimeMs; } catch (e) {}
		if (force || age >= MAX_AGE_MS) await this.rebuild();
	}

	rebuild() {
		const root = this.root();
		if (!root) return Promise.resolve(new Notice("No Garrick workspace found; name it in Settings › Garrick."));
		if (this.building) return this.building;
		const notice = new Notice("Rebuilding Garrick's status page…", 0);
		const flags = (this.settings.flags || "").split(/\s+/).filter(Boolean);
		this.building = new Promise((resolve) => {
			execFile(this.python(), [this.script(), "--workspace", root, ...flags], { cwd: root, timeout: 120000 }, (err) => {
				notice.hide();
				this.building = null;
				if (err) new Notice("The status page did not rebuild; showing the last build.");
				if (!this.watcher) this.watch();
				resolve();
			});
		});
		return this.building;
	}

	// MARK: the bridge, answered as Garrick.app answers it

	handle(view, body) {
		if (body.menu !== undefined) return;            // Garrick.app's menu bar: nothing to do here
		if (body.app) return view.toast("That setting is Garrick.app's own.");
		if (typeof body.copy === "string" && body.copy) clipboard.writeText(body.copy);
		if (typeof body.launch === "string" && typeof body.folder === "string") {
			this.launch(view, body.launch, body.folder, typeof body.phrase === "string" ? body.phrase : "");
		} else if (typeof body.cmux === "string") {
			this.launch(view, "cmux", body.cmux, "");   // a page built before the other apps
		}
		if (body.rebuild === true) this.rebuild();
		if (body.act && typeof body.act === "object") this.act(view, body.act);
	}

	// A folder of this workspace that still exists, or null, with the page rebuilt.
	inWorkspace(view, p) {
		const root = this.root();
		const folder = path.resolve(p);
		let ok = false;
		try { ok = (folder === root || folder.startsWith(root + path.sep)) && fs.statSync(folder).isDirectory(); } catch (e) {}
		if (!ok) {
			view.toast("That folder is not in this workspace any more. Rebuilding the page.");
			this.rebuild();
			return null;
		}
		return folder;
	}

	gone(view, app) {
		view.toast(`${NAMES[app]} is not installed here any more. Rebuilding the page without it.`);
		this.rebuild();
	}

	// As Garrick.swift's launch(): Claude gets the phrase typed into a new
	// session for you to send; Codex and cmux get the folder, and the phrase
	// goes on the clipboard; Finder shows the folder. Nothing is sent and no
	// command is typed into a terminal.
	launch(view, app, p, phrase) {
		const folder = this.inWorkspace(view, p);
		if (!folder) return;
		if (app === "claude") {
			const url = "claude://code/new?folder=" + encodeURIComponent(folder) + (phrase ? "&q=" + encodeURIComponent(phrase) : "");
			execFile("open", [url], (err) => { if (err) this.gone(view, "claude"); });
		} else if (app === "codex") {
			if (phrase) clipboard.writeText(phrase);
			this.appPath(BUNDLES.codex, ["Codex", "ChatGPT"], (found) => {
				if (!found) return this.gone(view, "codex");
				const cli = CODEX_CLI.map((r) => path.join(found, r)).find((c) => { try { fs.accessSync(c, fs.constants.X_OK); return true; } catch (e) { return false; } });
				if (!cli) return view.toast("Codex's own launcher is missing; reinstall the Codex app.");
				const child = spawn(cli, ["app", folder], { detached: true, stdio: "ignore" });
				child.on("error", () => view.toast("Codex did not open that folder."));
				child.unref();
			});
		} else if (app === "cmux") {
			if (phrase) clipboard.writeText(phrase);
			execFile("open", ["-b", BUNDLES.cmux, folder], (err) => { if (err) this.gone(view, "cmux"); });
		} else if (app === "finder") {
			execFile("open", ["-R", folder], () => {});
		}
	}

	// An app by its bundle id, as Launch Services finds it, or in an Applications folder.
	appPath(bundle, names, done) {
		execFile("mdfind", [`kMDItemCFBundleIdentifier == '${bundle}'`], { timeout: 3000 }, (err, out) => {
			const found = (out || "").split("\n").find((l) => l.endsWith(".app"));
			if (found) return done(found);
			const dirs = ["/Applications", path.join(os.homedir(), "Applications")];
			done(dirs.flatMap((d) => names.map((n) => path.join(d, n + ".app"))).find((a) => fs.existsSync(a)) || null);
		});
	}

	// A button that changes something (preview page-actions): page_action.py,
	// beside status.py, checks it, does it and commits it, and says what it did.
	act(view, request) {
		const script = path.join(path.dirname(this.script()), "page_action.py");
		if (!fs.existsSync(script)) return view.toast("This page's actions need page_action.py beside status.py.");
		const child = execFile(this.python(), [script, "--workspace", this.root()], { cwd: this.root(), timeout: 120000 }, (err, out) => {
			let said = null;
			try { said = JSON.parse(out); } catch (e) {}
			view.toast((said && said.say) || "That did not work.");
			this.rebuild();
		});
		child.stdin.end(JSON.stringify(request));
	}

	// A link on the page: a note in this vault opens here, in a new tab;
	// anything else goes to macOS.
	follow(url) {
		if (url === this.last && Date.now() - this.lastAt < 1000) return;   // one click can report twice
		this.last = url;
		this.lastAt = Date.now();
		try {
			const u = new URL(url);
			const file = u.searchParams.get("file");
			if (u.protocol === "obsidian:" && u.hostname === "open" && file && u.searchParams.get("vault") === this.app.vault.getName()) {
				return this.app.workspace.openLinkText(file, "", "tab");
			}
			if (u.protocol === "file:") {
				const p = fileURLToPath(u);
				const rel = path.relative(this.vaultPath(), p);
				if (!rel.startsWith("..") && !path.isAbsolute(rel) && this.app.vault.getAbstractFileByPath(rel.split(path.sep).join("/"))) {
					return this.app.workspace.openLinkText(rel.split(path.sep).join("/"), "", "tab");
				}
				return shell.openPath(p);
			}
		} catch (e) {}
		shell.openExternal(url);
	}

	// MARK: parked projects and threads, out of the file explorer

	// Folders to hide, by their path in the vault: a thread whose note is
	// parked, a project whose hub is, and a project whose threads all are.
	parkedFolders() {
		const hidden = new Set();
		const projects = new Map();
		for (const f of this.app.vault.getMarkdownFiles()) {
			const parts = f.path.split("/");
			if (parts.length < 2 || parts[parts.length - 2] !== f.basename) continue;
			const fm = (this.app.metadataCache.getFileCache(f) || {}).frontmatter || {};
			const parked = String(fm.status || "").trim().toLowerCase() === "parked";
			const folder = parts.slice(0, -1).join("/");
			if (parts.length >= 4 && parts[parts.length - 3] === "Threads") {
				const project = parts.slice(0, -3).join("/");
				const p = projects.get(project) || { threads: 0, parked: 0 };
				p.threads += 1;
				if (parked) { p.parked += 1; hidden.add(folder); }
				projects.set(project, p);
			} else if (parked) {
				hidden.add(folder);
			}
		}
		for (const [project, p] of projects) if (p.threads && p.parked === p.threads) hidden.add(project);
		return [...hidden].sort();
	}

	hideParked() {
		if (!this.style) {
			this.style = document.createElement("style");
			this.style.id = "garrick-hide-parked";
			document.head.appendChild(this.style);
		}
		const folders = this.settings.hideParked ? this.parkedFolders() : [];
		const esc = (s) => s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
		this.style.textContent = folders.length
			? folders.map((f) => `.nav-folder:has(> .nav-folder-title[data-path="${esc(f)}"])`).join(",\n") + " { display: none; }"
			: "";
	}
};
// For tests/test_obsidian.py, which drives a view without Obsidian.
module.exports.StatusView = StatusView;

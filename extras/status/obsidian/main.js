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
//     and page_action.py for a button that changes something, then a toast on the page, the reply handed to the page
//     (window.GarrickActed, which shows a park or a wake at once) and a rebuild;
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
const KINDS = ["act", "app", "copy", "cmux", "launch", "menu", "open", "pick", "rebuild", "reveal", "save"];
const BUNDLES = { claude: "com.anthropic.claudefordesktop", codex: "com.openai.codex", cmux: "com.cmuxterm.app" };
const NAMES = { claude: "Claude", codex: "Codex", cmux: "cmux" };
const CODEX_CLI = ["Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex", "Contents/Resources/codex", "Contents/Resources/bin/codex"];
// A Claude that is not running drops a deep link while its window is still
// loading, so a cold Claude is started and the link waits for the window.
// Claude's own log writes `boot: done` once the window has loaded; where that
// log cannot be read, the fallback stands in and the link goes anyway. The
// same marks and the same waits as Garrick.swift's, which a test compares.
const CLAUDE_LOG = path.join(os.homedir(), "Library", "Logs", "Claude", "main.log");
const CLAUDE_READY = "boot: done";
const WAITS = { poll: 500, ceiling: 40000, settle: 1000, fallback: 15000 };
// What a launcher says when it is done, in Garrick.swift's words: every
// sentence names the phrase one way or another, so no launcher leaves the
// phrase to be rebuilt. Claude types it into the session, Codex and cmux put
// it on the clipboard and say so, and Finder, which can take neither, names
// it. tests/test_status_more.py compares the two hosts' sentences.
const SAYS = {
	opened: (app, name, phrase) =>
		!phrase ? `Opened ${app} in ${name}.`
			: app === "Claude" ? `Opened Claude in ${name} with “${phrase}” typed in. Press Enter to send it.`
				: `Opened ${app} in ${name}. The clipboard now holds “${phrase}”; paste it to resume.`,
	notOpened: (app, name, phrase) =>
		phrase ? `${app} did not open ${name}. The phrase that resumes it is “${phrase}”.` : `${app} did not open ${name}.`,
	finder: (name, phrase) =>
		phrase ? `Showed ${name} in Finder. Nothing was copied; the phrase that resumes it is “${phrase}”.`
			: `Showed ${name} in Finder.`,
	starting: (name) => `Starting Claude, then opening ${name}. This takes a few seconds.`,
	late: (name, phrase) =>
		phrase ? `Claude did not say its window was ready within forty seconds. Opened ${name} anyway; `
			+ `if the session came up empty, the phrase that resumes it is “${phrase}”.`
			: `Claude did not say its window was ready within forty seconds. Opened ${name} anyway.`,
};
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

// A file a link on the page may open, as Garrick.app's workspaceFile() checks
// it (#318): inside the workspace, still there, and with no symlink anywhere
// below the workspace's folder, the last part included; else null.
function workspaceFile(root, p) {
	if (!root || typeof p !== "string" || !path.isAbsolute(p)) return null;
	const base = path.resolve(root), named = path.resolve(p), rel = path.relative(base, named);
	if (!rel || rel.startsWith("..") || path.isAbsolute(rel)) return null;
	let at = base;
	for (const part of rel.split(path.sep)) {
		at = path.join(at, part);
		try { if (fs.lstatSync(at).isSymbolicLink()) return null; } catch (e) { return null; }
	}
	return named;
}

// What opening a file could run, install or follow rather than show, as
// Garrick.app's runsSomething() has it, here by name: an app or a bundle, a
// script or anything executable, an installer, a disk image, a profile, a
// shortcut, a workflow, a Terminal setting, a web or file location and a web
// page; and a Finder alias, known by its first bytes.
const RUNS = new Set(["app", "command", "tool", "terminal", "webloc", "inetloc", "fileloc", "workflow", "action", "pkg", "mpkg",
	"dmg", "iso", "sparseimage", "sparsebundle", "mobileconfig", "shortcut", "html", "htm", "xhtml", "webarchive", "sh", "bash",
	"zsh", "csh", "ksh", "py", "pyw", "rb", "pl", "php", "js", "mjs", "jar", "scpt", "scptd", "applescript", "bundle",
	"plugin", "framework", "kext", "prefpane", "saver", "service", "xpc", "appex", "qlgenerator"]);
const ALIAS = Buffer.from("book\0\0\0\0mark", "latin1");
function runsSomething(p) {
	if (RUNS.has(path.extname(p).slice(1).toLowerCase())) return true;
	let st;
	try { st = fs.statSync(p); } catch (e) { return true; }
	if (st.isDirectory()) return false;                       // a folder opens in Finder
	if (st.mode & 0o111) return true;                         // executable
	try {
		const fd = fs.openSync(p, "r"), head = Buffer.alloc(ALIAS.length);
		const n = fs.readSync(fd, head, 0, ALIAS.length, 0);
		fs.closeSync(fd);
		return n === ALIAS.length && head.equals(ALIAS);
	} catch (e) { return true; }
}

// A job's log, from its panel's Open log: a .log directly in the jobs folder.
function jobLog(p) {
	const set = process.env.GARRICK_JOBS_DIR;
	const jobs = path.resolve(set ? set.replace(/^~(?=$|\/)/, os.homedir()) : path.join(os.homedir(), "Library", "Logs", "garrick-jobs"));
	return path.extname(p) === ".log" && path.dirname(path.resolve(p)) === jobs;
}

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
		// GarrickReads tells the page this plugin answers a request that only reads,
		// so it may ask what is running (page_action.py's "operations"); GarrickReady
		// makes it ask now, since the page's script has already run by here. A plugin
		// without them is never asked, and the page works as it did before the record.
		this.web.addEventListener("dom-ready", () => {
			this.web.executeJavaScript("window.GarrickReadsMemory=true;window.GarrickReadsNotes=true;window.GarrickReads=true;window.GarrickReadsFiles=true;window.GarrickReady&&window.GarrickReady()").catch(() => {});
		});
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
		this.addCommand({ id: "catch-up", name: "Catch up", callback: () => this.catchUp() });
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

	// Catch up (#27), from the command palette: the page's own dialog in the
	// Garrick view, as its button beside Settings opens it. A view still
	// loading opens it once the page is ready.
	async catchUp() {
		await this.open(false);
		const view = this.views()[0];
		if (!view || !view.web) return;
		const run = () => view.web.executeJavaScript("window.GarrickCatchUp&&window.GarrickCatchUp.open()").catch(() => {});
		let loading = false;
		try { loading = !!(view.web.isLoading && view.web.isLoading()); } catch (e) {}
		if (loading) view.web.addEventListener("dom-ready", run, { once: true });
		else run();
	}

	async freshen(force) {
		let age = Infinity;
		try { age = Date.now() - fs.statSync(this.page()).mtimeMs; } catch (e) {}
		if (force || age >= MAX_AGE_MS) await this.rebuild();
	}

	// A rebuild asked for after a change (queue) while one runs follows it: the
	// one running may have read the workspace before the change.
	rebuild(queue) {
		const root = this.root();
		if (!root) return Promise.resolve(new Notice("No Garrick workspace found; name it in Settings › Garrick."));
		if (this.building) {
			if (queue) this.again = true;
			return this.building;
		}
		const notice = new Notice("Rebuilding Garrick's status page…", 0);
		const flags = (this.settings.flags || "").split(/\s+/).filter(Boolean);
		this.building = new Promise((resolve) => {
			execFile(this.python(), [this.script(), "--workspace", root, ...flags], { cwd: root, timeout: 120000 }, (err) => {
				notice.hide();
				this.building = null;
				if (err) new Notice("The status page did not rebuild; showing the last build.");
				if (!this.watcher) this.watch();
				resolve();
				if (this.again) {
					this.again = false;
					this.rebuild();
				}
			});
		});
		return this.building;
	}

	// MARK: the bridge, answered as Garrick.app answers it

	handle(view, body) {
		if (body.menu !== undefined) return;            // Garrick.app's menu bar: nothing to do here
		if (body.app) return view.toast("That setting is Garrick.app's own.");
		// Add your own work (#182): the folder picker, which also grants access, is Garrick.app's own.
		if (body.pick !== undefined) return view.toast("Only the Garrick app can open your folders. In Claude, ask it to look through the folder you keep your work in.");
		// Save a copy, on an earlier version of a work's file (#189): the Save panel is Garrick.app's own, so the
		// version goes into Downloads, which page_action.py does when no place is given.
		if (body.save && typeof body.save === "object" && body.save.act) return this.act(view, body.save.act);
		// A link to a project's hub or a thread's note (#318): Garrick.app opens it as the row does; here,
		// inside Obsidian, the note opens in Obsidian, as any other link to a note of this vault does.
		if (typeof body.open === "string") return this.follow(body.open);
		// Show both, on a drifted file (#323), reveals a shared copy through the zone's .shared/ link: Garrick.app's alone.
		if (body.reveal) return view.toast("Show both is Garrick.app's: open the page there to see the two copies in Finder.");
		// A Copy button's own text. A launch carries the phrase too, for a host
		// older than this one; here the launcher owns the clipboard and says
		// when it replaced it, so the copy is left to it and never happens twice.
		if (typeof body.copy === "string" && body.copy && typeof body.launch !== "string") clipboard.writeText(body.copy);
		if (typeof body.launch === "string" && typeof body.folder === "string") {
			this.launching = this.launch(view, body.launch, body.folder, typeof body.phrase === "string" ? body.phrase : "", !!body.dk);
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
	// session for you to send, only where Open in Claude cannot go through
	// page_action.py's `continue` (#180), which the page then sends as an act; Codex and cmux get the folder, and the phrase
	// goes on the clipboard; Finder shows the folder. Nothing is sent and no
	// command is typed into a terminal. cmux with the cmux extra's desk ready
	// (desk: the message says so) goes through page_action.py instead: a tab
	// in the folder that starts the assistant on the phrase.
	// Every route says on the page what it achieved, a failure included, and
	// the clipboard is replaced in one place only: where the launcher cannot
	// take the phrase itself and did open the folder, with the toast saying so.
	// Returns a promise that settles when there is nothing left to say, which
	// is what the tests wait on; handle() keeps it as this.launching.
	launch(view, app, p, phrase, desk) {
		const folder = this.inWorkspace(view, p);
		if (!folder) return Promise.resolve();
		const name = path.basename(folder);
		if (app === "cmux" && desk) return Promise.resolve(this.act(view, { verb: "open", folder, prompt: phrase }));
		if (app === "claude") {
			const url = "claude://code/new?folder=" + encodeURIComponent(folder) + (phrase ? "&q=" + encodeURIComponent(phrase) : "");
			return this.openInClaude(view, url, name, phrase);
		}
		if (app === "codex") {
			return new Promise((resolve) => this.appPath(BUNDLES.codex, ["Codex", "ChatGPT"], (found) => {
				if (!found) { this.gone(view, "codex"); return resolve(); }
				const cli = CODEX_CLI.map((r) => path.join(found, r)).find((c) => { try { fs.accessSync(c, fs.constants.X_OK); return true; } catch (e) { return false; } });
				if (!cli) {
					// Each build checks for this launcher, so the page does not offer
					// Codex without it; a page built before it went missing still can.
					view.toast("Codex's own launcher is missing; reinstall the Codex app. Rebuilding the page without it.");
					this.rebuild();
					return resolve();
				}
				const child = spawn(cli, ["app", folder], { detached: true, stdio: "ignore" });
				child.on("error", () => { view.toast(SAYS.notOpened("Codex", name, phrase)); resolve(); });
				child.on("spawn", () => {
					if (phrase) clipboard.writeText(phrase);   // it opened: the toast says the clipboard holds it
					view.toast(SAYS.opened("Codex", name, phrase));
					resolve();
				});
				child.unref();
			}));
		}
		if (app === "cmux") {
			return new Promise((resolve) => this.appPath(BUNDLES.cmux, ["cmux"], (found) => {
				if (!found) { this.gone(view, "cmux"); return resolve(); }
				execFile("open", ["-b", BUNDLES.cmux, folder], (err) => {
					if (err) { view.toast(SAYS.notOpened("cmux", name, phrase)); return resolve(); }
					if (phrase) clipboard.writeText(phrase);
					view.toast(SAYS.opened("cmux", name, phrase));
					resolve();
				});
			}));
		}
		if (app === "finder") {
			return new Promise((resolve) => execFile("open", ["-R", folder], (err) => {
				view.toast(err ? SAYS.notOpened("Finder", name, phrase) : SAYS.finder(name, phrase));
				resolve();
			}));
		}
		return Promise.resolve();
	}

	// A running Claude takes the link at once, as it always has. A cold one
	// would drop it while its window loads, so it is started first, its window
	// waited for, and the link sent then. It says it is starting, so a
	// ten-second gap does not look like nothing happened. Nothing is sent to
	// anybody: the phrase is typed into the new session, for you to send.
	openInClaude(view, url, name, phrase) {
		return new Promise((resolve) => this.appPath(BUNDLES.claude, ["Claude"], (found) => {
			if (!found) { this.gone(view, "claude"); return resolve(); }
			// Its own executable, not its name: "Usage for Claude" must not read as Claude.
			const exe = path.join(found, "Contents", "MacOS") + path.sep;
			execFile("pgrep", ["-f", exe], { timeout: 3000 }, (err, out) => {
				if ((out || "").trim()) return this.sendToClaude(view, url, name, phrase, null).then(resolve);
				const from = this.claudeLogSize();           // before it starts: only what it writes from here counts
				view.toast(SAYS.starting(name));
				execFile("open", ["-b", BUNDLES.claude], (e) => {
					if (e) { view.toast(SAYS.notOpened("Claude", name, phrase)); return resolve(); }
					this.claudeWindow(from, (how) => this.sendToClaude(view, url, name, phrase, how).then(resolve));
				});
			});
		}));
	}

	// Sends the link to a Claude whose window is up, and says what happened.
	// `how` is how a cold Claude's window was found, null for one already
	// running; a wait that ran out says the session may have come up empty.
	sendToClaude(view, url, name, phrase, how) {
		return new Promise((resolve) => execFile("open", [url], (err) => {
			view.toast(err ? SAYS.notOpened("Claude", name, phrase)
				: how === "late" ? SAYS.late(name, phrase) : SAYS.opened("Claude", name, phrase));
			resolve();
		}));
	}

	// Claude's log and how long the wait allows, as methods so a test can stand
	// in for them without reaching the real log or waiting forty seconds.
	claudeLogPath() { return CLAUDE_LOG; }

	waitTimes() { return WAITS; }

	// Where Claude's log stands now, so only what it writes after the app is
	// started is read. null where the log is not there at all.
	claudeLogSize() {
		try { return fs.statSync(this.claudeLogPath()).size; } catch (e) { return null; }
	}

	// Waits for a cold Claude's window, as Garrick.swift's awaitClaudeWindow():
	// the mark its log writes when the window has loaded, read from where the
	// log stood before the app was started, up to the ceiling. Never waits for
	// ever: every ending sends the link, and says which ending it was.
	claudeWindow(from, done) {
		const w = this.waitTimes();
		if (from === null) return setTimeout(() => done("assumed"), w.fallback);
		let waited = 0;
		const look = () => {
			waited += w.poll;
			let tail = "";
			try {
				const fd = fs.openSync(this.claudeLogPath(), "r");
				try {
					const size = fs.fstatSync(fd).size;
					if (size > from) {
						const buf = Buffer.alloc(size - from);
						fs.readSync(fd, buf, 0, buf.length, from);
						tail = buf.toString("utf8");
					}
				} finally { fs.closeSync(fd); }
			} catch (e) {
				return setTimeout(() => done("assumed"), w.fallback);   // rotated or gone: nothing to find
			}
			if (tail.includes(CLAUDE_READY)) return setTimeout(() => done("ready"), w.settle);
			if (waited >= w.ceiling) return done("late");
			setTimeout(look, w.poll);
		};
		setTimeout(look, w.poll);
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

	// A button that changes something: page_action.py,
	// beside status.py, checks it, does it and commits it, and says what it did.
	// Its own limits come first: a commit waits up to five minutes for the
	// wall check, so the plugin waits fifteen before it lets the request go.
	// Every request gets a reply on the page, a failed one too: the page shows
	// a request running until its reply comes.
	act(view, request) {
		const script = path.join(path.dirname(this.script()), "page_action.py");
		if (!fs.existsSync(script)) return this.acted(view, request, { ok: false, say: "This page's actions need page_action.py beside status.py." });
		const child = execFile(this.python(), [script, "--workspace", this.root()], { cwd: this.root(), timeout: 900000 }, (err, out) => {
			let said = null;
			try { said = JSON.parse(out); } catch (e) {}
			if (!said || typeof said !== "object") {
				said = { ok: false, say: err && err.killed ? "page_action.py had no answer after fifteen minutes and was stopped." : "That did not work." };
			}
			this.acted(view, request, said);
			if (this.rebuilds(request)) this.rebuild(true);
		});
		child.stdin.end(JSON.stringify(request));
	}

	// The page asking what is running (page_action.py's "operations"), how far
	// a copy or a move of a work's files has got ("files-progress", #189), what
	// Settings › Memory's unsaved values would do ("memory-preview", #108), or a
	// note for Explore's Preview ("note-read", #206), only reads: the reply goes
	// to the page, with no toast and no rebuild, or asking would rebuild the
	// page it asks from.
	reading(request) {
		return !!request && ["operations", "files-progress", "memory-preview", "note-read"].includes(request.verb);
	}

	// What changes nothing the page shows is not followed by a rebuild, which
	// would reload the page under the preview: a request that only reads, and
	// a note opened in its own app from it ("note-open"), which still toasts.
	rebuilds(request) {
		return !this.reading(request) && !(request && request.verb === "note-open");
	}

	// The reply: the toast, then the page, which shows a park or a wake at once
	// (the rebuild confirms it) and ends what it showed running.
	acted(view, request, said) {
		if (!this.reading(request)) view.toast(said.say || "That did not work.");
		if (view.web) {
			view.web.executeJavaScript(`(function(a){window.GarrickActed&&window.GarrickActed(a[0],a[1])})(${
				JSON.stringify([request, said]).replace(/</g, "\\u003c")})`).catch(() => {});
		}
	}

	// A link on the page, as Garrick.app follows one (#318): a job's log, the
	// one file outside the workspace the page links; a file of the workspace,
	// with no symlink anywhere below its folder, a note of this vault opening
	// here in a new tab, one that could run something shown in Finder, and
	// anything else opened by macOS; and the web, http and https only.
	// Anything else opens nothing.
	follow(url) {
		if (url === this.last && Date.now() - this.lastAt < 1000) return;   // one click can report twice
		this.last = url;
		this.lastAt = Date.now();
		let u;
		try { u = new URL(url); } catch (e) { return; }
		const file = u.searchParams.get("file");
		if (u.protocol === "obsidian:" && u.hostname === "open" && file && u.searchParams.get("vault") === this.app.vault.getName()) {
			return this.app.workspace.openLinkText(file, "", "tab");
		}
		if (u.protocol === "http:" || u.protocol === "https:") return shell.openExternal(url);
		if (u.protocol !== "file:") return;
		let p;
		try { p = fileURLToPath(u); } catch (e) { return; }
		if (jobLog(p)) return shell.openPath(p);
		const mine = workspaceFile(this.root(), p);
		if (!mine) return new Notice("That link leads outside this workspace, so nothing was opened.");
		// What could run something is shown in Finder before anything else is
		// asked of it, a file the vault holds too: Obsidian lists every file.
		if (runsSomething(mine)) {
			new Notice(path.basename(mine) + " could run something, so it is shown in Finder rather than opened.");
			return shell.showItemInFolder(mine);
		}
		const rel = path.relative(this.vaultPath(), mine);
		if (!rel.startsWith("..") && !path.isAbsolute(rel) && this.app.vault.getAbstractFileByPath(rel.split(path.sep).join("/"))) {
			return this.app.workspace.openLinkText(rel.split(path.sep).join("/"), "", "tab");
		}
		return shell.openPath(mine);
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

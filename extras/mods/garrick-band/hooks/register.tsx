import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Note, Thread, Wait, WaitPick } from '../types'

// Garrick blue, from docs/assets/garrick-mark.svg.
const BLUE = 0x3d73e0
const DEFAULT = 0x01000000
const PANE = 'garrick-resume'

const note = atom({ plugin: 'garrick-band', key: 'note' } as const, null)
const isHidden = atom({ plugin: 'garrick-band', key: 'isHidden' } as const, false)
const used = atom({ plugin: 'garrick-band', key: 'used' } as const, null)
const wait = atom({ plugin: 'garrick-band', key: 'wait' } as const, null)

// The mark, the cabinet, as a 4×2 cell tile, as tall as the band's two lines:
// a 4×4 grid of half-block pixels, two to a cell, each pixel about square. The
// spine and the closed compartment are drawn in the terminal's own text colour,
// so they read on light and dark; the open one is blue. A gap of one pixel is
// the wall.
const CABINET = ['I BB', 'I   ', 'I II', 'I II']
export const MARK = { columns: CABINET[0]!.length, rows: CABINET.length / 2 }

export function markCells(): string {
  const colour = (p: string) => (p === 'B' ? BLUE : DEFAULT)
  const words: number[] = []
  for (let row = 0; row < CABINET.length; row += 2) {
    for (let col = 0; col < MARK.columns; col++) {
      const up = CABINET[row]![col]!
      const down = CABINET[row + 1]![col]!
      if (up === ' ' && down === ' ') words.push(0x20, DEFAULT, DEFAULT)
      else if (up === down) words.push(0x2588, colour(up), DEFAULT)                 // █
      else if (down === ' ') words.push(0x2580, colour(up), DEFAULT)                // ▀
      else if (up === ' ') words.push(0x2584, colour(down), DEFAULT)                // ▄
      else words.push(0x2580, colour(up), colour(down))                             // ▀ over the other colour
    }
  }

  // Uint8Array.prototype.toBase64 is in the engine's runtime but not yet in ES2023's types.
  const bytes = new Uint8Array(Uint32Array.from(words).buffer) as Uint8Array & { toBase64(): string }

  return bytes.toBase64()
}

const basename = (path: string) => path.slice(path.lastIndexOf('/') + 1)
const parent = (path: string) => path.slice(0, path.lastIndexOf('/')) || '/'

// "Zones/Work/Acme/Threads/Acme Renewal" -> "Work › Acme › Acme Renewal"
export function label(relative: string): string {
  return relative
    .split('/')
    .filter(part => part !== 'Zones' && part !== 'Threads' && part !== '')
    .join(' › ')
}

// The frontmatter status, the Resume here block and its heading.
export function parseNote(text: string): Pick<Note, 'status' | 'heading' | 'resume'> {
  const status = /^---\n[\s\S]*?^status:\s*(\S+)[\s\S]*?^---$/m.exec(text)?.[1] ?? null
  const match = /^### (Resume here|Outcome)\s*$/m.exec(text)
  if (match === null) return { status, heading: null, resume: null }
  const start = match.index

  const body = text.slice(start).replace(/^### .*\n/, '')
  const end = body.search(/^#{2,3} /m)
  const resume = (end < 0 ? body : body.slice(0, end)).trim()

  return { status, heading: match[1]!, resume }
}

// How full the context window is, as a whole percentage: the status line's own
// figure, from $.session.usage()'s plain call, which counts no tokens. Null
// before the live window's first response, in a new session or one just
// compacted, when the API has none.
export function percentOf(context: { percent?: number } | null | undefined): number | null {
  const p = context?.percent

  return typeof p === 'number' && Number.isFinite(p) ? Math.round(p) : null
}

// Above this the figure is red: the point where it is time to wrap and clear.
export const FULL = 60

// What the band's buttons say to the assistant, in the person's own words, so
// the rules' "Open X" and "wrap X" phrases apply.
export function resumePrompt(n: Note): string {
  return `Open ${n.title}: read the ${n.heading ?? 'Resume here'} block in \`${n.rel}\` and tell me in two sentences where it stands and the next action.`
}

// At a project whose resume points are in its threads: where each one stands.
export function projectResumePrompt(n: Note): string {
  const notes = n.threads.map(t => `\`${t.rel}\``).join(', ')

  return `Open ${n.title}: read the Resume here block of each of its live threads (${notes}) and tell me in a sentence or two for each where it stands and the next action.`
}

// At a project kept in threads: thread-wrap works out from the session which
// thread the work was for, and says so when it was none.
export function projectWrapPrompt(n: Note): string {
  return `Wrap ${n.title}: wrap the thread this session worked on, and the hub \`${n.rel}\` too if its status changed. If the session touched no thread, say so and stop.`
}

export function wrapPrompt(n: Note): string {
  return `Wrap ${n.title}: rewrite the Resume here block in \`${n.rel}\` so it describes now, and add today's dated entry below it.`
}

// The Resume block for the pane: wikilinks become links to the file they name,
// or their label where none matches, so the renderer draws them as text a
// click opens rather than as brackets. An escaped pipe in a table is a link's.
export function paneMarkdown(markdown: string, resolve: (target: string) => string | null): string {
  return markdown.replace(/\[\[([^\]|\\]+)(?:\\?\|([^\]]+))?\]\]/g, (_, target: string, shown?: string) => {
    const words = shown ?? basename(target)
    const abs = resolve(target.trim())

    return abs ? `[${words}](${fileHref(abs)})` : words
  })
}

// Walk up from the session's folder to the workspace root (the folder holding
// System/rules.md); the first folder whose own <Folder>.md exists is the thread.
// The folder is the one the session started in ($.session.root()), not the
// shell's: a `cd` in a tool call moves $.session.cwd(), and the band would lose
// its thread after that turn.
async function findNote($: any): Promise<Note | null> {
  let dir: string = await $.session.root()
  const chain: string[] = []
  while (dir !== '/') {
    chain.push(dir)
    if (await $.fs.exists(`${dir}/System/rules.md`)) break
    dir = parent(dir)
  }
  const root = chain[chain.length - 1]
  if (root === undefined || !(await $.fs.exists(`${root}/System/rules.md`))) return null

  for (const folder of chain.slice(0, -1)) {
    const path = `${folder}/${basename(folder)}.md`
    if (!(await $.fs.exists(path))) continue
    const text: string = await $.fs.read(path)
    const where = label(folder.slice(root.length + 1))
    const rel = path.slice(root.length + 1)

    const parsed = parseNote(text)
    const threads = parsed.resume === null ? await liveThreads($, folder, root) : []

    return { path, rel, where, title: basename(folder), ...parsed, threads, ...(await openers($, chain, folder, (await launchers($, root)).on)) }
  }
  // No thread note above the folder (System/, the root, a wiki): nothing to
  // resume or wrap, but Finder still shows the folder and, in a wiki, Obsidian
  // opens its index.
  const here = chain[0]!
  const where = label(here.slice(root.length + 1))
  const index = `${here}/wiki/index.md`
  const target = (await $.fs.exists(index)) ? index : here
  const open = await openers($, chain, here, (await launchers($, root)).on)

  return {
    path: target, rel: target.slice(root.length + 1), where: where || 'Home', title: where || 'Home',
    status: null, heading: null, resume: null,
    finder: open.finder, obsidian: open.obsidian && target === index, threads: [],
  }
}

// A project's live threads: Threads/<Thread>/<Thread>.md with a Resume here
// block, not done or parked, by name.
async function liveThreads($: any, folder: string, root: string): Promise<Thread[]> {
  const entries = await $.fs.list(`${folder}/Threads`).catch(() => [])
  const out: Thread[] = []
  for (const e of [...entries].sort((a: any, b: any) => a.name.localeCompare(b.name))) {
    if (e.kind !== 'dir' || e.name.startsWith('.') || e.name.startsWith('_')) continue
    const path = `${folder}/Threads/${e.name}/${e.name}.md`
    if (!(await $.fs.exists(path))) continue
    const parsed = parseNote(await $.fs.read(path))
    if (parsed.resume === null || parsed.status === 'done' || parsed.status === 'parked') continue
    out.push({ title: e.name, rel: path.slice(root.length + 1), heading: parsed.heading, resume: parsed.resume.slice(0, 20000) })
  }

  return out
}

// Settings › Opening a thread, as System/garrick-settings.json keeps it and
// status.py's shared_launchers() reads it: "launchers" is {name: true or
// false}, a name left out being on, or a list of the names switched on;
// "default" is what clicking a thread does, "note" when it names no launcher.
// The band can run three of them: the note in Obsidian, Finder, and cmux
// through the desk. Nothing saved, or nothing that reads, leaves every one on
// and no default, so a hand-edited file never empties the band.
export const LAUNCH_KEYS = ['note', 'finder', 'cmux', 'codex', 'claude'] as const
export type Launchers = { on: Record<string, boolean>; default: string | null }

export function launcherSettings(text: string | null): Launchers {
  let data: any = null
  try {
    data = text === null ? null : JSON.parse(text)
  } catch {
    data = null
  }
  const saved = data !== null && typeof data === 'object' ? data.launchers : undefined
  const on: Record<string, boolean> = {}
  if (saved !== null && typeof saved === 'object' && !Array.isArray(saved)) {
    for (const k of LAUNCH_KEYS) on[k] = !(k in saved) || saved[k] === true
  } else if (Array.isArray(saved)) {
    for (const k of LAUNCH_KEYS) on[k] = saved.includes(k)
  } else {
    for (const k of LAUNCH_KEYS) on[k] = true

    return { on, default: null }
  }

  return { on, default: (LAUNCH_KEYS as readonly string[]).includes(data.default) ? data.default : 'note' }
}

const launchers = async ($: any, root: string) =>
  launcherSettings((await $.fs.read(`${root}/System/garrick-settings.json`).catch(() => null)) as string | null)

const ALL_ON: Record<string, boolean> = Object.fromEntries(LAUNCH_KEYS.map(k => [k, true]))

// Finder wherever macOS's `open` is there; Obsidian when it is installed and a
// folder from the note up to the workspace root is a vault (holds .obsidian).
// Each only when Settings › Opening a thread has it switched on: Obsidian is
// the note's own launcher, `note`.
async function openers($: any, chain: string[], folder: string, switched: Record<string, boolean> = ALL_ON): Promise<Pick<Note, 'finder' | 'obsidian'>> {
  const open: boolean = await $.fs.exists('/usr/bin/open')
  if (!open) return { finder: false, obsidian: false }
  let inVault = false
  if (switched.note !== false) {
    const home: string = (await $.env.get('HOME')) ?? ''
    const installed = (await $.fs.exists('/Applications/Obsidian.app')) || (await $.fs.exists(`${home}/Applications/Obsidian.app`))
    for (const dir of installed ? chain.slice(chain.indexOf(folder)) : []) {
      if (await $.fs.exists(`${dir}/.obsidian`)) {
        inVault = true
        break
      }
    }
  }

  return { finder: switched.finder !== false, obsidian: inVault }
}

export const switchedOff = (app: 'Finder' | 'Obsidian') => `${app} is switched off in Settings › Opening a thread.`

export const obsidianUrl = (abs: string) => 'obsidian://open?path=' + encodeURIComponent(abs)

// The band's actions, shared by its buttons and /garrick.
const openNote = ($: any, n: Note) => $.ui.open({ id: PANE, title: n.title, focus: true, closeOnEscape: true })
const resume = ($: any, n: Note) => $.prompt.submit({ text: n.resume ? resumePrompt(n) : projectResumePrompt(n), asUser: true })
const resumable = (n: Note | null): n is Note => n !== null && (n.resume !== null || n.threads.length > 0)
const wrap = ($: any, n: Note) => $.prompt.submit({ text: n.resume ? wrapPrompt(n) : projectWrapPrompt(n), asUser: true })
// The cleared conversation's figure is not the new one's: none until its first reply.
const clear = async ($: any) => {
  await $.command.run({ command: 'clear' })
  await update($, used, () => null)
}
async function opener($: any, args: string[], app: string) {
  const { exitCode } = await $.process.run(['/usr/bin/open', ...args])
  if (exitCode !== 0) $.ui.toast(`${app} did not open the note.`)
}
const finder = ($: any, n: Note) => opener($, ['-R', n.path], 'Finder')
const obsidian = ($: any, n: Note) => opener($, [obsidianUrl(n.path)], 'Obsidian')

async function measure($: any) {
  // A Claude Code older than the usage call shows no figure rather than failing the turn.
  let usage = null
  try {
    usage = await $.session.usage()
  } catch {
    usage = null
  }
  await update($, used, () => percentOf(usage?.context))
}

async function refresh($: any) {
  const found = await findNote($).catch(() => null)
  last = found
  await update($, note, () => found)
  await measure($)
}

// The note the band last found, kept by the module. A /clear starts a new
// conversation with no session.start, and its atoms start empty, so `note`
// reads null until that conversation's first turn.complete; meanwhile the band
// draws from this, with no figure, since `used` starts empty too. Undefined
// until a search has run in this module, which then searches once; a folder
// with no note above it keeps null and never searches again, so a render
// costs no file read.
let last: Note | null | undefined = undefined
let finding: Promise<Note | null> | null = null

async function noteOf($: any): Promise<Note | null> {
  const n = await read($, note)
  if (n !== null) return n
  if (last !== undefined) return last
  finding ??= findNote($).catch(() => null).then(found => (last ??= found))

  return finding
}

// --- Clickable paths -------------------------------------------------------
// Every file and folder in the workspace, relative to its root, by basename.
// find never follows symlinks, so a cloud folder linked into the workspace is
// never walked.
type Index = { root: string; byName: Map<string, string[]> }
let index: Index | null = null

export function buildIndex(root: string, listing: string): Index {
  const byName = new Map<string, string[]>()
  for (const line of listing.split('\n')) {
    if (!line.startsWith(root + '/')) continue
    const rel = line.slice(root.length + 1)
    const name = basename(rel)
    byName.set(name, [...(byName.get(name) ?? []), rel])
  }

  return { root, byName }
}

async function findRoot($: any): Promise<string | null> {
  let dir: string = await $.session.cwd()
  while (dir !== '/') {
    if (await $.fs.exists(`${dir}/System/rules.md`)) return dir
    dir = parent(dir)
  }

  return null
}

async function reindex($: any) {
  const root = await findRoot($)
  if (root === null) return
  const prune = ['.git', 'node_modules', '__pycache__', '.obsidian', '.trash']
  const args = prune.flatMap((name, i) => (i === 0 ? ['-name', name] : ['-o', '-name', name]))
  const { exitCode, stdout } = await $.process.run(['find', root, '(', ...args, ')', '-prune', '-o', '-print'])
  if (exitCode === 0) index = buildIndex(root, stdout)
}

// The workspace-relative path a code span names, or null. Bare names and partial
// paths match by suffix; an ellipsis falls back to the basename. Ambiguity
// prefers the session's folder, then gives up.
export function lookup(idx: Index, span: string, cwdRel: string): string | null {
  const p = span.replace(/:\d+(:\d+)?$/, '').replace(/^\.\//, '').replace(/\/$/, '')
  const tail = p.includes('…') ? basename(p) : p
  const hits = (idx.byName.get(basename(tail)) ?? []).filter(rel => rel === tail || rel.endsWith('/' + tail))
  if (hits.length === 1) return hits[0]!
  const near = hits.filter(rel => cwdRel !== '' && rel.startsWith(cwdRel + '/'))

  return near.length === 1 ? near[0]! : null
}

const looksLikePath = (s: string) =>
  !/[\n`<>|*]/.test(s) && !s.startsWith('-') && (s.includes('/') || /\.[A-Za-z0-9]{1,5}(:\d+)?$/.test(s))

export const fileHref = (abs: string) => 'file://' + abs.split('/').map(encodeURIComponent).join('/')

// Rewrites `path` code spans outside fences into [`path`](file://...) links.
export async function linkify(text: string, resolve: (span: string) => Promise<string | null>): Promise<string> {
  const parts = text.split(/(^```[\s\S]*?^```)/m)
  for (let i = 0; i < parts.length; i += 2) {
    const part = parts[i]!
    let out = ''
    let at = 0
    for (const m of part.matchAll(/(?<!\[)`([^`\n]+)`(?!\]\()/g)) {
      const span = m[1]!
      const abs = looksLikePath(span) ? await resolve(span) : null
      out += part.slice(at, m.index) + (abs ? `[\`${span}\`](${fileHref(abs)})` : m[0])
      at = m.index + m[0].length
    }
    parts[i] = out + part.slice(at)
  }

  return parts.join('')
}

async function resolver($: any) {
  const cwd: string = await $.session.cwd()
  const home: string = (await $.env.get('HOME')) ?? ''

  return async (span: string): Promise<string | null> => {
    const bare = span.replace(/:\d+(:\d+)?$/, '')
    if (bare.startsWith('/') || bare.startsWith('~/')) {
      const abs = bare.startsWith('~/') ? home + bare.slice(1) : bare

      return (await $.fs.exists(abs)) ? abs.replace(/\/$/, '') : null
    }
    if (index === null) return null
    const cwdRel = cwd.startsWith(index.root + '/') ? cwd.slice(index.root.length + 1) : ''
    const rel = lookup(index, span, cwdRel)
    if (rel !== null) return `${index.root}/${rel}`
    // Written this turn, not indexed yet.
    for (const base of [cwd, index.root]) {
      if (await $.fs.exists(`${base}/${bare}`)) return `${base}/${bare}`.replace(/\/$/, '')
    }

    return null
  }
}

// --- While you wait ---------------------------------------------------------
// Once a turn has run past the threshold, one line offers something to do
// elsewhere, from System/tools/next_up.py. Nothing here reaches the running
// session: opening runs cmux, Obsidian or Finder, and ticking runs
// page_action.py on stdin, as the status page does. A tick in the zone the turn
// works in waits for the turn to end, so the two commits never meet. Whether
// the band's letter keys fire mid-turn is not settled, so the actions are
// /garrick next, open, tick and later, which run at once mid-turn, and the
// same words drawn as buttons for a click.
export const WAIT_DEFAULTS = { on: true, threshold: 45 }
const WAIT_LIMITS = [10, 600] as const
const WAIT_FRESH_MS = 60_000

// Settings › While you wait, as System/garrick-settings.json keeps it; what
// does not read is the default, so a hand-edited file never stops the band.
export function waitSettings(text: string | null): { on: boolean; threshold: number } {
  let saved: any = null
  try {
    saved = text === null ? null : JSON.parse(text)?.['while-you-wait']
  } catch {
    saved = null
  }
  const on = typeof saved?.on === 'boolean' ? saved.on : WAIT_DEFAULTS.on
  const t = saved?.threshold
  const threshold = Number.isInteger(t) && t >= WAIT_LIMITS[0] && t <= WAIT_LIMITS[1] ? t : WAIT_DEFAULTS.threshold

  return { on, threshold }
}

// Parked since #247 as a preview feature: off unless System/garrick-flags.json
// switches it on, {"while-you-wait": true}, read as status.py's preview_flags()
// reads it, so only a true counts and a file that does not read leaves it off.
// Off, no line shows and the four words say so.
export const WAIT_FLAG = 'while-you-wait'
export const waitOff = 'While you wait is a preview feature, and it is off. "while-you-wait": true in System/garrick-flags.json switches it on.'

export function previewOn(text: string | null, flag: string): boolean {
  try {
    const data = text === null ? null : JSON.parse(text)

    return data !== null && typeof data === 'object' && !Array.isArray(data) && data[flag] === true
  } catch {
    return false
  }
}

const waitPreview = async ($: any, root: string) =>
  previewOn((await $.fs.read(`${root}/System/garrick-flags.json`).catch(() => null)) as string | null, WAIT_FLAG)

// The workspace root a note was found under, and the zone of the session.
export const rootOf = (n: Note) => (n.rel === '' ? n.path : n.path.slice(0, n.path.length - n.rel.length - 1))
export const zoneOf = (rel: string) => /^Zones\/([^/]+)\//.exec(rel)?.[1] ?? null

// next_up.py's command: the session's zone, and the folder of the thread or
// project the session is in, which is never offered.
export function nextUpArgv(n: Note): string[] {
  const root = rootOf(n)
  const zone = zoneOf(n.rel)
  const own = n.rel.startsWith('Zones/') && n.rel.endsWith(`/${n.title}.md`)

  return ['python3', `${root}/System/tools/next_up.py`, '--root', root, ...(zone ? ['--zone', zone] : []),
    ...(own ? ['--exclude', parent(n.rel)] : [])]
}

export const pageActionArgv = (root: string) => ['python3', `${root}/System/status/page_action.py`, '--workspace', root]

// The pick on show, or null.
export const shownPick = (w: Wait | null): WaitPick | null => (w === null || w.hidden ? null : w.picks[w.index] ?? null)

let running: string | null = null          // the main loop's turn, while it runs
let timer: { cancel: () => void } | null = null
let held: { pick: WaitPick; root: string }[] = []     // ticks waiting for the turn to end

async function nextUp($: any): Promise<WaitPick[]> {
  const n = await noteOf($)
  if (n === null) return []
  const argv = nextUpArgv(n)
  if (!(await $.fs.exists(argv[1]!))) return []
  const { exitCode, stdout } = await $.process.run(argv, { timeoutMs: 20_000 }).catch(() => ({ exitCode: 1, stdout: '' }))
  if (exitCode !== 0) return []
  try {
    const data = JSON.parse(stdout)

    return data.on === false || !Array.isArray(data.picks) ? [] : data.picks
  } catch {
    return []
  }
}

async function offer($: any, turnId: string) {
  if (running !== turnId) return
  const picks = await nextUp($)
  if (running !== turnId || picks.length === 0) return
  const at = await $.clock.now()
  await update($, wait, () => ({ turnId, picks, index: 0, at, hidden: false, shown: [picks[0]!.id] }))
}

async function waitNext($: any): Promise<string> {
  const w = await read($, wait)
  if (w === null || running === null) return 'Nothing is on offer: the line shows once a turn has run a while.'
  const now = await $.clock.now()
  let picks = w.picks
  let index = w.index + 1
  if (now - w.at > WAIT_FRESH_MS) {
    picks = (await nextUp($)).filter(p => !w.shown.includes(p.id))
    index = 0
  }
  const pick = picks[index]
  if (pick === undefined) {
    await update($, wait, x => (x === null ? null : { ...x, hidden: true }))

    return 'Nothing else is waiting.'
  }
  await update($, wait, x => (x === null ? null : { ...x, picks, index, at: picks === w.picks ? x.at : now, hidden: false, shown: [...x.shown, pick.id] }))

  return `While you wait: ${pick.say}`
}

async function pageAction($: any, root: string, req: object): Promise<{ ok: boolean; say: string }> {
  const { exitCode, stdout, stderr } = await $.process.run(pageActionArgv(root), { stdin: JSON.stringify(req), timeoutMs: 120_000 })
    .catch((err: unknown) => ({ exitCode: 1, stdout: '', stderr: String(err) }))
  try {
    const reply = JSON.parse(String(stdout).trim().split('\n').pop() ?? '')

    return { ok: reply.ok === true, say: String(reply.say ?? '') }
  } catch {
    return { ok: false, say: exitCode === 0 ? 'page_action.py gave no answer' : String(stderr).trim().split('\n').pop() ?? '' }
  }
}

// The order While you wait's open tries the launchers in: the default first,
// then the band's own order, cmux, the note, Finder, keeping those switched
// on. With nothing saved, as before Settings › Opening a thread existed: cmux,
// the note, then the Mac's default app ('app').
export function waitOrder(l: Launchers): string[] {
  if (l.default === null) return ['cmux', 'note', 'app']
  const order = [l.default, 'cmux', 'note', 'finder'].filter(k => l.on[k] === true)

  return order.filter((k, i) => order.indexOf(k) === i)
}

// Opens the pick elsewhere, the way Settings › Opening a thread says: its
// thread's own cmux tab where the desk is installed (an Inbox opens a tab at
// the root on "process the inbox"), its note in Obsidian when it sits in a
// vault, or Finder; the default first, then the first of the others switched
// on that can open it here.
async function waitOpen($: any): Promise<string> {
  const pick = shownPick(await read($, wait))
  const n = await noteOf($)
  if (pick === null || n === null || pick.note === null) return 'Nothing is on offer to open.'
  const root = rootOf(n)
  const abs = `${root}/${pick.note}`
  const name = pick.thread ?? pick.project ?? basename(pick.note)
  const run = async (argv: string[], said: string) => {
    const { exitCode } = await $.process.run(argv).catch(() => ({ exitCode: 1 }))

    return exitCode === 0 ? said : 'It did not open.'
  }
  for (const way of waitOrder(await launchers($, root))) {
    if (way === 'cmux') {
      const desk = (await $.fs.exists(`${root}/System/status/page_action.py`)) && (await $.fs.exists(`${root}/System/cmux/desk.py`))
      if (desk && pick.zone !== null && pick.project !== null) {
        const reply = await pageAction($, root, { verb: 'open', zone: pick.zone, project: pick.project, ...(pick.thread ? { thread: pick.thread } : {}) })
        if (reply.ok) return reply.say || `Opened ${pick.thread ?? pick.project} in cmux.`
      }
      if (desk && pick.source === 'inbox') {
        const reply = await pageAction($, root, { verb: 'open', folder: root, prompt: 'process the inbox' })
        if (reply.ok) return reply.say || 'Opened a tab on "process the inbox".'
      }
    } else if (way === 'note') {
      if (abs.endsWith('.md') && (await openers($, chainOf(abs, root), parent(abs))).obsidian) return run(['/usr/bin/open', obsidianUrl(abs)], `Opened ${name} in Obsidian.`)
    } else if (way === 'finder') {
      // A folder, such as an Inbox, opens in Finder; a file is shown in its folder.
      const file = /\.[A-Za-z0-9]{1,5}$/.test(basename(abs))
      if (await $.fs.exists('/usr/bin/open')) return run(['/usr/bin/open', ...(file ? ['-R'] : []), abs], `Opened ${name} in Finder.`)
    } else if (way === 'app') {
      return run(['/usr/bin/open', abs], `Opened ${name}.`)
    }
  }

  return 'Nothing switched on in Settings › Opening a thread can open it here.'
}

// The folders from a file's own up to the root, as findNote walks them.
function chainOf(abs: string, root: string): string[] {
  const out: string[] = []
  for (let dir = parent(abs); dir.length >= root.length && dir !== '/'; dir = parent(dir)) out.push(dir)

  return out
}

async function tick($: any, pick: WaitPick, root: string): Promise<string> {
  const reply = await pageAction($, root, pick.tick!)

  return reply.ok ? reply.say || 'Ticked.' : `Not ticked: ${reply.say}`
}

async function waitTick($: any): Promise<string> {
  const w = await read($, wait)
  const pick = shownPick(w)
  const n = await noteOf($)
  if (pick === null || n === null) return 'Nothing is on offer to tick.'
  if (!pick.tick) return 'Only a Todo line can be ticked.'
  const root = rootOf(n)
  if (!(await $.fs.exists(pageActionArgv(root)[1]!))) return 'Ticking needs the status page extra, System/status/page_action.py.'
  // The rest of the list stays on offer; the ticked line goes from it.
  await update($, wait, x => (x === null ? null : { ...x, picks: x.picks.filter(p => p.id !== pick.id), index: Math.min(x.index, Math.max(0, x.picks.length - 2)), hidden: x.picks.length <= 1 }))
  const zone = zoneOf(n.rel)
  if (running !== null && (zone === null || zone === pick.zone)) {
    held.push({ pick, root })

    return `Ticks when the turn ends, since it works in ${pick.zone}: ${pick.say}`
  }

  return tick($, pick, root)
}

async function waitLater($: any): Promise<string> {
  await update($, wait, x => (x === null ? null : { ...x, hidden: true }))

  return 'Put away for this turn.'
}

const STATUS_COLOR: Record<string, string> = { active: 'green', parked: 'yellow', done: 'gray' }

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // immediate: typed while a turn runs, it answers at once instead of
    // waiting for the turn to end.
    await $.command.register({
      name: 'garrick',
      description: 'Show the Garrick band; "hide" it, "resume" or "wrap" the thread, "note" shows its Resume here block, "finder" or "obsidian" opens the note; with the While you wait preview on, "next", "open", "tick" or "later" for what it suggests',
      argumentHint: '[hide|resume|wrap|note|finder|obsidian|next|open|tick|later]',
      immediate: true,
    })
    await update($, wait, () => null)
    await refresh($)
    await reindex($).catch(() => undefined)

    return next(e)
  })

  // The main loop's turn: the While you wait line, once it has run past the
  // threshold, where the preview is switched on.
  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) {
      running = e.turnId
      timer?.cancel()
      timer = null
      await update($, wait, () => null).catch(() => undefined)
      const n = await noteOf($)
      const previewed = n !== null && (await waitPreview($, rootOf(n)))
      const text = previewed ? ((await $.fs.read(`${rootOf(n)}/System/garrick-settings.json`).catch(() => null)) as string | null) : null
      const chosen = waitSettings(text)
      const turnId = e.turnId
      if (previewed && chosen.on) timer = $.clock.after(chosen.threshold * 1000, () => void offer($, turnId).catch(() => undefined))
    }

    return next(e)
  })

  // The note may have been rewritten by the turn (thread-wrap, an edit), files
  // may have been added, and the context has grown.
  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined) {
      timer?.cancel()
      timer = null
      running = null
      const was = shownPick(await read($, wait))
      await update($, wait, () => null)
      const due = held
      held = []
      const said = [] as string[]
      for (const t of due) said.push(await tick($, t.pick, t.root).catch(() => 'A tick did not go through.'))
      if (was !== null || said.length) $.ui.toast(['The turn has finished.', ...said].join(' '))
    }
    await refresh($)
    await reindex($).catch(() => undefined)

    return next(e)
  })

  // After a compaction the API has no figure until the next response, so the
  // band shows none rather than the one from before.
  on('session.compact', async ($, e, next) => {
    const done = await next(e)
    await measure($).catch(() => undefined)

    return done
  })

  // A /clear, typed or from the band, ends the conversation and goes on in a
  // new one with no session.start; so does a resume. The new conversation has
  // no figure until its first reply, so the band shows none rather than the
  // old one's, which may be red and tell the person to clear again. Its atoms
  // start empty, `note` too, so the band draws from noteOf()'s fallback.
  on('session.end', async ($, e, next) => {
    await update($, used, () => null).catch(() => undefined)

    return next(e)
  })

  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    const text = await linkify(e.props.text, await resolver($))

    return text === e.props.text ? next(e) : next({ ...e, props: { ...e.props, text } })
  })

  // /garrick shows the band and /garrick hide takes it away; any other word
  // shows it too. Not a toggle: the [-] beside the band is Claude Code's own
  // fold, which a mod can neither read nor undo, so a toggle would guess wrong.
  on('command.run', { command: 'garrick' }, async ($, e) => {
    const arg = String(e.args ?? '').trim().toLowerCase()
    if (arg === 'hide') {
      await update($, isHidden, () => true)

      return { text: 'Garrick band hidden. /garrick brings it back.' }
    }
    await update($, isHidden, () => false)
    const shown = 'Garrick band shown. If it is folded under [+], ctrl+x ctrl+a opens it.'
    if (arg === '' || arg === 'show') return { text: shown }
    const current = await noteOf($)
    if (['next', 'open', 'tick', 'later'].includes(arg)) {
      if (current === null || !(await waitPreview($, rootOf(current)))) return { text: waitOff }
      if (arg === 'next') return { text: await waitNext($) }
      if (arg === 'open') return { text: await waitOpen($) }
      if (arg === 'tick') return { text: await waitTick($) }

      return { text: await waitLater($) }
    }
    if (arg === 'finder' || arg === 'obsidian') {
      if (current === null || current.path === '') return { text: 'No project or thread note above this folder.' }
      const switched = (await launchers($, rootOf(current))).on
      if (switched[arg === 'finder' ? 'finder' : 'note'] === false) return { text: switchedOff(arg === 'finder' ? 'Finder' : 'Obsidian') }
      if (!current[arg]) return { text: arg === 'finder' ? 'Finder is not available here.' : 'This note is not in an Obsidian vault, or Obsidian is not installed.' }
      void (arg === 'finder' ? finder($, current) : obsidian($, current))

      return { text: `Opening ${current.title} in ${arg === 'finder' ? 'Finder' : 'Obsidian'}.` }
    }
    if (!resumable(current)) return { text: 'No Resume here block above this folder.' }
    if (arg === 'note') {
      await openNote($, current)

      return { text: 'Resume here pane opened.' }
    }
    if (arg === 'resume' || arg === 'wrap') {
      // Submitted once this hook has answered: a prompt submitted from inside a
      // command.run hook would wait on the very turn the hook is holding.
      $.clock.after(50, () => void (arg === 'resume' ? resume($, current) : wrap($, current)))

      return { text: `${arg === 'resume' ? 'Resuming' : 'Wrapping'} ${current.title}.` }
    }

    return { text: `Unknown argument "${arg}": use hide, resume, wrap, note, finder, obsidian, next, open, tick or later.` }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const current = await noteOf($)
    if (e.props.hasSurvey || current === null || (await read($, isHidden))) return next(e)

    const percent = await read($, used)
    // Only ever set where the preview is on: offer() runs from turn.start's timer.
    const offered = e.props.isWorking ? shownPick(await read($, wait)) : null
    const { Box, Text, Button, ...rest } = $.ui.resolve(e)
    const Raster = (rest as any).Raster
    // Without Raster, the same cabinet in two rows of text.
    const mark = Raster ? (
      <Raster key="mark" columns={MARK.columns} rows={MARK.rows} cells={markCells()} />
    ) : (
      <Box flexDirection="column">
        <Text>█ <Text color="#3d73e0">▀▀</Text></Text>
        <Text>█ ██</Text>
      </Box>
    )

    // Two lines: where the session is, then what can be done there, every
    // button at one weight. While you wait, a preview, adds its line between.
    return (
      <Box flexDirection="row" gap={1}>
        {mark}
        <Box flexDirection="column" flexGrow={1} flexShrink={1}>
          <Text wrap="truncate-end">
            <Text bold color="#3d73e0">Garrick</Text>
            <Text dimColor> · </Text>
            <Text bold>{current.where}</Text>
            {current.status && <Text color={STATUS_COLOR[current.status] ?? 'gray'}> {current.status}</Text>}
            {percent !== null && <Text dimColor> · </Text>}
            {percent !== null && (
              <Text {...(percent > FULL ? { color: 'red' } : { dimColor: true })}>{percent}%</Text>
            )}
          </Text>
          {offered !== null && (
            <Box flexDirection="row" gap={1}>
              <Box flexShrink={1}>
                <Text wrap="truncate-end">
                  <Text color="#3d73e0">While you wait: </Text>
                  {offered.say}
                </Text>
              </Box>
              <Text dimColor>/garrick</Text>
              <Button key="wait-open" label="open" plain onPress={() => void waitOpen($).then(t => $.ui.toast(t))} />
              <Button key="wait-next" label="next" plain dimColor onPress={() => void waitNext($)} />
              {offered.tick && <Button key="wait-tick" label="tick" plain dimColor onPress={() => void waitTick($).then(t => $.ui.toast(t))} />}
              <Button key="wait-later" label="later" plain dimColor onPress={() => void waitLater($)} />
            </Box>
          )}
          <Box flexDirection="row" gap={2}>
            {resumable(current) && current.status !== 'done' && (
              <Button key="wrap" label="Wrap" hotkey="w" plain onPress={() => void wrap($, current)} />
            )}
            <Button key="clear" label="Clear" hotkey="c" plain onPress={() => void clear($)} />
            {current.finder && <Button key="finder" label="Finder" hotkey="f" plain onPress={() => void finder($, current)} />}
            {current.obsidian && <Button key="obsidian" label="Obsidian" hotkey="o" plain onPress={() => void obsidian($, current)} />}
          </Box>
        </Box>
      </Box>
    )
  })

  // The block as the renderer draws a reply: tables, emphasis, and links a
  // click opens, wikilinks and file paths included. For the whole note, typeset,
  // the pane offers Obsidian and Finder as the band does.
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Markdown } = $.ui.resolve(e)
    const current = await noteOf($)
    if (!resumable(current)) return <Text dimColor>No Resume here block found.</Text>
    const byTarget = (target: string) => {
      if (index === null) return null
      const rel = lookup(index, /\.[A-Za-z0-9]{1,5}$/.test(target) ? target : `${target}.md`, '')

      return rel === null ? null : `${index.root}/${rel}`
    }
    // The note's own block, or at a project kept in threads, each thread's.
    const blocks: Thread[] = current.resume !== null
      ? [{ title: current.heading ?? 'Resume here', rel: current.rel, heading: current.heading, resume: current.resume }]
      : current.threads.map(t => ({ ...t, title: `${t.title} · ${t.heading ?? 'Resume here'}` }))
    const resolve = await resolver($)
    const texts = await Promise.all(blocks.map(b => linkify(paneMarkdown(b.resume.slice(0, 20000), byTarget), resolve)))

    return (
      <Box flexDirection="column" gap={1}>
        {blocks.map((b, i) => (
          <Box key={`block-${i}`} flexDirection="column" gap={1}>
            <Box flexDirection="row" gap={2}>
              <Text bold color="#3d73e0">{b.title}</Text>
              <Text dimColor wrap="truncate-end">{b.rel}</Text>
            </Box>
            <Markdown text={texts[i]!} />
          </Box>
        ))}
        {(current.obsidian || current.finder) && (
          <Box flexDirection="row" gap={2}>
            {current.obsidian && <Button key="pane-obsidian" label="Open in Obsidian" hotkey="o" plain onPress={() => void obsidian($, current)} />}
            {current.finder && <Button key="pane-finder" label="Reveal in Finder" hotkey="f" plain dimColor onPress={() => void finder($, current)} />}
          </Box>
        )}
      </Box>
    )
  })
}

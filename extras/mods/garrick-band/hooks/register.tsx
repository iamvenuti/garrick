import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Activity, Note, Thread } from '../types'

// Garrick blue, from docs/assets/garrick-mark.svg.
const BLUE = 0x3d73e0
const DEFAULT = 0x01000000
const PANE = 'garrick-resume'

const note = atom({ plugin: 'garrick-band', key: 'note' } as const, null)
const isHidden = atom({ plugin: 'garrick-band', key: 'isHidden' } as const, false)
const activity = atom({ plugin: 'garrick-band', key: 'activity' } as const, null)

// The mark, the cabinet, as a 6×3 cell tile: a 6×6 grid of half-block pixels,
// two to a cell. The spine and the closed compartment are drawn in the
// terminal's own text colour, so they read on light and dark; the open one is
// blue. A gap of one pixel is the wall.
const CABINET = ['II BBB', 'II BBB', 'II    ', 'II III', 'II III', 'II III']

export function markCells(): string {
  const colour = (p: string) => (p === 'B' ? BLUE : DEFAULT)
  const words: number[] = []
  for (let row = 0; row < 6; row += 2) {
    for (let col = 0; col < 6; col++) {
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

export function plain(markdown: string): string {
  return markdown
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, '$2')
    .replace(/\[\[([^\]]+)\]\]/g, (_, target: string) => basename(target))
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\*\*|__|`/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

// The frontmatter status, the Resume here block, its heading and its first paragraph.
export function parseNote(text: string): Pick<Note, 'status' | 'heading' | 'lead' | 'resume'> {
  const status = /^---\n[\s\S]*?^status:\s*(\S+)[\s\S]*?^---$/m.exec(text)?.[1] ?? null
  const match = /^### (Resume here|Outcome)\s*$/m.exec(text)
  if (match === null) return { status, heading: null, lead: null, resume: null }
  const start = match.index

  const body = text.slice(start).replace(/^### .*\n/, '')
  const end = body.search(/^#{2,3} /m)
  const resume = (end < 0 ? body : body.slice(0, end)).trim()
  const lead = resume.split(/\n\s*\n/).find(p => !p.startsWith('|')) ?? null

  return { status, heading: match[1]!, lead: lead === null ? null : plain(lead), resume }
}

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

// --- What the session is doing --------------------------------------------
// The prompt as one line: its first line with text in it, markup stripped.
export function promptLine(text: string): string {
  const line = text.split('\n').map(l => l.trim()).find(l => l !== '') ?? ''

  return plain(line)
}

// One tool call as a few words: what it touches, not how.
export function stepLine(e: Record<string, any>): string {
  const tool = String(e.tool ?? '')
  const file = e.file_path ?? e.notebook_path
  const first = (v: unknown) => String(v ?? '').split('\n')[0]!.trim()
  switch (tool) {
    case 'Bash':
      return e.description ? first(e.description) : `$ ${first(e.command)}`
    case 'Read':
      return `Reading ${basename(String(file ?? ''))}`
    case 'Edit':
    case 'NotebookEdit':
      return `Editing ${basename(String(file ?? ''))}`
    case 'Write':
      return `Writing ${basename(String(file ?? ''))}`
    case 'Grep':
    case 'Glob':
      return `Searching for ${first(e.pattern)}`
    case 'Agent':
    case 'Task':
      return `Agent: ${first(e.description)}`
    case 'Skill':
      return `Skill: ${first(e.skill)}`
    case 'WebSearch':
      return `Searching the web for ${first(e.query)}`
    case 'WebFetch':
      return `Fetching ${first(e.url).replace(/^https?:\/\//, '').split('/')[0]}`
  }
  const mcp = /^mcp__(.+?)__(.+)$/.exec(tool)
  if (mcp) return `${mcp[1]!.replace(/^claude_ai_/, '').replace(/_/g, ' ')}: ${mcp[2]!.replace(/_/g, ' ')}`

  return tool
}

// The prompt cut to leave room for the step after it on one row.
export function cut(text: string, room: number): string {
  return text.length <= room ? text : text.slice(0, Math.max(1, room - 1)).trimEnd() + '…'
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
    const lead = threads.length ? `${threads.length === 1 ? 'Thread' : `${threads.length} threads`}: ${threads.map(t => t.title).join(', ')}` : parsed.lead

    return { path, rel, where, title: basename(folder), ...parsed, lead, threads, ...(await openers($, chain, folder)) }
  }
  // No thread note above the folder (System/, the root, a wiki): nothing to
  // resume or wrap, but Finder still shows the folder and, in a wiki, Obsidian
  // opens its index.
  const here = chain[0]!
  const where = label(here.slice(root.length + 1))
  const index = `${here}/wiki/index.md`
  const target = (await $.fs.exists(index)) ? index : here
  const open = await openers($, chain, here)

  return {
    path: target, rel: target.slice(root.length + 1), where: where || 'Home', title: where || 'Home',
    status: null, heading: null, lead: null, resume: null,
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

// Finder wherever macOS's `open` is there; Obsidian when it is installed and a
// folder from the note up to the workspace root is a vault (holds .obsidian).
async function openers($: any, chain: string[], folder: string): Promise<Pick<Note, 'finder' | 'obsidian'>> {
  const finder: boolean = await $.fs.exists('/usr/bin/open')
  if (!finder) return { finder, obsidian: false }
  const home: string = (await $.env.get('HOME')) ?? ''
  const installed = (await $.fs.exists('/Applications/Obsidian.app')) || (await $.fs.exists(`${home}/Applications/Obsidian.app`))
  let vault = false
  for (const dir of chain.slice(chain.indexOf(folder))) {
    if (await $.fs.exists(`${dir}/.obsidian`)) {
      vault = true
      break
    }
  }

  return { finder, obsidian: installed && vault }
}

export const obsidianUrl = (abs: string) => 'obsidian://open?path=' + encodeURIComponent(abs)

// The band's actions, shared by its buttons and /garrick.
const openNote = ($: any, n: Note) => $.ui.open({ id: PANE, title: n.title, focus: true, closeOnEscape: true })
const resume = ($: any, n: Note) => $.prompt.submit({ text: n.resume ? resumePrompt(n) : projectResumePrompt(n), asUser: true })
const resumable = (n: Note | null): n is Note => n !== null && (n.resume !== null || n.threads.length > 0)
const wrap = ($: any, n: Note) => $.prompt.submit({ text: n.resume ? wrapPrompt(n) : projectWrapPrompt(n), asUser: true })
const clear = ($: any) => $.command.run({ command: 'clear' })
async function opener($: any, args: string[], app: string) {
  const { exitCode } = await $.process.run(['/usr/bin/open', ...args])
  if (exitCode !== 0) $.ui.toast(`${app} did not open the note.`)
}
const finder = ($: any, n: Note) => opener($, ['-R', n.path], 'Finder')
const obsidian = ($: any, n: Note) => opener($, [obsidianUrl(n.path)], 'Obsidian')

async function refresh($: any) {
  const found = await findNote($).catch(() => null)
  await update($, note, () => found)
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

const STATUS_COLOR: Record<string, string> = { active: 'green', parked: 'yellow', done: 'gray' }

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // immediate: typed while a turn runs, it answers at once instead of
    // waiting for the turn to end.
    await $.command.register({
      name: 'garrick',
      description: 'Show the Garrick band; "hide" it, "resume" or "wrap" the thread, "note" shows its Resume here block, "finder" or "obsidian" opens the note',
      argumentHint: '[hide|resume|wrap|note|finder|obsidian]',
      immediate: true,
    })
    await update($, activity, () => null)
    await refresh($)
    await reindex($).catch(() => undefined)

    return next(e)
  })

  // The note may have been rewritten by the turn (thread-wrap, an edit), and
  // files may have been added.
  on('prompt.submit', async ($, e, next) => {
    const prompt = promptLine(e.text)
    if (prompt !== '') await update($, activity, () => ({ prompt, step: null })).catch(() => undefined)

    return next(e)
  })

  // The main conversation's calls only: a subagent's would flicker past.
  on('tool.call', async ($, e, next) => {
    if ((e as any).agentId === undefined) {
      const step = stepLine(e as any)
      await update($, activity, a => (a === null ? null : { ...a, step })).catch(() => undefined)
    }

    return next(e)
  })

  on('command.run', { command: 'clear' }, async ($, e, next) => {
    await update($, activity, () => null).catch(() => undefined)

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    await update($, activity, a => (a === null ? null : { ...a, step: null }))
    await refresh($)
    await reindex($).catch(() => undefined)

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
    const current = await read($, note)
    if (arg === 'finder' || arg === 'obsidian') {
      if (current === null || current.path === '') return { text: 'No project or thread note above this folder.' }
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

    return { text: `Unknown argument "${arg}": use hide, resume, wrap, note, finder or obsidian.` }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const current = await read($, note)
    if (e.props.hasSurvey || current === null || (await read($, isHidden))) return next(e)

    const doing = await read($, activity)
    const { Box, Text, Button, ...rest } = $.ui.resolve(e)
    const Raster = (rest as any).Raster
    const mark = Raster ? (
      <Raster key="mark" columns={6} rows={3} cells={markCells()} />
    ) : (
      <Text>█<Text color="#3d73e0">▀</Text></Text>
    )

    return (
      <Box flexDirection="row" gap={1}>
        {mark}
        <Box flexDirection="column" flexGrow={1} flexShrink={1}>
          <Text wrap="truncate-end">
            <Text bold color="#3d73e0">Garrick</Text>
            <Text dimColor> · </Text>
            <Text bold>{current.where}</Text>
            {current.status && <Text color={STATUS_COLOR[current.status] ?? 'gray'}> {current.status}</Text>}
          </Text>
          {doing === null ? (
            <Text dimColor wrap="truncate-end">
              {current.lead ?? 'No Resume here block above this folder.'}
            </Text>
          ) : (
            <Text wrap="truncate-end">
              <Text color="#3d73e0">› </Text>
              <Text dimColor={!e.props.isWorking}>
                {e.props.isWorking && doing.step ? cut(doing.prompt, Math.floor(e.props.bodyColumns * 0.5)) : doing.prompt}
              </Text>
              {e.props.isWorking && doing.step && <Text dimColor> · {doing.step}</Text>}
            </Text>
          )}
          <Box flexDirection="row" gap={2}>
            {resumable(current) && <Button key="resume" label="Resume" hotkey="r" plain onPress={() => void resume($, current)} />}
            {resumable(current) && current.status !== 'done' && (
              <Button key="wrap" label="Wrap" hotkey="w" plain onPress={() => void wrap($, current)} />
            )}
            <Button key="clear" label="Clear" hotkey="c" plain onPress={() => void clear($)} />
            {resumable(current) && <Button key="note" label="Note" hotkey="n" plain dimColor onPress={() => void openNote($, current)} />}
            {current.finder && <Button key="finder" label="Finder" hotkey="f" plain dimColor onPress={() => void finder($, current)} />}
            {current.obsidian && <Button key="obsidian" label="Obsidian" hotkey="o" plain dimColor onPress={() => void obsidian($, current)} />}
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
    const current = await read($, note)
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

import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Note } from '../types'

// Garrick blue, from docs/assets/garrick-mark.svg.
const BLUE = 0x3d73e0
const DEFAULT = 0x01000000
const PANE = 'garrick-resume'

const note = atom({ plugin: 'garrick-band', key: 'note' } as const, null)
const isHidden = atom({ plugin: 'garrick-band', key: 'isHidden' } as const, false)

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

// The frontmatter status, the Resume here block, and its first paragraph.
export function parseNote(text: string): Pick<Note, 'status' | 'lead' | 'resume'> {
  const status = /^---\n[\s\S]*?^status:\s*(\S+)[\s\S]*?^---$/m.exec(text)?.[1] ?? null
  const start = text.search(/^### (Resume here|Outcome)\s*$/m)
  if (start < 0) return { status, lead: null, resume: null }

  const body = text.slice(start).replace(/^### .*\n/, '')
  const end = body.search(/^#{2,3} /m)
  const resume = (end < 0 ? body : body.slice(0, end)).trim()
  const lead = resume.split(/\n\s*\n/).find(p => !p.startsWith('|')) ?? null

  return { status, lead: lead === null ? null : plain(lead), resume }
}

// Walk up from the working directory to the workspace root (the folder holding
// System/rules.md); the first folder whose own <Folder>.md exists is the thread.
async function findNote($: any): Promise<Note | null> {
  let dir: string = await $.session.cwd()
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

    return { path, where, title: basename(folder), ...parseNote(text) }
  }
  const where = label(chain[0]!.slice(root.length + 1))

  return { path: '', where: where || 'Home', title: where, status: null, lead: null, resume: null }
}

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
    await $.command.register({
      name: 'garrick',
      description: 'Show or hide the Garrick band; "resume" opens the Resume here pane',
      argumentHint: '[resume]',
    })
    await refresh($)
    await reindex($).catch(() => undefined)

    return next(e)
  })

  // The note may have been rewritten by the turn (thread-wrap, an edit), and
  // files may have been added.
  on('turn.complete', async ($, e, next) => {
    await refresh($)
    await reindex($).catch(() => undefined)

    return next(e)
  })

  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    const text = await linkify(e.props.text, await resolver($))

    return text === e.props.text ? next(e) : next({ ...e, props: { ...e.props, text } })
  })

  on('command.run', { command: 'garrick' }, async ($, e) => {
    if (String(e.args ?? '').trim() === 'resume') {
      await $.ui.open({ id: PANE, title: 'Resume here', focus: true, closeOnEscape: true })

      return { text: 'Resume pane opened.' }
    }
    const hidden = await update($, isHidden, was => !was)

    return { text: hidden ? 'Garrick band hidden.' : 'Garrick band shown.' }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const current = await read($, note)
    if (e.props.hasSurvey || current === null || (await read($, isHidden))) return next(e)

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
          <Text dimColor wrap="truncate-end">
            {current.lead ?? 'No Resume here block above this folder.'}
          </Text>
          {current.resume && (
            <Box flexDirection="row" gap={1}>
              <Button
                key="resume"
                label="Resume here"
                plain
                onPress={() => void $.ui.open({ id: PANE, title: current.title, focus: true, closeOnEscape: true })}
              />
              <Button key="hide" label="Hide" plain dimColor onPress={() => update($, isHidden, () => true)} />
            </Box>
          )}
        </Box>
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Markdown } = $.ui.resolve(e)
    const current = await read($, note)
    if (current?.resume == null) return <Text dimColor>No Resume here block found.</Text>

    return (
      <Box flexDirection="column">
        <Text dimColor wrap="truncate-end">{current.path}</Text>
        <Markdown text={current.resume.slice(0, 10000)} />
      </Box>
    )
  })
}

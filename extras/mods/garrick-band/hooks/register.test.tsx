import { describe, expect, test } from 'claude-code/testing'

import { buildIndex, fileHref, label, linkify, lookup, markCells, parseNote, plain } from './register'

const ROOT = '/v'
const NOTE = `---
status: active
---
# Acme Renewal

## State of play

### Resume here

**Where it stands, 6 October.** The term sheet is ready, see [[Acme Renewal/Deliverables/x|the sheet]].

| | |
|---|---|
| Live artifact | \`x.xlsx\` |

### 2026-10-05

Older entry.
`

describe('parsing', () => {
  test('labels drop Zones and Threads', () => {
    expect(label('Zones/Work/Acme/Threads/Acme Renewal')).toBe(
      'Work › Acme › Acme Renewal',
    )
    expect(label('Wikis/Meetings')).toBe('Wikis › Meetings')
  })

  test('plain strips links and emphasis', () => {
    expect(plain('**Bold** [[a/b|shown]] and [[c/d]] `code`')).toBe('Bold shown and d code')
  })

  test('reads status, lead and stops at the next heading', () => {
    const parsed = parseNote(NOTE)
    expect(parsed.status).toBe('active')
    expect(parsed.lead).toBe('Where it stands, 6 October. The term sheet is ready, see the sheet.')
    expect(parsed.resume).toContain('Live artifact')
    expect(parsed.resume).not.toContain('Older entry')
  })

  test('a note with no Resume block', () => {
    expect(parseNote('# Plain\n').resume).toBeNull()
  })

  test('a finished thread reads its Outcome block', () => {
    const parsed = parseNote('---\nstatus: done\n---\n## State of play\n\n### Outcome\n\nSigned on 2 October.\n')
    expect(parsed.status).toBe('done')
    expect(parsed.lead).toBe('Signed on 2 October.')
  })

  test('the mark is 6×3 cells of three u32 words each', () => {
    expect(atob(markCells()).length).toBe(6 * 3 * 3 * 4)
  })

  test('the mark is the cabinet: walls in the text colour, the open compartment blue', () => {
    const bytes = Uint8Array.from(atob(markCells()), (c) => c.charCodeAt(0))
    const words = new Uint32Array(bytes.buffer)
    const cell = (row: number, col: number) => Array.from(words.slice((row * 6 + col) * 3, (row * 6 + col) * 3 + 3))
    expect(cell(0, 0)).toEqual([0x2588, 0x01000000, 0x01000000])   // the spine
    expect(cell(0, 2)).toEqual([0x20, 0x01000000, 0x01000000])     // the wall
    expect(cell(0, 3)).toEqual([0x2588, 0x3d73e0, 0x01000000])     // the open compartment
    expect(cell(1, 4)).toEqual([0x2584, 0x01000000, 0x01000000])   // the wall above the closed one
  })
})

describe('band', () => {
  for (const surface of ['terminal', 'desktop'] as const) {
    test(`draws the thread on ${surface}`, async ($, on) => {
      const cwd = `${ROOT}/Zones/Work/Acme`
      on('session.cwd', async () => ({ value: cwd }))
      on('fs.exists', async (_$, e: any) => ({
        value: e.path === `${ROOT}/System/rules.md` || e.path === `${cwd}/Acme.md`,
      }))
      on('fs.read', async () => ({ value: NOTE }))
      on('turn.complete', async () => ({ text: '' }))

      await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
      const band = await $.ui.mount({
        plugin: 'garrick-band',
        surface,
        component: 'AbovePrompt',
        props: { hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 100 } as any,
      } as any)

      expect(await band.find({ text: /Work › Acme/ })).toBeDefined()
      expect(await band.find({ key: 'resume' })).toBeDefined()
    })
  }
})

describe('outside a project', () => {
  test('shows the place with no Resume line', async ($, on) => {
    on('session.cwd', async () => ({ value: `${ROOT}/Wikis/Meetings` }))
    on('fs.exists', async (_$, e: any) => ({ value: e.path === `${ROOT}/System/rules.md` }))
    on('turn.complete', async () => ({ text: '' }))

    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
    const band = await $.ui.mount({
      plugin: 'garrick-band',
      surface: 'terminal',
      component: 'AbovePrompt',
      props: { hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 100 } as any,
    } as any)

    expect(await band.find({ text: /Wikis › Meetings/ })).toBeDefined()
    expect(await band.find({ key: 'resume' })).toBeUndefined()
  })
})

describe('paths', () => {
  const idx = buildIndex(
    '/v',
    [
      '/v/System/rules.md',
      '/v/Zones/Work/Acme/Acme.md',
      '/v/Zones/Work/Acme/Deliverables/260907 - Price list #2-v3.xlsx',
      '/v/Zones/Work/Birch/Notes/readme.md',
      '/v/Zones/Work/Acme/Notes/readme.md',
    ].join('\n'),
  )

  test('full, partial and bare names resolve by suffix', () => {
    expect(lookup(idx, 'System/rules.md', '')).toBe('System/rules.md')
    expect(lookup(idx, 'Deliverables/260907 - Price list #2-v3.xlsx', '')).toBe('Zones/Work/Acme/Deliverables/260907 - Price list #2-v3.xlsx')
    expect(lookup(idx, '260907 - Price list #2-v3.xlsx', '')).toBe('Zones/Work/Acme/Deliverables/260907 - Price list #2-v3.xlsx')
    expect(lookup(idx, 'Deliverables/…/260907 - Price list #2-v3.xlsx', '')).toBe('Zones/Work/Acme/Deliverables/260907 - Price list #2-v3.xlsx')
    expect(lookup(idx, 'System/rules.md:12', '')).toBe('System/rules.md')
  })

  test('an ambiguous name prefers the session folder, else stays plain', () => {
    expect(lookup(idx, 'readme.md', '')).toBeNull()
    expect(lookup(idx, 'readme.md', 'Zones/Work/Acme')).toBe('Zones/Work/Acme/Notes/readme.md')
  })

  test('hrefs are percent-encoded', () => {
    expect(fileHref('/v/a b/#1.md')).toBe('file:///v/a%20b/%231.md')
  })

  test('linkify rewrites path spans only, outside fences', async () => {
    const resolve = async (s: string) => (s === 'System/rules.md' ? '/v/System/rules.md' : null)
    const text = 'See `System/rules.md` and `claude plugin test`.\n```\n`System/rules.md`\n```\n'
    const out = await linkify(text, resolve)
    expect(out).toContain('[`System/rules.md`](file:///v/System/rules.md)')
    expect(out).toContain('`claude plugin test`')
    expect(out).toContain('```\n`System/rules.md`\n```')
  })
})

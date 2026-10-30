import { describe, expect, mock, test } from 'claude-code/testing'

import { buildIndex, fileHref, FULL, label, launcherSettings, linkify, lookup, MARK, markCells, nextUpArgv, obsidianUrl, pageActionArgv, paneMarkdown, parseNote, percentOf, previewOn, resumePrompt, rootOf, switchedOff, waitOff, waitOrder, waitSettings, wrapPrompt, zoneOf } from './register'

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

  test('reads status and the Resume here block, and stops at the next heading', () => {
    const parsed = parseNote(NOTE)
    expect(parsed.status).toBe('active')
    expect(parsed.heading).toBe('Resume here')
    expect(parsed.resume).toMatch(/^\*\*Where it stands, 6 October\.\*\*/)
    expect(parsed.resume).toContain('Live artifact')
    expect(parsed.resume).not.toContain('Older entry')
  })

  test('a note with no Resume block', () => {
    expect(parseNote('# Plain\n').resume).toBeNull()
  })

  test('a finished thread reads its Outcome block', () => {
    const parsed = parseNote('---\nstatus: done\n---\n## State of play\n\n### Outcome\n\nSigned on 2 October.\n')
    expect(parsed.status).toBe('done')
    expect(parsed.heading).toBe('Outcome')
    expect(parsed.resume).toBe('Signed on 2 October.')
  })

  test('the prompts name the thread and its note', () => {
    const n = { path: '/v/Zones/Work/Acme/Acme.md', rel: 'Zones/Work/Acme/Acme.md', where: 'Work › Acme', title: 'Acme', ...parseNote(NOTE), finder: true, obsidian: false, threads: [] }
    expect(resumePrompt(n)).toBe('Open Acme: read the Resume here block in `Zones/Work/Acme/Acme.md` and tell me in two sentences where it stands and the next action.')
    expect(wrapPrompt(n)).toMatch(/^Wrap Acme: rewrite the Resume here block in `Zones\/Work\/Acme\/Acme.md`/)
  })

  test('the mark is 4×2 cells, as tall as the band, of three u32 words each', () => {
    expect(MARK).toEqual({ columns: 4, rows: 2 })
    expect(atob(markCells()).length).toBe(4 * 2 * 3 * 4)
  })

  test('the mark is the cabinet: walls in the text colour, the open compartment blue', () => {
    const bytes = Uint8Array.from(atob(markCells()), (c) => c.charCodeAt(0))
    const words = new Uint32Array(bytes.buffer)
    const cell = (row: number, col: number) => Array.from(words.slice((row * 4 + col) * 3, (row * 4 + col) * 3 + 3))
    expect(cell(0, 0)).toEqual([0x2588, 0x01000000, 0x01000000])   // the spine
    expect(cell(1, 0)).toEqual([0x2588, 0x01000000, 0x01000000])
    expect(cell(0, 1)).toEqual([0x20, 0x01000000, 0x01000000])     // the wall beside it
    expect(cell(0, 2)).toEqual([0x2580, 0x3d73e0, 0x01000000])     // the open compartment, the wall under it
    expect(cell(0, 3)).toEqual([0x2580, 0x3d73e0, 0x01000000])
    expect(cell(1, 2)).toEqual([0x2588, 0x01000000, 0x01000000])   // the closed one
    expect(cell(1, 3)).toEqual([0x2588, 0x01000000, 0x01000000])
  })

  test('the context used: a whole percentage, or none', () => {
    expect(percentOf({ percent: 42 })).toBe(42)
    expect(percentOf({ percent: 60.4 })).toBe(60)
    expect(percentOf({})).toBeNull()
    expect(percentOf(null)).toBeNull()
    expect(FULL).toBe(60)
  })
})

const BAND = {
  plugin: 'garrick-band',
  component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 100 },
} as any

// settings: what System/garrick-settings.json holds, as a string or an object;
// left out, every file read is the note, so the settings do not parse.
async function inThread($: any, on: any, text: string, extra: string[] = [], settings?: object | string) {
  const cwd = `${ROOT}/Zones/Work/Acme`
  on('session.root', async () => ({ value: cwd }))
  on('session.cwd', async () => ({ value: `${ROOT}/System/tools` }))      // a cd in a tool call: the band keeps its thread
  on('env.get', async () => ({ value: '/Users/someone' }))
  on('fs.exists', async (_$: any, e: any) => ({
    value: [`${ROOT}/System/rules.md`, `${cwd}/Acme.md`, ...extra].includes(e.path),
  }))
  on('fs.read', async (_$: any, e: any) => ({
    value: settings !== undefined && e.path === `${ROOT}/System/garrick-settings.json`
      ? (typeof settings === 'string' ? settings : JSON.stringify(settings)) : text,
  }))
  on('turn.complete', async () => ({ text: '' }))
  await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
}

describe('band', () => {
  for (const surface of ['terminal', 'desktop'] as const) {
    test(`draws the thread on ${surface}`, async ($, on) => {
      await inThread($, on, NOTE)
      const band = await $.ui.mount({ ...BAND, surface })

      expect(await band.find({ text: /Work › Acme/ })).toBeDefined()
      for (const key of ['wrap', 'clear']) expect(await band.find({ key })).toBeDefined()
      for (const key of ['resume', 'note', 'finder']) expect(await band.find({ key })).toBeUndefined()
    })

    test(`Wrap submits the thread's prompt on ${surface}`, async ($, on) => {
      const submitted: string[] = []
      on('prompt.submit', async (_$, e: any) => {
        submitted.push(e.text)
        return { text: e.text }
      })
      await inThread($, on, NOTE)
      const band = await $.ui.mount({ ...BAND, surface })

      await band.press({ key: 'wrap' })
      expect(submitted).toHaveLength(1)
      expect(submitted[0]).toMatch(/^Wrap Acme: rewrite the Resume here block in `Zones\/Work\/Acme\/Acme.md`/)
    })

    test(`Clear runs /clear on ${surface}`, async ($, on) => {
      const ran: string[] = []
      on('command.run', async (_$, e: any) => {
        ran.push(e.command)
        return {}
      })
      await inThread($, on, NOTE)
      const band = await $.ui.mount({ ...BAND, surface })

      await band.press({ key: 'clear' })
      expect(ran).toEqual(['clear'])
    })
  }

  test('a finished thread offers no Wrap', async ($, on) => {
    await inThread($, on, '---\nstatus: done\n---\n## State of play\n\n### Outcome\n\nSigned on 2 October.\n')
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

    expect(await band.find({ key: 'clear' })).toBeDefined()
    expect(await band.find({ key: 'wrap' })).toBeUndefined()
  })

  test('two lines: the place, then the buttons at one weight, with no Resume line', async ($, on) => {
    await inThread($, on, NOTE, ['/usr/bin/open', '/Applications/Obsidian.app', `${ROOT}/Zones/Work/.obsidian`])
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect((await band.findAll({ type: 'Button' })).map(b => b.key)).toEqual(['wrap', 'clear', 'finder', 'obsidian'])
    for (const b of await band.findAll({ type: 'Button' })) expect(b.props.dimColor).toBeFalsy()
    expect(await band.find({ text: /Where it stands/ })).toBeUndefined()
  })

  test('no prompt or step under the place, and no line under the buttons, during a long turn', async ($, on) => {
    const clock = mock.clock(on)
    const ran: string[][] = []
    on('process.run', async (_$: any, e: any) => {
      ran.push([...e.argv])
      return { value: { exitCode: 0, stdout: '', stderr: '' } } as any
    })
    on('prompt.submit', async (_$: any, e: any) => ({ text: e.text }))
    on('tool.call', async () => ({ result: '' }))
    on('turn.start', async (_$: any, e: any) => ({ turnId: e.turnId }))
    await inThread($, on, NOTE, [`${ROOT}/System/tools/next_up.py`])
    await $.turn.start({ text: 'Fix the pricing table', turnId: 't2' } as any)
    await $.prompt.submit({ text: 'Fix the **pricing** table' } as any)
    await $.tool.call({ tool: 'Edit', file_path: '/v/x/sheet.md', old_string: 'a', new_string: 'b' } as any).catch(() => undefined)
    await clock.advance(120_000)
    const working = await $.ui.mount({ ...BAND, surface: 'terminal', props: { ...BAND.props, isWorking: true } })
    expect(await working.find({ text: /pricing/ })).toBeUndefined()
    expect(await working.find({ text: /Editing sheet\.md/ })).toBeUndefined()
    expect(await working.find({ text: /While you wait/ })).toBeUndefined()
    expect(ran.filter(r => r.some(a => a.endsWith('next_up.py')))).toEqual([])
    expect((await $.command.run({ command: 'garrick', args: 'next' } as any)).text).toBe(waitOff)
  })
})

describe('context used', () => {
  // What $.session.usage() answers, its percent read from `at` each time.
  function usage(on: any, at: { percent?: number }) {
    on('session.usage', async () => ({ value: { startedAt: 0, context: { window: 200_000, ...at }, rateLimits: [] } }) as any)
  }
  const shown = async ($: any) => (await $.ui.mount({ ...BAND, surface: 'terminal' })).find({ type: 'Text', text: /^\d+%$/ })

  test('dimmed at 60, red at 61, read again after every turn', async ($, on) => {
    const at: { percent?: number } = { percent: 60 }
    usage(on, at)
    await inThread($, on, NOTE)
    const sixty = await shown($)
    expect(sixty?.text).toBe('60%')
    expect(sixty?.props.dimColor).toBe(true)
    expect(sixty?.props.color).toBeUndefined()
    expect(await (await $.ui.mount({ ...BAND, surface: 'terminal' })).find({ text: /active · 60%/ })).toBeDefined()

    at.percent = 61
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't2', reason: 'answer' })
    const over = await shown($)
    expect(over?.text).toBe('61%')
    expect(over?.props.color).toBe('red')
    expect(over?.props.dimColor).toBeFalsy()
  })

  test('nothing while the API has no figure', async ($, on) => {
    const at: { percent?: number } = {}
    usage(on, at)
    await inThread($, on, NOTE)
    expect(await shown($)).toBeUndefined()
    expect(await (await $.ui.mount({ ...BAND, surface: 'terminal' })).find({ text: /%/ })).toBeUndefined()
  })

  test("a typed /clear empties the figure until the new conversation's first reply", async ($, on) => {
    const at: { percent?: number } = { percent: 78 }
    usage(on, at)
    on('session.end', async (_$: any, e: any) => ({ sessionId: e.sessionId }))
    await inThread($, on, NOTE)
    expect((await shown($))?.props.color).toBe('red')

    await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } } as any)
    expect(await shown($)).toBeUndefined()
    expect(await (await $.ui.mount({ ...BAND, surface: 'terminal' })).find({ text: /Work › Acme/ })).toBeDefined()

    at.percent = 3
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't2', reason: 'answer' })
    expect((await shown($))?.text).toBe('3%')
  })

  // The session's named values, held by the test so that a clear can empty
  // them as a real one does: the new conversation's atoms start fresh, and no
  // session.start follows.
  function freshState(on: any) {
    const values = new Map<string, { value: unknown; version: number }>()
    const name = (e: any) => `${e.plugin}/${e.key}/${e.id ?? ''}`
    on('state.get', async (_$: any, e: any) => ({ value: values.get(name(e)) ?? { value: undefined, version: 0 } }))
    on('state.set', async (_$: any, e: any) => {
      const now = values.get(name(e))?.version ?? 0
      if (e.ifVersion !== undefined && e.ifVersion !== now) return { value: { isSet: false, version: now } }
      values.set(name(e), { value: e.value, version: now + 1 })
      return { value: { isSet: true, version: now + 1 } }
    })
    return () => values.clear()
  }

  for (const how of ['typed', 'from the band'] as const) {
    test(`after a clear ${how}, the band is drawn at once, with its place and buttons and no figure`, async ($, on) => {
      mock.clock(on)
      on('ui.render', ENGINE)
      const at: { percent?: number } = { percent: 78 }
      usage(on, at)
      const wipe = freshState(on)
      on('session.end', async (_$: any, e: any) => ({ sessionId: e.sessionId }))
      on('command.run', async (_$: any, e: any) => {
        if (e.command === 'clear') {
          delete at.percent
          wipe()
        }
        return {}
      })
      await inThread($, on, NOTE)
      expect((await shown($))?.text).toBe('78%')

      if (how === 'typed') {
        delete at.percent
        await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } } as any)
        wipe()
      } else {
        await (await $.ui.mount({ ...BAND, surface: 'terminal' })).press({ key: 'clear' })
      }
      const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
      expect(await band.find({ text: /Work › Acme/ })).toBeDefined()
      expect((await band.findAll({ type: 'Button' })).map(b => b.key)).toEqual(['wrap', 'clear'])
      expect(await band.find({ text: /%/ })).toBeUndefined()
      expect((await $.command.run({ command: 'garrick', args: 'wrap' } as any)).text).toBe('Wrapping Acme.')

      at.percent = 4
      await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't2', reason: 'answer' })
      expect((await shown($))?.text).toBe('4%')
    })
  }

  test('after a clear outside any workspace, a render searches for nothing', async ($, on) => {
    on('ui.render', ENGINE)
    const wipe = freshState(on)
    let asked = 0
    on('session.root', async () => {
      asked++
      return { value: '/elsewhere/project' }
    })
    on('session.cwd', async () => ({ value: '/elsewhere/project' }))
    on('fs.exists', async () => ({ value: false }))
    on('turn.complete', async () => ({ text: '' }))
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
    const before = asked
    wipe()
    for (let i = 0; i < 3; i++) expect(await (await $.ui.mount({ ...BAND, surface: 'terminal' })).find({ key: 'clear' })).toBeUndefined()
    expect(asked).toBe(before)
  })

  test("the band's Clear empties the figure", async ($, on) => {
    usage(on, { percent: 78 })
    on('command.run', async () => ({}))
    await inThread($, on, NOTE)
    expect((await shown($))?.text).toBe('78%')

    await (await $.ui.mount({ ...BAND, surface: 'terminal' })).press({ key: 'clear' })
    expect(await shown($)).toBeUndefined()
  })

  test('after a compaction there is no figure until the next reply', async ($, on) => {
    const at: { percent?: number } = { percent: 70 }
    usage(on, at)
    const summary = { role: 'user', text: 'Summary of the conversation so far.', toolUses: [] }
    on('session.compact', async () => ({ messages: [summary] }) as any)
    await inThread($, on, NOTE)
    expect((await shown($))?.text).toBe('70%')

    delete at.percent
    await $.session.compact({ trigger: 'manual', messages: [summary, summary] } as any)
    expect(await shown($)).toBeUndefined()

    at.percent = 9
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't2', reason: 'answer' })
    expect((await shown($))?.text).toBe('9%')
  })

  test('a Claude Code without the usage call shows the band with no figure', async ($, on) => {
    on('session.usage', async () => {
      throw new Error('no such operation: session.usage')
    })
    await inThread($, on, NOTE)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await band.find({ text: /Work › Acme/ })).toBeDefined()
    expect(await band.find({ text: /%/ })).toBeUndefined()
  })

  test('outside a thread too, after the place', async ($, on) => {
    usage(on, { percent: 12 })
    on('session.root', async () => ({ value: `${ROOT}/System` }))
    on('session.cwd', async () => ({ value: `${ROOT}/System` }))
    on('fs.exists', async (_$, e: any) => ({ value: e.path === `${ROOT}/System/rules.md` }))
    on('turn.complete', async () => ({ text: '' }))
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
    expect((await shown($))?.text).toBe('12%')
  })
})

describe('outside a project', () => {
  test('a wiki offers Finder on its folder and Obsidian on its index', async ($, on) => {
    const ran: string[][] = []
    on('process.run', async (_$: any, e: any) => {
      ran.push([...e.argv])
      return { value: { exitCode: 0, stdout: '', stderr: '' } } as any
    })
    on('session.root', async () => ({ value: `${ROOT}/Wikis/Meetings` }))
    on('session.cwd', async () => ({ value: `${ROOT}/Wikis/Meetings` }))
    on('env.get', async () => ({ value: '/Users/someone' }))
    on('fs.exists', async (_$, e: any) => ({
      value: [`${ROOT}/System/rules.md`, '/usr/bin/open', '/Applications/Obsidian.app', `${ROOT}/Wikis/.obsidian`,
              `${ROOT}/Wikis/Meetings/wiki/index.md`].includes(e.path),
    }))
    on('turn.complete', async () => ({ text: '' }))
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await band.find({ key: 'wrap' })).toBeUndefined()
    expect(await band.find({ key: 'finder' })).toBeDefined()
    await band.press({ key: 'obsidian' })
    expect(JSON.stringify(ran)).toContain(obsidianUrl(`${ROOT}/Wikis/Meetings/wiki/index.md`))
  })

  test('System offers Finder on the folder, and no Obsidian', async ($, on) => {
    on('session.root', async () => ({ value: `${ROOT}/System` }))
    on('session.cwd', async () => ({ value: `${ROOT}/System` }))
    on('env.get', async () => ({ value: '/Users/someone' }))
    on('fs.exists', async (_$, e: any) => ({ value: [`${ROOT}/System/rules.md`, '/usr/bin/open', '/Applications/Obsidian.app'].includes(e.path) }))
    on('turn.complete', async () => ({ text: '' }))
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await band.find({ text: /System/ })).toBeDefined()
    expect(await band.find({ key: 'finder' })).toBeDefined()
    expect(await band.find({ key: 'obsidian' })).toBeUndefined()
  })

  test('shows the place and Clear', async ($, on) => {
    on('session.root', async () => ({ value: `${ROOT}/Wikis/Meetings` }))
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
    expect(await band.find({ key: 'wrap' })).toBeUndefined()
    expect(await band.find({ key: 'clear' })).toBeDefined()
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

const ENGINE = async ($: any, e: any) => {
  const { Text } = $.ui.resolve(e)
  return <Text>engine</Text>
}

describe('a project kept in threads', () => {
  const HUB = '---\nstatus: active\n---\n# Acme\n\n## Active threads\n\n- Pricing\n'
  let clock: any
  const thread = (status: string, block: string) => `---\nstatus: ${status}\n---\n## State of play\n\n### Resume here\n\n${block}\n`
  const files: Record<string, string> = {
    [`${ROOT}/Zones/Work/Acme/Acme.md`]: HUB,
    [`${ROOT}/Zones/Work/Acme/Threads/Pricing/Pricing.md`]: thread('active', 'Pricing waits on legal.'),
    [`${ROOT}/Zones/Work/Acme/Threads/Renewal/Renewal.md`]: thread('active', 'Renewal is signed off.'),
    [`${ROOT}/Zones/Work/Acme/Threads/Old/Old.md`]: thread('done', 'Finished.'),
  }

  async function atProject($: any, on: any) {
    const submitted: string[] = []
    clock = mock.clock(on)
    on('ui.render', ENGINE)
    on('prompt.submit', async (_$: any, e: any) => {
      submitted.push(e.text)
      return { text: e.text }
    })
    on('session.root', async () => ({ value: `${ROOT}/Zones/Work/Acme` }))
    on('session.cwd', async () => ({ value: `${ROOT}/Zones/Work/Acme` }))
    on('env.get', async () => ({ value: '/Users/someone' }))
    on('fs.exists', async (_$: any, e: any) => ({ value: e.path === `${ROOT}/System/rules.md` || e.path in files }))
    on('fs.read', async (_$: any, e: any) => ({ value: files[e.path] ?? '' }))
    on('fs.list', async () => ({ value: ['Renewal', 'Old', 'Pricing'].map(name => ({ name, kind: 'dir', size: 0, mtimeMs: 0, isLink: false })) }) as any)
    on('turn.complete', async () => ({ text: '' }))
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
    return submitted
  }

  test('/garrick resume resumes its live threads, and Wrap wraps the one worked on', async ($, on) => {
    const submitted = await atProject($, on)
    expect((await $.command.run({ command: 'garrick', args: 'resume' } as any)).text).toBe('Resuming Acme.')
    await clock.advance(100)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    await band.press({ key: 'wrap' })
    expect(submitted[0]).toBe('Open Acme: read the Resume here block of each of its live threads (`Zones/Work/Acme/Threads/Pricing/Pricing.md`, `Zones/Work/Acme/Threads/Renewal/Renewal.md`) and tell me in a sentence or two for each where it stands and the next action.')
    expect(submitted[1]).toBe('Wrap Acme: wrap the thread this session worked on, and the hub `Zones/Work/Acme/Acme.md` too if its status changed. If the session touched no thread, say so and stop.')
  })

  test('/garrick wrap at the project wraps the thread worked on', async ($, on) => {
    const submitted = await atProject($, on)
    expect((await $.command.run({ command: 'garrick', args: 'wrap' } as any)).text).toBe('Wrapping Acme.')
    expect(submitted).toEqual([])                       // not from inside the command's own hook
    await clock.advance(100)
    expect(submitted[0]).toMatch(/^Wrap Acme: wrap the thread this session worked on/)
  })
})

describe('show and hide', () => {
  test('/garrick hide takes the band away and /garrick brings it back', async ($, on) => {
    on('ui.render', ENGINE)
    await inThread($, on, NOTE)
    const mount = () => $.ui.mount({ ...BAND, surface: 'terminal' })
    expect((await $.command.run({ command: 'garrick', args: 'hide' } as any)).text).toMatch(/hidden/)
    expect(await (await mount()).find({ key: 'wrap' })).toBeUndefined()
    expect((await $.command.run({ command: 'garrick' } as any)).text).toMatch(/^Garrick band shown/)
    expect(await (await mount()).find({ key: 'wrap' })).toBeDefined()
    expect((await $.command.run({ command: 'garrick' } as any)).text).toMatch(/^Garrick band shown/)  // never a toggle
    expect(await (await mount()).find({ key: 'wrap' })).toBeDefined()
  })

  test('any action brings a hidden band back', async ($, on) => {
    on('ui.render', ENGINE)
    await inThread($, on, NOTE)
    await $.command.run({ command: 'garrick', args: 'hide' } as any)
    await $.command.run({ command: 'garrick', args: 'note' } as any).catch(() => undefined)
    expect(await (await $.ui.mount({ ...BAND, surface: 'terminal' })).find({ key: 'wrap' })).toBeDefined()
  })
})

describe('/garrick resume and note, off the band', () => {
  test('/garrick resume submits the thread\'s prompt', async ($, on) => {
    const clock = mock.clock(on)
    const submitted: string[] = []
    on('prompt.submit', async (_$: any, e: any) => {
      submitted.push(e.text)
      return { text: e.text }
    })
    await inThread($, on, NOTE)
    expect((await $.command.run({ command: 'garrick', args: 'resume' } as any)).text).toBe('Resuming Acme.')
    await clock.advance(100)
    expect(submitted[0]).toMatch(/^Open Acme: read the Resume here block in `Zones\/Work\/Acme\/Acme.md`/)
  })

  test('/garrick note opens the Resume here pane', async ($, on) => {
    const opened: any[] = []
    on('ui.open', async (_$: any, e: any) => {
      opened.push(e)
      return { value: undefined } as any
    })
    on('ui.render', ENGINE)
    await inThread($, on, NOTE)
    expect((await $.command.run({ command: 'garrick', args: 'note' } as any)).text).toBe('Resume here pane opened.')
    const pane = await $.ui.mount({ plugin: 'garrick-band', surface: 'terminal', component: 'Pane', requestId: 'garrick-resume', props: {} } as any)
    expect(await pane.find({ text: /Where it stands/ })).toBeDefined()
  })
})

describe('Finder and Obsidian', () => {
  const VAULT = [`/usr/bin/open`, `/Applications/Obsidian.app`, `${ROOT}/Zones/Work/.obsidian`]

  test('both show where open, Obsidian and a vault are there, and open the note', async ($, on) => {
    const ran: string[][] = []
    on('process.run', async (_$: any, e: any) => {
      ran.push([...e.argv])
      return { value: { exitCode: 0, stdout: '', stderr: '' } } as any
    })
    await inThread($, on, NOTE, VAULT)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    await band.press({ key: 'obsidian' })
    await band.press({ key: 'finder' })
    const calls = ran.map(r => JSON.stringify(r))
    expect(calls.some(c => c.includes(obsidianUrl(`${ROOT}/Zones/Work/Acme/Acme.md`)))).toBe(true)
    expect(calls.some(c => c.includes('"-R"'))).toBe(true)
  })

  test('no Obsidian outside a vault', async ($, on) => {
    await inThread($, on, NOTE, VAULT.slice(0, 2))
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await band.find({ key: 'finder' })).toBeDefined()
    expect(await band.find({ key: 'obsidian' })).toBeUndefined()
  })

  test('the Obsidian link carries the path encoded', () => {
    expect(obsidianUrl('/v/a b/#1.md')).toBe('obsidian://open?path=%2Fv%2Fa%20b%2F%231.md')
  })
})

describe('Settings › Opening a thread', () => {
  const VAULT = [`/usr/bin/open`, `/Applications/Obsidian.app`, `${ROOT}/Zones/Work/.obsidian`]
  const ALL = { note: true, finder: true, cmux: true, codex: true, claude: true }

  test('read as status.py reads them: a key left out is on, or a list of those on', () => {
    expect(launcherSettings(null)).toEqual({ on: ALL, default: null })
    expect(launcherSettings('{}')).toEqual({ on: ALL, default: null })
    expect(launcherSettings('not json')).toEqual({ on: ALL, default: null })
    expect(launcherSettings('{"launchers": "note"}')).toEqual({ on: ALL, default: null })
    expect(launcherSettings('{"launchers": {"note": false}}')).toEqual({ on: { ...ALL, note: false }, default: 'note' })
    expect(launcherSettings('{"launchers": {"finder": null}, "default": "cmux"}')).toEqual({ on: { ...ALL, finder: false }, default: 'cmux' })
    expect(launcherSettings('{"launchers": ["finder", "cmux"], "default": "elsewhere"}'))
      .toEqual({ on: { note: false, finder: true, cmux: true, codex: false, claude: false }, default: 'note' })
  })

  test('While you wait tries the default first, then the others switched on', () => {
    expect(waitOrder({ on: ALL, default: null })).toEqual(['cmux', 'note', 'app'])
    expect(waitOrder({ on: ALL, default: 'note' })).toEqual(['note', 'cmux', 'finder'])
    expect(waitOrder({ on: ALL, default: 'finder' })).toEqual(['finder', 'cmux', 'note'])
    expect(waitOrder({ on: { ...ALL, note: false }, default: 'note' })).toEqual(['cmux', 'finder'])
    expect(waitOrder({ on: { ...ALL, note: false, finder: false, cmux: false }, default: 'codex' })).toEqual(['codex'])
  })

  test('with the note switched off: no Obsidian, and /garrick obsidian refuses', async ($, on) => {
    const ran: string[][] = []
    on('process.run', async (_$: any, e: any) => {
      ran.push([...e.argv])
      return { value: { exitCode: 0, stdout: '', stderr: '' } } as any
    })
    await inThread($, on, NOTE, VAULT, { launchers: { note: false, finder: true }, default: 'note' })
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await band.find({ key: 'obsidian' })).toBeUndefined()
    expect(await band.find({ key: 'finder' })).toBeDefined()
    expect((await $.command.run({ command: 'garrick', args: 'obsidian' } as any)).text).toBe('Obsidian is switched off in Settings › Opening a thread.')
    expect(ran.filter(r => r[0] === '/usr/bin/open')).toEqual([])
    const pane = await $.ui.mount({ plugin: 'garrick-band', surface: 'terminal', component: 'Pane', requestId: 'garrick-resume', props: {} } as any)
    expect(await pane.find({ key: 'pane-obsidian' })).toBeUndefined()
    expect(await pane.find({ key: 'pane-finder' })).toBeDefined()
  })

  test('with the note switched on, Obsidian installed and a vault, the button is back', async ($, on) => {
    await inThread($, on, NOTE, VAULT, { launchers: { note: true, finder: false }, default: 'note' })
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await band.find({ key: 'obsidian' })).toBeDefined()
    expect(await band.find({ key: 'finder' })).toBeUndefined()
    const pane = await $.ui.mount({ plugin: 'garrick-band', surface: 'terminal', component: 'Pane', requestId: 'garrick-resume', props: {} } as any)
    expect(await pane.find({ key: 'pane-obsidian' })).toBeDefined()
    expect(await pane.find({ key: 'pane-finder' })).toBeUndefined()
  })

  test('with Finder switched off: no Finder, and /garrick finder refuses', async ($, on) => {
    await inThread($, on, NOTE, VAULT, { launchers: ['note', 'cmux'], default: 'cmux' })
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await band.find({ key: 'finder' })).toBeUndefined()
    expect(await band.find({ key: 'obsidian' })).toBeDefined()
    expect((await $.command.run({ command: 'garrick', args: 'finder' } as any)).text).toBe(switchedOff('Finder'))
  })

  for (const [what, settings] of [['no launchers key', { 'while-you-wait': { on: true } }], ['a file that does not parse', '{"launchers": {']] as const) {
    test(`with ${what}, both show as before`, async ($, on) => {
      await inThread($, on, NOTE, VAULT, settings)
      const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
      expect(await band.find({ key: 'obsidian' })).toBeDefined()
      expect(await band.find({ key: 'finder' })).toBeDefined()
    })
  }

  test('a wiki with the note switched off offers no Obsidian on its index', async ($, on) => {
    on('session.root', async () => ({ value: `${ROOT}/Wikis/Meetings` }))
    on('session.cwd', async () => ({ value: `${ROOT}/Wikis/Meetings` }))
    on('env.get', async () => ({ value: '/Users/someone' }))
    on('fs.exists', async (_$, e: any) => ({
      value: [`${ROOT}/System/rules.md`, '/usr/bin/open', '/Applications/Obsidian.app', `${ROOT}/Wikis/.obsidian`,
              `${ROOT}/Wikis/Meetings/wiki/index.md`].includes(e.path),
    }))
    on('fs.read', async () => ({ value: JSON.stringify({ launchers: { note: false } }) }))
    on('turn.complete', async () => ({ text: '' }))
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await band.find({ key: 'finder' })).toBeDefined()
    expect(await band.find({ key: 'obsidian' })).toBeUndefined()
  })
})

describe('pane', () => {
  test('wikilinks become links to their file, or their label', () => {
    const resolve = (t: string) => (t === 'Acme/Deliverables/x' ? '/v/Zones/Work/Acme/Deliverables/x.md' : null)
    expect(paneMarkdown('See [[Acme/Deliverables/x|the sheet]] and [[Gone/y]].', resolve)).toBe(
      'See [the sheet](file:///v/Zones/Work/Acme/Deliverables/x.md) and y.',
    )
    expect(paneMarkdown('| a | [[Acme/Deliverables/x\\|sheet]] |', resolve)).toBe('| a | [sheet](file:///v/Zones/Work/Acme/Deliverables/x.md) |')
  })
})

describe('while you wait, a preview', () => {
  const PICKS = [
    { id: 'due:1', rule: 2, source: 'due', say: 'Renewal: Reply on the renewal dates (Birch, due today)', zone: 'Personal', project: 'Birch', thread: 'Renewal',
      note: 'Zones/Personal/Birch/Threads/Renewal/Renewal.md', tick: { verb: 'todo-done', zone: 'Personal', file: 'Todo.md', key: 'k1' } },
    { id: 'due:2', rule: 2, source: 'due', say: 'Pricing: Send the price list (Work, due today)', zone: 'Work', project: 'Acme', thread: 'Pricing',
      note: 'Zones/Work/Acme/Threads/Pricing/Pricing.md', tick: { verb: 'todo-done', zone: 'Work', file: 'Todo.md', key: 'k2' } },
    { id: 'inbox:Zones/Work/Inbox', rule: 4, source: 'inbox', say: "2 files in Work's Inbox: say “process the inbox”", zone: 'Work', project: null, thread: null,
      note: 'Zones/Work/Inbox' },
  ]
  const WORKING = { ...BAND, surface: 'terminal', props: { ...BAND.props, isWorking: true } }

  // A thread in Work with next_up.py and page_action.py installed; every
  // command the band runs is recorded, and next_up.py answers PICKS. The
  // preview is switched on unless `flags` says otherwise.
  async function waiting($: any, on: any, settings: object | null = null, extra: string[] = [], flags: object | string | null = { 'while-you-wait': true }) {
    const clock = mock.clock(on)
    const ran: { argv: string[]; stdin?: string }[] = []
    const submitted: string[] = []
    on('ui.render', ENGINE)
    on('prompt.submit', async (_$: any, e: any) => {
      submitted.push(e.text)
      return { text: e.text }
    })
    on('process.run', async (_$: any, e: any) => {
      ran.push({ argv: [...e.argv], stdin: e.init?.stdin })
      const stdout = String(e.argv[1]).endsWith('next_up.py') ? JSON.stringify({ on: true, picks: PICKS })
        : String(e.argv[1]).endsWith('page_action.py') ? JSON.stringify({ ok: true, say: 'Done: the line' }) : ''
      return { value: { exitCode: 0, stdout, stderr: '' } } as any
    })
    const cwd = `${ROOT}/Zones/Work/Acme`
    on('session.root', async () => ({ value: cwd }))
    on('session.cwd', async () => ({ value: cwd }))
    on('env.get', async () => ({ value: '/Users/someone' }))
    on('fs.exists', async (_$: any, e: any) => ({
      value: [`${ROOT}/System/rules.md`, `${cwd}/Acme.md`, `${ROOT}/System/tools/next_up.py`, `${ROOT}/System/status/page_action.py`, '/usr/bin/open', ...extra].includes(e.path),
    }))
    on('fs.read', async (_$: any, e: any) => {
      if (e.path.endsWith('garrick-flags.json')) {
        if (flags === null) throw new Error('no such file')
        return { value: typeof flags === 'string' ? flags : JSON.stringify(flags) }
      }
      return { value: e.path.endsWith('garrick-settings.json') ? JSON.stringify(settings ?? {}) : NOTE }
    })
    on('turn.start', async (_$: any, e: any) => ({ turnId: e.turnId }))
    on('turn.complete', async () => ({ text: '' }))
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't0', reason: 'answer' })
    const start = () => $.turn.start({ text: 'Wrap Acme', turnId: 't1' } as any)
    const end = () => $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
    const garrick = async (args: string) => (await $.command.run({ command: 'garrick', args } as any)).text
    return { clock, ran, submitted, start, end, garrick }
  }

  test('the flag: only a true in System/garrick-flags.json switches it on', () => {
    expect(previewOn('{"while-you-wait": true}', 'while-you-wait')).toBe(true)
    for (const text of [null, '{}', '{"while-you-wait": false}', '{"while-you-wait": "yes"}', '["while-you-wait"]', 'not json']) {
      expect(previewOn(text, 'while-you-wait')).toBe(false)
    }
  })

  for (const [what, flags] of [['no flags file', null], ['the flag off', { 'while-you-wait': false }], ['a file that does not read', '{"while']] as const) {
    test(`with ${what}: no line, and the four words say it is a preview`, async ($, on) => {
      const w = await waiting($, on, null, [], flags as any)
      await w.start()
      await w.clock.advance(120_000)
      const band = await $.ui.mount(WORKING)
      expect(await band.find({ text: /While you wait/ })).toBeUndefined()
      expect(await band.find({ key: 'wait-open' })).toBeUndefined()
      expect(w.ran.filter(r => r.argv[1]!.endsWith('next_up.py'))).toHaveLength(0)
      for (const word of ['next', 'open', 'tick', 'later']) expect(await w.garrick(word)).toBe(waitOff)
      expect(w.ran.filter(r => r.argv[1]!.endsWith('page_action.py'))).toHaveLength(0)
      expect(await band.find({ key: 'wrap' })).toBeDefined()                // the band itself is as before
    })
  }

  test('settings: the defaults, what is saved, and what does not read', () => {
    expect(waitSettings(null)).toEqual({ on: true, threshold: 45 })
    expect(waitSettings('{"while-you-wait": {"on": false, "threshold": 90}}')).toEqual({ on: false, threshold: 90 })
    expect(waitSettings('{"while-you-wait": {"threshold": 2}}')).toEqual({ on: true, threshold: 45 })
    expect(waitSettings('not json')).toEqual({ on: true, threshold: 45 })
  })

  test('next_up.py is asked for the session zone, never the thread the session is in', () => {
    const n = { path: '/v/Zones/Work/Acme/Threads/Pricing/Pricing.md', rel: 'Zones/Work/Acme/Threads/Pricing/Pricing.md', where: '', title: 'Pricing',
      status: 'active', heading: null, resume: null, finder: true, obsidian: false, threads: [] }
    expect(rootOf(n)).toBe('/v')
    expect(zoneOf(n.rel)).toBe('Work')
    expect(nextUpArgv(n)).toEqual(['python3', '/v/System/tools/next_up.py', '--root', '/v', '--zone', 'Work', '--exclude', 'Zones/Work/Acme/Threads/Pricing'])
    const home = { ...n, path: '/v/System', rel: 'System', title: 'System' }
    expect(nextUpArgv(home)).toEqual(['python3', '/v/System/tools/next_up.py', '--root', '/v'])
    expect(pageActionArgv('/v')).toEqual(['python3', '/v/System/status/page_action.py', '--workspace', '/v'])
  })

  test('one line once a turn has run past the threshold, and gone when it ends', async ($, on) => {
    const w = await waiting($, on)
    await w.start()
    await w.clock.advance(44_000)
    expect(await (await $.ui.mount(WORKING)).find({ text: /While you wait/ })).toBeUndefined()
    expect(w.ran.filter(r => r.argv[1]!.endsWith('next_up.py'))).toHaveLength(0)
    await w.clock.advance(2_000)
    const band = await $.ui.mount(WORKING)
    expect(await band.find({ text: /Reply on the renewal dates/ })).toBeDefined()
    for (const key of ['wait-open', 'wait-next', 'wait-tick', 'wait-later']) expect(await band.find({ key })).toBeDefined()
    expect(w.ran.find(r => r.argv[1]!.endsWith('next_up.py'))!.argv).toContain('--exclude')
    await w.end()
    expect(await (await $.ui.mount(WORKING)).find({ text: /While you wait/ })).toBeUndefined()
  })

  test('not while the band is idle, and never when it is switched off', async ($, on) => {
    const w = await waiting($, on, { 'while-you-wait': { on: false } })
    await w.start()
    await w.clock.advance(120_000)
    expect(await (await $.ui.mount(WORKING)).find({ text: /While you wait/ })).toBeUndefined()
    expect(w.ran.filter(r => r.argv[1]!.endsWith('next_up.py'))).toHaveLength(0)
  })

  test('the threshold is a setting', async ($, on) => {
    const w = await waiting($, on, { 'while-you-wait': { threshold: 120 } })
    await w.start()
    await w.clock.advance(60_000)
    expect(await (await $.ui.mount(WORKING)).find({ text: /While you wait/ })).toBeUndefined()
    await w.clock.advance(61_000)
    expect(await (await $.ui.mount(WORKING)).find({ text: /While you wait/ })).toBeDefined()
  })

  test('/garrick next shows the next one, later puts the line away for the turn', async ($, on) => {
    const w = await waiting($, on)
    await w.start()
    await w.clock.advance(46_000)
    expect(await w.garrick('next')).toBe('While you wait: Pricing: Send the price list (Work, due today)')
    expect(await (await $.ui.mount(WORKING)).find({ text: /Send the price list/ })).toBeDefined()
    expect(await w.garrick('later')).toBe('Put away for this turn.')
    expect(await (await $.ui.mount(WORKING)).find({ text: /While you wait/ })).toBeUndefined()
    expect(w.submitted).toEqual([])                                    // nothing reached the running session
  })

  test('a tick in another zone goes at once, through page_action.py on stdin', async ($, on) => {
    const w = await waiting($, on)
    await w.start()
    await w.clock.advance(46_000)
    expect(await w.garrick('tick')).toBe('Done: the line')
    const call = w.ran.find(r => r.argv[1]!.endsWith('page_action.py'))!
    expect(call.argv).toEqual(['python3', `${ROOT}/System/status/page_action.py`, '--workspace', ROOT])
    expect(JSON.parse(call.stdin!)).toEqual({ verb: 'todo-done', zone: 'Personal', file: 'Todo.md', key: 'k1' })
    expect(await (await $.ui.mount(WORKING)).find({ text: /Send the price list/ })).toBeDefined()      // the next one
    expect(w.submitted).toEqual([])
  })

  test('a tick in the running turn\'s zone waits for the turn to end', async ($, on) => {
    const w = await waiting($, on)
    await w.start()
    await w.clock.advance(46_000)
    await w.garrick('next')
    expect(await w.garrick('tick')).toMatch(/^Ticks when the turn ends, since it works in Work/)
    expect(w.ran.filter(r => r.argv[1]!.endsWith('page_action.py'))).toHaveLength(0)
    await w.end()
    const call = w.ran.find(r => r.argv[1]!.endsWith('page_action.py'))!
    expect(JSON.parse(call.stdin!).key).toBe('k2')
  })

  test('open never touches the running session', async ($, on) => {
    const w = await waiting($, on)
    await w.start()
    await w.clock.advance(46_000)
    expect(await w.garrick('open')).toBe('Opened Renewal.')
    expect(w.ran.some(r => r.argv[0] === '/usr/bin/open' && r.argv[1] === `${ROOT}/Zones/Personal/Birch/Threads/Renewal/Renewal.md`)).toBe(true)
    expect(w.submitted).toEqual([])
  })

  // Renewal, the first pick, sits in the Personal zone's vault.
  const VAULT = ['/Applications/Obsidian.app', `${ROOT}/Zones/Personal/.obsidian`]
  const RENEWAL = `${ROOT}/Zones/Personal/Birch/Threads/Renewal/Renewal.md`
  const opened = (w: any) => w.ran.filter((r: any) => r.argv[0] === '/usr/bin/open').map((r: any) => r.argv.slice(1))

  test('open follows the default: the note in Obsidian', async ($, on) => {
    const w = await waiting($, on, { launchers: { note: true, finder: true, cmux: true }, default: 'note' }, VAULT)
    await w.start()
    await w.clock.advance(46_000)
    expect(await w.garrick('open')).toBe('Opened Renewal in Obsidian.')
    expect(opened(w)).toEqual([[obsidianUrl(RENEWAL)]])
  })

  test('open follows the default: Finder, even in a vault', async ($, on) => {
    const w = await waiting($, on, { launchers: { note: true, finder: true }, default: 'finder' }, VAULT)
    await w.start()
    await w.clock.advance(46_000)
    expect(await w.garrick('open')).toBe('Opened Renewal in Finder.')
    expect(opened(w)).toEqual([['-R', RENEWAL]])
  })

  test('with the note switched off, open falls back to the first launcher on that can run', async ($, on) => {
    const w = await waiting($, on, { launchers: { note: false, finder: true, cmux: true }, default: 'note' }, VAULT)
    await w.start()
    await w.clock.advance(46_000)
    expect(await w.garrick('open')).toBe('Opened Renewal in Finder.')       // no desk, so no cmux
    expect(opened(w)).toEqual([['-R', RENEWAL]])
  })

  test('with nothing on that the band can run, open says so and opens nothing', async ($, on) => {
    const w = await waiting($, on, { launchers: ['claude'], default: 'claude' }, VAULT)
    await w.start()
    await w.clock.advance(46_000)
    expect(await w.garrick('open')).toBe('Nothing switched on in Settings › Opening a thread can open it here.')
    expect(opened(w)).toEqual([])
  })

  test('with nothing on offer, the commands say so', async ($, on) => {
    const w = await waiting($, on)
    expect(await w.garrick('next')).toMatch(/^Nothing is on offer/)
    expect(await w.garrick('tick')).toBe('Nothing is on offer to tick.')
  })
})

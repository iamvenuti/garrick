import { describe, expect, mock, test } from 'claude-code/testing'

import { buildIndex, cut, fileHref, label, linkify, lookup, markCells, nextUpArgv, obsidianUrl, pageActionArgv, paneMarkdown, parseNote, plain, promptLine, resumePrompt, rootOf, stepLine, waitSettings, wrapPrompt, zoneOf } from './register'

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
    expect(parsed.heading).toBe('Outcome')
    expect(parsed.lead).toBe('Signed on 2 October.')
  })

  test('the prompts name the thread and its note', () => {
    const n = { path: '/v/Zones/Work/Acme/Acme.md', rel: 'Zones/Work/Acme/Acme.md', where: 'Work › Acme', title: 'Acme', ...parseNote(NOTE), finder: true, obsidian: false, threads: [] }
    expect(resumePrompt(n)).toBe('Open Acme: read the Resume here block in `Zones/Work/Acme/Acme.md` and tell me in two sentences where it stands and the next action.')
    expect(wrapPrompt(n)).toMatch(/^Wrap Acme: rewrite the Resume here block in `Zones\/Work\/Acme\/Acme.md`/)
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

const BAND = {
  plugin: 'garrick-band',
  component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 100 },
} as any

async function inThread($: any, on: any, text: string, extra: string[] = []) {
  const cwd = `${ROOT}/Zones/Work/Acme`
  on('session.root', async () => ({ value: cwd }))
  on('session.cwd', async () => ({ value: `${ROOT}/System/tools` }))      // a cd in a tool call: the band keeps its thread
  on('env.get', async () => ({ value: '/Users/someone' }))
  on('fs.exists', async (_$: any, e: any) => ({
    value: [`${ROOT}/System/rules.md`, `${cwd}/Acme.md`, ...extra].includes(e.path),
  }))
  on('fs.read', async () => ({ value: text }))
  on('turn.complete', async () => ({ text: '' }))
  await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
}

describe('band', () => {
  for (const surface of ['terminal', 'desktop'] as const) {
    test(`draws the thread on ${surface}`, async ($, on) => {
      await inThread($, on, NOTE)
      const band = await $.ui.mount({ ...BAND, surface })

      expect(await band.find({ text: /Work › Acme/ })).toBeDefined()
      for (const key of ['resume', 'wrap', 'clear', 'note']) expect(await band.find({ key })).toBeDefined()
      expect(await band.find({ key: 'finder' })).toBeUndefined()
    })

    test(`Resume and Wrap submit the thread's prompt on ${surface}`, async ($, on) => {
      const submitted: string[] = []
      on('prompt.submit', async (_$, e: any) => {
        submitted.push(e.text)
        return { text: e.text }
      })
      await inThread($, on, NOTE)
      const band = await $.ui.mount({ ...BAND, surface })

      await band.press({ key: 'resume' })
      await band.press({ key: 'wrap' })
      expect(submitted).toHaveLength(2)
      expect(submitted[0]).toMatch(/^Open Acme: read the Resume here block in `Zones\/Work\/Acme\/Acme.md`/)
      expect(submitted[1]).toMatch(/^Wrap Acme:/)
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

    expect(await band.find({ key: 'resume' })).toBeDefined()
    expect(await band.find({ key: 'wrap' })).toBeUndefined()
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
    expect(await band.find({ key: 'resume' })).toBeUndefined()
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

  test('shows the place with no Resume line', async ($, on) => {
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
    expect(await band.find({ key: 'resume' })).toBeUndefined()
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

  test('names its live threads, resumes them all, and wraps the one worked on', async ($, on) => {
    const submitted = await atProject($, on)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await band.find({ text: /2 threads: Pricing, Renewal/ })).toBeDefined()
    expect(await band.find({ key: 'note' })).toBeDefined()
    await band.press({ key: 'resume' })
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
    expect(await (await mount()).find({ key: 'resume' })).toBeUndefined()
    expect((await $.command.run({ command: 'garrick' } as any)).text).toMatch(/^Garrick band shown/)
    expect(await (await mount()).find({ key: 'resume' })).toBeDefined()
    expect((await $.command.run({ command: 'garrick' } as any)).text).toMatch(/^Garrick band shown/)  // never a toggle
    expect(await (await mount()).find({ key: 'resume' })).toBeDefined()
  })

  test('any action brings a hidden band back', async ($, on) => {
    on('ui.render', ENGINE)
    await inThread($, on, NOTE)
    await $.command.run({ command: 'garrick', args: 'hide' } as any)
    await $.command.run({ command: 'garrick', args: 'note' } as any).catch(() => undefined)
    expect(await (await $.ui.mount({ ...BAND, surface: 'terminal' })).find({ key: 'resume' })).toBeDefined()
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

describe('activity', () => {
  test('the band shows the last prompt and the step it is on', async ($, on) => {
    on('prompt.submit', async (_$: any, e: any) => ({ text: e.text }))
    on('tool.call', async () => ({ result: '' }))
    await inThread($, on, NOTE)
    await $.prompt.submit({ text: '\n  Fix the **pricing** table\nand more' } as any)
    await $.tool.call({ tool: 'Edit', file_path: '/v/x/sheet.md', old_string: 'a', new_string: 'b' } as any).catch(() => undefined)
    const working = await $.ui.mount({ ...BAND, surface: 'terminal', props: { ...BAND.props, isWorking: true } })
    expect(await working.find({ text: /Fix the pricing table/ })).toBeDefined()
    expect(await working.find({ text: /Editing sheet\.md/ })).toBeDefined()
    expect(await working.find({ text: /Where it stands/ })).toBeUndefined()
  })

  test('before any prompt the band shows the Resume line', async ($, on) => {
    await inThread($, on, NOTE)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await band.find({ text: /Where it stands/ })).toBeDefined()
  })

  test('steps and prompts in a few words', () => {
    expect(promptLine('\n\n  Open **Acme**: read [[a/b|the note]]\nsecond')).toBe('Open Acme: read the note')
    expect(stepLine({ tool: 'Bash', command: 'npm test', description: 'Run the tests' })).toBe('Run the tests')
    expect(stepLine({ tool: 'Bash', command: 'ls -la\npwd' })).toBe('$ ls -la')
    expect(stepLine({ tool: 'Read', file_path: '/v/a/b.md' })).toBe('Reading b.md')
    expect(stepLine({ tool: 'Grep', pattern: 'TODO' })).toBe('Searching for TODO')
    expect(stepLine({ tool: 'mcp__claude_ai_Gmail__search_threads' })).toBe('Gmail: search threads')
    expect(cut('abcdefghij', 5)).toBe('abcd…')
    expect(cut('abc', 5)).toBe('abc')
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

describe('while you wait', () => {
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
  // command the band runs is recorded, and next_up.py answers PICKS.
  async function waiting($: any, on: any, settings: object | null = null) {
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
      value: [`${ROOT}/System/rules.md`, `${cwd}/Acme.md`, `${ROOT}/System/tools/next_up.py`, `${ROOT}/System/status/page_action.py`, '/usr/bin/open'].includes(e.path),
    }))
    on('fs.read', async (_$: any, e: any) => ({ value: e.path.endsWith('garrick-settings.json') ? JSON.stringify(settings ?? {}) : NOTE }))
    on('turn.start', async (_$: any, e: any) => ({ turnId: e.turnId }))
    on('turn.complete', async () => ({ text: '' }))
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't0', reason: 'answer' })
    const start = () => $.turn.start({ text: 'Wrap Acme', turnId: 't1' } as any)
    const end = () => $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
    const garrick = async (args: string) => (await $.command.run({ command: 'garrick', args } as any)).text
    return { clock, ran, submitted, start, end, garrick }
  }

  test('settings: the defaults, what is saved, and what does not read', () => {
    expect(waitSettings(null)).toEqual({ on: true, threshold: 45 })
    expect(waitSettings('{"while-you-wait": {"on": false, "threshold": 90}}')).toEqual({ on: false, threshold: 90 })
    expect(waitSettings('{"while-you-wait": {"threshold": 2}}')).toEqual({ on: true, threshold: 45 })
    expect(waitSettings('not json')).toEqual({ on: true, threshold: 45 })
  })

  test('next_up.py is asked for the session zone, never the thread the session is in', () => {
    const n = { path: '/v/Zones/Work/Acme/Threads/Pricing/Pricing.md', rel: 'Zones/Work/Acme/Threads/Pricing/Pricing.md', where: '', title: 'Pricing',
      status: 'active', heading: null, lead: null, resume: null, finder: true, obsidian: false, threads: [] }
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

  test('with nothing on offer, the commands say so', async ($, on) => {
    const w = await waiting($, on)
    expect(await w.garrick('next')).toMatch(/^Nothing is on offer/)
    expect(await w.garrick('tick')).toBe('Nothing is on offer to tick.')
  })
})

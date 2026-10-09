import { describe, expect, test } from 'claude-code/testing'

import { buildIndex, cut, fileHref, label, linkify, lookup, markCells, obsidianUrl, paneMarkdown, parseNote, plain, promptLine, resumePrompt, stepLine, wrapPrompt } from './register'

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
    const n = { path: '/v/Zones/Work/Acme/Acme.md', rel: 'Zones/Work/Acme/Acme.md', where: 'Work › Acme', title: 'Acme', ...parseNote(NOTE), finder: true, obsidian: false }
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

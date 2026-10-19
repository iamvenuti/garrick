export type Note = {
  path: string
  rel: string
  where: string
  title: string
  status: string | null
  heading: string | null
  lead: string | null
  resume: string | null
  // Where the note can be opened: Finder (macOS's `open`) and Obsidian, when
  // it is installed and the note sits in a vault; each only while Settings ›
  // Opening a thread has it switched on (`finder`, and `note` for Obsidian).
  finder: boolean
  obsidian: boolean
  // A project whose hub has no Resume here block: its live threads, each with
  // its own block. Empty for a thread, or a project that is its own thread.
  threads: Thread[]
}

export type Thread = {
  title: string
  rel: string
  heading: string | null
  resume: string
}

// The last prompt of the session and the step the assistant is on.
export type Activity = {
  prompt: string
  step: string | null
}

// One thing to do while a long turn runs, as System/tools/next_up.py ranks it.
export type WaitPick = {
  id: string
  rule: number
  source: string
  say: string
  zone: string | null
  project: string | null
  thread: string | null
  // The note, folder or Todo.md it opens, from the workspace root.
  note: string | null
  // On a Todo line: the request page_action.py takes on stdin to tick it.
  tick?: { verb: string; zone: string; file: string; key: string }
}

// The While you wait line of the turn that is running: its picks, the one on
// show, when they were read, whether it was put away for this turn, and the
// ids already shown, so a fresh read never offers one twice.
export type Wait = {
  turnId: string
  picks: WaitPick[]
  index: number
  at: number
  hidden: boolean
  shown: string[]
}

declare module 'claude-code' {
  interface PluginState {
    'garrick-band': { note: Note | null; isHidden: boolean; activity: Activity | null; wait: Wait | null }
  }
}

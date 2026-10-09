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
  // it is installed and the note sits in a vault.
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

declare module 'claude-code' {
  interface PluginState {
    'garrick-band': { note: Note | null; isHidden: boolean; activity: Activity | null }
  }
}

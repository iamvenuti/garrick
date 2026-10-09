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

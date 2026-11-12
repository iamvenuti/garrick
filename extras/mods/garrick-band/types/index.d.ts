export type Note = {
  path: string
  rel: string
  where: string
  title: string
  status: string | null
  heading: string | null
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

// What the band's one slot offers (see bandSlot in hooks/register.tsx): null is nothing.
export type Slot = 'wrap' | 'resume' | 'wrapping' | null

export type Thread = {
  title: string
  rel: string
  heading: string | null
  resume: string
}

declare module 'claude-code' {
  interface PluginState {
    // used: how full the context window is, a whole percentage, or null while the API has no figure.
    // slot: what the band's one slot offers; 'unknown' until the band has looked once.
    'garrick-band': { note: Note | null; isHidden: boolean; used: number | null; slot: Slot | 'unknown' }
  }
}

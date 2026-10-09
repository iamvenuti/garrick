export type Note = {
  path: string
  where: string
  title: string
  status: string | null
  lead: string | null
  resume: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'garrick-band': { note: Note | null; isHidden: boolean }
  }
}

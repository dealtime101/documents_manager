export type Note = { ok: boolean; text: string } | null

/** A failed reload is always shown, after the result of the action that came before it, whether that succeeded or failed (DOC534.228). */
export function withReloadError(note: Note, error: string, msg: (text: string) => string): Note {
  return error ? { ok: false, text: `${note ? `${note.text} ` : ''}${msg(error)}` } : note
}

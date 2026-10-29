/** The file name of a path as the server wrote it: POSIX ('/') or Windows ('\') separators. */
export const baseName = (path: string) => path.split(/[\\/]/).pop() || path

/** The folder part of a path, with either separator ('' when the path has none). */
export const dirName = (path: string) => {
  const i = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
  return i < 0 ? '' : i === 0 ? path.slice(0, 1) : path.slice(0, i)
}

/** The line (counted from 1) of the `index`-th (from 0) non-empty line of a text area. The server counts the entries it was sent
 *  (the empty lines are not), the person counts the lines of the box: this is how an error "entry 2" is shown as "line 4". */
export const lineOfEntry = (text: string, index: number): number | null => {
  let seen = -1
  const lines = text.split('\n')
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim()) {
      seen += 1
      if (seen === index) return i + 1
    }
  }
  return null
}

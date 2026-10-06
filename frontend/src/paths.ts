/** The file name of a path as the server wrote it: POSIX ('/') or Windows ('\') separators. */
export const baseName = (path: string) => path.split(/[\\/]/).pop() || path

/** The folder part of a path, with either separator ('' when the path has none). */
export const dirName = (path: string) => {
  const i = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
  return i < 0 ? '' : i === 0 ? path.slice(0, 1) : path.slice(0, i)
}

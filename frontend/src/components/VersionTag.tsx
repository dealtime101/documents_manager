/** The program's version beside the title, "v0.x.y"; nothing while the server has not said it yet (DOC534.243: rendered by a test). */
export default function VersionTag({ version }: { version: string }) {
  return version ? <span className="ml-2 text-xs font-normal text-slate-600">v{version}</span> : null
}

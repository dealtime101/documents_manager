/** French typography: a no-break space before : ; ! ? and » and after «, so a line never ends on « or starts on a lone ":".
 *  Applied to the TEXT OF THE MESSAGES (written with plain spaces, easier to type and to compare), never to what the server sends.
 *  The no-break space is named and built from its code: as a literal it is indistinguishable from a plain space and one reformat would undo it. */
const NBSP = String.fromCharCode(0xa0)
/** Items of a list in one line: "a; b" in English, "a ; b" in French with the no-break space the language asks for before a semicolon.
 *  The items are built at run time, so frenchSpaces (which only reads the message texts) never sees this separator. */
export const joinList = (items: string[], french: boolean): string => items.join(french ? `${NBSP}; ` : '; ')
export const frenchSpaces = (s: string): string => s.replace(/ ([:;!?»])/g, `${NBSP}$1`).replace(/« /g, `«${NBSP}`)

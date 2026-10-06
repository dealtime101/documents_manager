/** French typography: a no-break space before : ; ! ? and » and after «, so a line never ends on « or starts on a lone ":".
 *  Applied to the TEXT OF THE MESSAGES (written with plain spaces, easier to type and to compare), never to what the server sends. */
export const frenchSpaces = (s: string): string => s.replace(/ ([:;!?»])/g, ' $1').replace(/« /g, '« ')

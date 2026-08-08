/** True for routes that mount the Reader, which owns horizontal swipe for page
 *  turns. The global edge-swipe-back gesture must stay disarmed there. */
const READER_PREFIXES = ['/reader/', '/e-hentai/read/']

export function isReaderPath(pathname: string): boolean {
  return READER_PREFIXES.some((prefix) => pathname.startsWith(prefix))
}

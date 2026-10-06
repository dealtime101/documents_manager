import type { AskKey } from '@/i18n'

/** The kinds of operation the server writes in its history (docflow pipeline: add_op) and their labels. */
const OP_KEYS: Record<string, AskKey> = { move: 'op.move', quarantine: 'op.quarantine' }

/** The label of an operation. A kind added by a newer server is shown under its own name rather than as a raw key. */
export const opLabel = (t: (key: AskKey) => string, kind: string): string => (Object.hasOwn(OP_KEYS, kind) ? t(OP_KEYS[kind]) : kind)

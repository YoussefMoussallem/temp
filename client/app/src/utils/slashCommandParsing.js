/**
 * Slash-command parser.
 *
 * Port of src/utils/slashCommandParsing.ts. Mirrors the Python backend at
 * server/backend/app/agent/utils/slash_command_parsing.py.
 */

const SLASH_RE = /^\s*\/(\S+)(?:\s+([\s\S]*))?\s*$/

/**
 * Parse a "/command args" string.
 *
 * @param {string} input
 * @returns {{ name: string, args: string } | null}
 */
export function parseSlashCommand(input) {
  if (typeof input !== 'string' || !input.trim()) return null
  const m = SLASH_RE.exec(input)
  if (!m) return null
  const name = (m[1] || '').trim()
  if (!name) return null
  const args = (m[2] || '').trim()
  return { name: name.toLowerCase(), args }
}

/** Cheap prefix check. Matches source `isCommandInput`. */
export function isCommandInput(input) {
  if (typeof input !== 'string') return false
  return input.trimStart().startsWith('/')
}

/**
 * Detect a slash-command start mid-input (e.g. the user typed text, a space,
 * then a /). Used by the typeahead to surface suggestions even when / isn't
 * the first character.
 *
 * Returns the slash position and the (possibly empty) partial command name
 * the user has typed so far. Returns null when:
 *   - there's no slash at/before the cursor
 *   - the slash is in the middle of a word (path / url, not a command)
 *   - the cursor is past whitespace after the command name (the user has
 *     moved on to typing arguments — the typeahead should close)
 *
 * Notably, a bare ``/`` with cursor right after it returns ``{name: ""}``
 * so the suggestion engine can show the full alphabetical list. Source's
 * parseSlashCommand regex requires at least one non-space character after
 * the slash, which is correct for parsing a *complete* command but wrong
 * for the typeahead's "user just hit /" moment.
 *
 * @param {string} input
 * @param {number} cursorOffset
 * @returns {{ startIndex: number, name: string, args: string } | null}
 */
export function findMidInputSlashCommand(input, cursorOffset) {
  if (typeof input !== 'string' || !input) return null
  const upto = input.slice(0, cursorOffset)
  const lastSlash = upto.lastIndexOf('/')
  if (lastSlash < 0) return null
  const before = lastSlash === 0 ? '' : upto[lastSlash - 1]
  // A slash counts as the start of a command iff it's the first char or
  // preceded by whitespace. Otherwise we're in the middle of a path/url.
  if (before && !/\s/.test(before)) return null
  // Slice from the slash to the caret. If it contains any whitespace,
  // the user has finished the command name and is now typing args (or
  // has moved past) — close the dropdown.
  const tokenUpToCursor = upto.slice(lastSlash)
  if (/\s/.test(tokenUpToCursor)) return null
  const name = tokenUpToCursor.slice(1)
  return { startIndex: lastSlash, name, args: '' }
}

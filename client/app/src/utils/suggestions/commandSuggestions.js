/**
 * Slash-command suggestions backed by Fuse.js fuzzy match.
 *
 * Port of src/utils/suggestions/commandSuggestions.ts.
 */

import Fuse from 'fuse.js'
import { getCommandName } from '../../commands/index.js'
import {
  findMidInputSlashCommand,
  isCommandInput,
  parseSlashCommand,
} from '../slashCommandParsing.js'

const FUSE_OPTIONS = {
  // Keys to fuzzy-match against. Name weighted highest; aliases + description
  // provide fallback matching when the user types keywords instead of names.
  keys: [
    { name: 'name', weight: 3 },
    { name: 'aliases', weight: 2 },
    { name: 'description', weight: 1 },
  ],
  // Tolerant but not sloppy — matches source tuning.
  threshold: 0.4,
  ignoreLocation: true,
  includeScore: true,
}

function buildIndex(commands) {
  const list = commands
    .filter((c) => !c.isHidden)
    .map((c) => ({
      name: getCommandName(c),
      aliases: c.aliases ?? [],
      description: c.description ?? '',
      _cmd: c,
    }))
  return { fuse: new Fuse(list, FUSE_OPTIONS), list }
}

/**
 * Generate suggestion entries for the current input.
 *
 * @param {string} value    Full input text.
 * @param {Array}  commands All available commands.
 * @param {number} [cursorOffset=value.length] Where the caret is.
 * @returns {Array<{ label: string, description: string, command: object, score: number }>}
 */
export function generateCommandSuggestions(value, commands, cursorOffset) {
  if (!commands?.length) return []
  const offset = cursorOffset ?? (value?.length ?? 0)
  const mid = findMidInputSlashCommand(value ?? '', offset)
  if (!mid) return []
  const { fuse, list } = buildIndex(commands)
  // Empty query (just "/") — return everything, sorted by primary name.
  if (!mid.name) {
    return list
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((r) => ({
        label: r.name,
        description: r.description,
        command: r._cmd,
        score: 0,
      }))
  }
  const results = fuse.search(mid.name)
  return results.map((r) => ({
    label: r.item.name,
    description: r.item.description,
    command: r.item._cmd,
    score: r.score ?? 0,
  }))
}

/** Best single match, or null if no suggestion scored above the threshold. */
export function getBestCommandMatch(input, commands) {
  const suggestions = generateCommandSuggestions(input, commands, input?.length ?? 0)
  return suggestions[0] ?? null
}

/**
 * Replace the current slash token with the chosen command's name.
 *
 * @returns {{ value: string, cursorOffset: number }}
 */
export function applyCommandSuggestion(suggestion, input, cursorOffset) {
  const offset = cursorOffset ?? (input?.length ?? 0)
  const mid = findMidInputSlashCommand(input ?? '', offset)
  if (!mid) {
    // Shouldn't happen — caller only invokes this when a suggestion was shown.
    const replacement = `/${suggestion.label} `
    return { value: replacement, cursorOffset: replacement.length }
  }
  const head = input.slice(0, mid.startIndex)
  const tail = input.slice(offset)
  const replacement = `/${suggestion.label} `
  const next = head + replacement + tail
  return { value: next, cursorOffset: head.length + replacement.length }
}

// Re-exports so callers only need one import.
export { isCommandInput, parseSlashCommand, findMidInputSlashCommand }

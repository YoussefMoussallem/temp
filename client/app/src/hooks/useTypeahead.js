/**
 * Slash-command typeahead hook.
 *
 * Port of src/hooks/useTypeahead.tsx (React, not Ink). Exposes:
 *   - suggestions: the current suggestion list
 *   - selectedIdx: index of the highlighted suggestion
 *   - setSelectedIdx, moveSelection: selection navigation
 *   - applySelected(): replace the current slash token with the chosen command
 *   - commandArgumentHint: argument hint for the matched command (if unique)
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  applyCommandSuggestion,
  generateCommandSuggestions,
} from '../utils/suggestions/commandSuggestions.js'
import { getCommands, subscribeRegistry } from '../commands/index.js'

const MAX_SUGGESTIONS = 8

/**
 * @param {{
 *   value: string,
 *   cursorOffset?: number,
 *   onValueChange: (next: string, nextCursor: number) => void,
 *   disabled?: boolean,
 * }} params
 */
export function useTypeahead({ value, cursorOffset, onValueChange, disabled = false }) {
  const [selectedIdx, setSelectedIdx] = useState(0)

  // Re-read the merged command list whenever the backend registry
  // changes (priming completes, or someone calls invalidateRegistry).
  // Without the subscription, the typeahead would freeze on the empty
  // pre-prime client-handler list, since ``primeRegistry`` resolves
  // asynchronously in App.jsx after this hook has already mounted.
  const [commands, setCommands] = useState(() => getCommands())
  useEffect(() => {
    return subscribeRegistry(() => setCommands(getCommands()))
  }, [])

  const suggestions = useMemo(() => {
    if (disabled) return []
    return generateCommandSuggestions(value, commands, cursorOffset).slice(0, MAX_SUGGESTIONS)
  }, [value, cursorOffset, commands, disabled])

  // Reset highlight whenever the suggestion list changes shape.
  useEffect(() => {
    setSelectedIdx(0)
  }, [suggestions.length, value])

  const moveSelection = useCallback(
    (delta) => {
      if (!suggestions.length) return
      setSelectedIdx((i) => (i + delta + suggestions.length) % suggestions.length)
    },
    [suggestions.length],
  )

  const applyAt = useCallback(
    (idx) => {
      const s = suggestions[idx]
      if (!s) return false
      const { value: next, cursorOffset: nextCursor } = applyCommandSuggestion(
        s,
        value,
        cursorOffset,
      )
      onValueChange(next, nextCursor)
      return true
    },
    [suggestions, value, cursorOffset, onValueChange],
  )

  const applySelected = useCallback(
    () => applyAt(selectedIdx),
    [applyAt, selectedIdx],
  )

  const commandArgumentHint = useMemo(() => {
    // Show the hint only when exactly one suggestion remains and the user
    // typed at least one character past the slash — matches source behavior.
    if (suggestions.length !== 1) return null
    const cmd = suggestions[0].command
    return cmd.argumentHint ?? cmd.argument_hint ?? null
  }, [suggestions])

  return {
    suggestions,
    selectedIdx,
    setSelectedIdx,
    moveSelection,
    applySelected,
    applyAt,
    commandArgumentHint,
  }
}

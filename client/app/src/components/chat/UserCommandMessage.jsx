/**
 * UserCommandMessage — renders a slash-command expansion as a chip.
 *
 * Port of src/components/messages/UserCommandMessage.tsx. When a user message's
 * text content begins with `<command-name>...`, the backend expanded a
 * /command into three tagged blocks. We collapse that to a compact chip so
 * the UI doesn't show the raw XML tags.
 */

import { Terminal } from 'lucide-react'

const NAME_RE = /^<command-name>(.*?)<\/command-name>/
const ARGS_RE = /^<command-args>(.*?)<\/command-args>/

/**
 * Extract the command name + args from a message's content blocks.
 *
 * Returns null if this doesn't look like a command expansion. Accepts either
 * a string or a list of content blocks — the backend emits the latter but
 * some callers flatten first.
 */
export function parseCommandExpansion(content) {
  const texts = toTextList(content)
  if (!texts.length) return null
  const nameMatch = NAME_RE.exec(texts[0])
  if (!nameMatch) return null
  let args = ''
  for (const t of texts.slice(1)) {
    const a = ARGS_RE.exec(t)
    if (a) {
      args = a[1] ?? ''
      break
    }
  }
  return { name: nameMatch[1], args }
}

function toTextList(content) {
  if (typeof content === 'string') return [content]
  if (!Array.isArray(content)) return []
  return content
    .filter((b) => b && (b.type === 'text' || typeof b === 'string'))
    .map((b) => (typeof b === 'string' ? b : b.text ?? ''))
}

export default function UserCommandMessage({ content }) {
  const parsed = parseCommandExpansion(content)
  if (!parsed) return null
  return (
    <div className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-[12px] text-gray-700">
      <Terminal size={12} className="text-gray-400" strokeWidth={2} />
      <span className="font-mono text-gray-900">{parsed.name}</span>
      {parsed.args ? <span className="text-gray-400">·</span> : null}
      {parsed.args ? <span className="truncate">{parsed.args}</span> : null}
    </div>
  )
}

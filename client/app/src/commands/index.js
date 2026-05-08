/**
 * Command registry — backend owns commands; frontend keeps a thin
 * client-handler set for UI-only operations the backend can't perform.
 *
 * Architecture:
 *   - Backend `/commands` endpoint is the source of truth for the user-visible
 *     command list (typeahead, /help). Backend commands declare
 *     `execution: "server"` and run via /turn with a command_uuid.
 *     `/clear` lives on the backend now (it truncates DB + Redis and the
 *     frontend refetches messages on lifecycle:completed — see useChat.js).
 *   - The frontend keeps only commands that have no backend equivalent because
 *     they act on transient client UI state:
 *       * `/tasks` — reads context.tasks (populated by tool-progress SSE
 *         events). Pure UI display of streamed task data. Currently
 *         registered as `isHidden: true` until the populator lands.
 *   - Merge rule: union by name; backend entries win on conflict.
 */

import tasks from './tasks/index.js'

const CLIENT_HANDLERS = [tasks]

function clientByName(name) {
  const lower = name.toLowerCase()
  return CLIENT_HANDLERS.find(
    (c) => c.name === lower || c.aliases?.map((a) => a.toLowerCase()).includes(lower),
  )
}

function clientToRegistryEntry(c) {
  return {
    name: c.name,
    description: c.description ?? '',
    aliases: c.aliases ?? [],
    argument_hint: c.argumentHint ?? '',
    argumentHint: c.argumentHint ?? '',
    type: c.type ?? 'local',
    execution: 'client',
    is_hidden: !!c.isHidden,
  }
}

let _registry = null
let _registryLoading = null

// Subscribers notified whenever the cached registry changes (prime
// completes, invalidate). Powers ``useTypeahead`` so the slash-command
// list updates the moment server-only commands become available — the
// previous ``useMemo(() => getCommands(), [])`` snapshotted the empty
// pre-prime list and never recovered.
const _listeners = new Set()

function notifyRegistryChange() {
  for (const l of _listeners) {
    try { l() } catch { /* don't let one bad listener break the rest */ }
  }
}

export function subscribeRegistry(listener) {
  _listeners.add(listener)
  return () => _listeners.delete(listener)
}

/**
 * Fetch and cache the backend registry. Subsequent calls are no-ops until
 * invalidateRegistry() is called.
 *
 * @param {() => Promise<string>} getToken
 */
export async function primeRegistry(getToken) {
  if (_registry) return _registry
  if (_registryLoading) return _registryLoading
  const { listCommands } = await import('../api.js')
  _registryLoading = (async () => {
    try {
      const token = getToken ? await getToken() : null
      _registry = await listCommands(token)
    } catch (err) {
      console.warn('[commands] failed to fetch backend registry:', err)
      _registry = null
    } finally {
      _registryLoading = null
    }
    notifyRegistryChange()
    return _registry
  })()
  return _registryLoading
}

export function invalidateRegistry() {
  _registry = null
  _registryLoading = null
  notifyRegistryChange()
}

export function getCachedRegistry() {
  return _registry
}

export function getCommandName(cmd) {
  return cmd.userFacingName?.() ?? cmd.name
}

export function isCommandEnabled(cmd) {
  return cmd.isEnabled?.() ?? true
}

/**
 * List every command for the typeahead / discovery surface.
 *
 * Merges the small client-handler set with the backend registry. Backend
 * entries win on name conflict so server-side metadata stays authoritative.
 * Before the registry finishes fetching, returns the client list alone —
 * server-only commands surface a moment later.
 */
export function getCommands() {
  const clientList = CLIENT_HANDLERS
    .filter(isCommandEnabled)
    .filter((c) => !c.isHidden)
    .map(clientToRegistryEntry)

  if (!_registry) return clientList

  const byName = new Map()
  for (const c of clientList) byName.set(c.name, c)
  for (const c of _registry) {
    if (c.is_hidden) continue
    byName.set(c.name, {
      ...c,
      argumentHint: c.argument_hint || c.argumentHint || '',
    })
  }
  return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name))
}

/**
 * Find a command by name or alias. Backend registry wins on conflict;
 * client handlers cover the remaining client-execution set.
 */
export function findCommand(commandName) {
  const name = commandName.toLowerCase()
  if (_registry) {
    const hit = _registry.find(
      (c) =>
        c.name === name ||
        (c.aliases || []).some((a) => a.toLowerCase() === name),
    )
    if (hit) return hit
  }
  const ch = clientByName(name)
  return ch ? clientToRegistryEntry(ch) : undefined
}

/** Lookup a client handler by command name. Returns null for server-only commands. */
export function findClientHandler(commandName) {
  return clientByName(commandName) || null
}

export function hasCommand(commandName) {
  return findCommand(commandName) !== undefined && findCommand(commandName) !== null
}

export function getCommand(commandName) {
  const command = findCommand(commandName)
  if (!command) {
    throw new ReferenceError(
      `Command ${commandName} not found.`,
    )
  }
  return command
}

export function formatDescriptionWithSource(cmd) {
  return cmd.description
}

export function isSlashCommand(input) {
  return typeof input === 'string' && input.trim().startsWith('/')
}

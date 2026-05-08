/**
 * Tasks command - minimal metadata only.
 * Implementation is lazy-loaded from tasks.js to reduce startup time.
 *
 * Currently hidden from the typeahead and /help: the populator that
 * fills `context.tasks` from streamed tool-progress events isn't wired
 * up yet. Flip `isHidden` back to false once the data source is live.
 */

const tasks = {
  type: 'local',
  name: 'tasks',
  description: 'Show active tasks',
  isHidden: true,
  load: () => import('./tasks.js'),
}

export default tasks

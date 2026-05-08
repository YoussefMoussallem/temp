export const call = async (_args, context) => {
  const tasks = context.tasks || {}
  const entries = Object.values(tasks)

  if (entries.length === 0) {
    return { type: 'text', value: 'No tasks.' }
  }

  const statusIcons = {
    pending: '[.]',
    running: '[>]',
    completed: '[x]',
    failed: '[!]',
    killed: '[-]',
  }

  const active = entries.filter((t) => t.status === 'running' || t.status === 'pending')
  const lines = ['## Tasks', '']

  for (const task of entries) {
    const icon = statusIcons[task.status] || '[?]'
    lines.push(`- ${icon} **${task.id}**: ${task.description || ''} (${task.status})`)
  }

  lines.push(`\n*${active.length} active, ${entries.length} total*`)
  return { type: 'text', value: lines.join('\n') }
}

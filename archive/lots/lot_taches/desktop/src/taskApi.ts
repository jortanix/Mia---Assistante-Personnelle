export type Task = {
  id: number
  title: string
  description: string
  status: 'todo' | 'done'
  created_at: string
  updated_at: string
}

export type TaskProposal = {
  id: number
  assistant_message_id: number
  action: 'create_task'
  data: { title: string; description: string }
  status: 'pending' | 'confirmed' | 'cancelled'
  task: Task | null
}

export function isTask(value: unknown): value is Task {
  if (!value || typeof value !== 'object') return false
  const t = value as Record<string, unknown>
  return typeof t.id === 'number' && Number.isInteger(t.id) &&
    typeof t.title === 'string' && typeof t.description === 'string' &&
    (t.status === 'todo' || t.status === 'done') &&
    typeof t.created_at === 'string' && typeof t.updated_at === 'string'
}

export function isTaskProposal(value: unknown): value is TaskProposal {
  if (!value || typeof value !== 'object') return false
  const p = value as Record<string, unknown>
  const data = p.data
  return typeof p.id === 'number' && Number.isInteger(p.id) &&
    typeof p.assistant_message_id === 'number' && p.action === 'create_task' &&
    (p.status === 'pending' || p.status === 'confirmed' || p.status === 'cancelled') &&
    !!data && typeof data === 'object' &&
    typeof (data as Record<string, unknown>).title === 'string' &&
    typeof (data as Record<string, unknown>).description === 'string' &&
    (p.task === null || isTask(p.task))
}

export function notifyTasks(detail?: { task?: Task; deletedId?: number }) {
  window.dispatchEvent(new CustomEvent('mia:tasks-updated', { detail }))
}

export function taskApiError(value: unknown): string {
  if (value && typeof value === 'object') {
    const data = value as Record<string, unknown>
    if (typeof data.error === 'string') return data.error
    if (typeof data.detail === 'string') return data.detail
    for (const key of ['title', 'description', 'status']) {
      const messages = data[key]
      if (Array.isArray(messages) && typeof messages[0] === 'string') {
        return `${key} : ${messages[0]}`
      }
    }
  }
  return 'Impossible de traiter la demande. Réessaie.'
}

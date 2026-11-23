import { describe, expect, it, vi } from 'vitest'
import { isTask, isTaskProposal, notifyTasks, taskApiError } from './taskApi'
import type { Task, TaskProposal } from './taskApi'

const fullTask: Task = {
  id: 1,
  title: 'Ranger mon bureau',
  description: '',
  status: 'todo',
  created_at: '2026-11-17T10:00:00Z',
  updated_at: '2026-11-17T10:00:00Z',
}

const fullProposal: TaskProposal = {
  id: 9,
  assistant_message_id: 42,
  action: 'create_task',
  data: { title: 'Ranger mon bureau', description: '' },
  status: 'pending',
  task: null,
}

describe('isTask', () => {
  it('accepts a valid task', () => {
    expect(isTask(fullTask)).toBe(true)
  })

  it('rejects a task without description', () => {
    const { description: _description, ...withoutDescription } = fullTask
    expect(isTask(withoutDescription)).toBe(false)
  })

  it('rejects non-object and invalid statuses', () => {
    expect(isTask(null)).toBe(false)
    expect(isTask('texte')).toBe(false)
    expect(isTask({ ...fullTask, status: 'archived' })).toBe(false)
    expect(isTask({ ...fullTask, id: '1' })).toBe(false)
  })

  it('rejects a task missing updated_at', () => {
    const { updated_at: _updated_at, ...withoutUpdatedAt } = fullTask
    expect(isTask(withoutUpdatedAt)).toBe(false)
  })
})

describe('isTaskProposal', () => {
  it('accepts a valid pending proposal', () => {
    expect(isTaskProposal(fullProposal)).toBe(true)
  })

  it('accepts a proposal with a resolved task', () => {
    expect(isTaskProposal({ ...fullProposal, status: 'confirmed', task: fullTask })).toBe(true)
  })

  it('rejects a proposal without assistant_message_id', () => {
    const { assistant_message_id: _id, ...withoutAssistantId } = fullProposal
    expect(isTaskProposal(withoutAssistantId)).toBe(false)
  })

  it('rejects a proposal with an invalid task', () => {
    expect(isTaskProposal({ ...fullProposal, task: { id: 1 } })).toBe(false)
  })

  it('rejects wrong action and bad data shape', () => {
    expect(isTaskProposal({ ...fullProposal, action: 'save_memory' })).toBe(false)
    expect(isTaskProposal({ ...fullProposal, data: { content: 'x' } })).toBe(false)
  })
})

describe('taskApiError', () => {
  it('reads the error field', () => {
    expect(taskApiError({ error: 'Conflit de version.' })).toBe('Conflit de version.')
  })

  it('reads the detail field as fallback', () => {
    expect(taskApiError({ detail: 'Introuvable.' })).toBe('Introuvable.')
  })

  it('reads field validation messages', () => {
    expect(taskApiError({ title: ['Le titre est trop long.'] })).toBe('title : Le titre est trop long.')
  })

  it('returns a fallback message', () => {
    expect(taskApiError({ nous: 'toujours' })).toBe('Impossible de traiter la demande. Réessaie.')
    expect(taskApiError(null)).toBe('Impossible de traiter la demande. Réessaie.')
  })
})

describe('notifyTasks', () => {
  it('dispatches a mia:tasks-updated event with the detail', () => {
    const listener = vi.fn((event: Event) => {
      const detail = (event as CustomEvent<{ task: Task }>).detail
      expect(detail.task.id).toBe(fullTask.id)
    })
    window.addEventListener('mia:tasks-updated', listener)
    try {
      notifyTasks({ task: fullTask })
      expect(listener).toHaveBeenCalledTimes(1)
    } finally {
      window.removeEventListener('mia:tasks-updated', listener)
    }
  })

  it('dispatches without payload', () => {
    const listener = vi.fn()
    window.addEventListener('mia:tasks-updated', listener)
    try {
      notifyTasks()
      expect(listener).toHaveBeenCalledTimes(1)
    } finally {
      window.removeEventListener('mia:tasks-updated', listener)
    }
  })
})

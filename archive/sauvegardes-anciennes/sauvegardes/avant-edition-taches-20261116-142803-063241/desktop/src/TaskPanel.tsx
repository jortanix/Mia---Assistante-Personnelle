import { useEffect, useRef, useState } from 'react'
import { isTask, notifyTasks, taskApiError } from './taskApi'
import type { Task } from './taskApi'

export function TaskPanel({ disabled }: { disabled: boolean }) {
  const [open, setOpen] = useState(false)
  const [tasks, setTasks] = useState<Task[]>([])
  const [filter, setFilter] = useState<'todo' | 'done' | 'all'>('todo')
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const requestId = useRef(0)
  const lock = useRef(false)

  async function refresh() {
    const id = ++requestId.current
    setLoading(true)
    setError(null)
    try {
      const response = await fetch('/api/tasks/')
      const data: unknown = await response.json()
      if (!response.ok || !Array.isArray(data) || !data.every(isTask)) {
        throw new Error('Impossible de charger les tâches.')
      }
      if (id === requestId.current) setTasks(data)
    } catch (caught) {
      if (id === requestId.current) setError(caught instanceof Error ? caught.message : 'Erreur de connexion.')
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    void refresh()
    const listener = () => { void refresh() }
    window.addEventListener('mia:tasks-updated', listener)
    return () => {
      ++requestId.current
      window.removeEventListener('mia:tasks-updated', listener)
    }
  }, [open])

  async function change(task: Task, action: 'toggle' | 'delete') {
    if (disabled || lock.current) return
    if (action === 'delete' && !window.confirm(`Supprimer définitivement cette tâche ?\n\n${task.title}\n\nLe texte restera dans la conversation.`)) return
    lock.current = true
    setBusyId(task.id)
    setError(null)
    try {
      const response = await fetch(`/api/tasks/${task.id}/`, action === 'delete'
        ? { method: 'DELETE' }
        : { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: task.status === 'todo' ? 'done' : 'todo' }) })
      if (action === 'delete' && (response.ok || response.status === 404)) {
        setTasks((current) => current.filter((item) => item.id !== task.id))
        notifyTasks({ deletedId: task.id })
      } else {
        const data: unknown = await response.json().catch(() => null)
        if (!response.ok) throw new Error(taskApiError(data))
        if (!isTask(data) || data.id !== task.id) throw new Error('Réponse du serveur inattendue.')
        setTasks((current) => current.map((item) => item.id === task.id ? data : item))
        notifyTasks({ task: data })
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Erreur de connexion.')
    } finally {
      lock.current = false
      setBusyId(null)
    }
  }

  const visible = tasks.filter((task) => filter === 'all' || task.status === filter)
  return <section className="task-panel" aria-label="Gestion des tâches">
    <button type="button" className="secondary-button" aria-expanded={open}
      onClick={() => setOpen((current) => !current)}>
      {open ? 'Fermer les tâches' : 'Mes tâches'}
    </button>
    {open && <div className="task-panel-body">
      <p>Pour ajouter : « Ajoute une tâche : ranger mon bureau. » Puis confirme dans le chat.</p>
      <label>Afficher :{' '}
        <select value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)}>
          <option value="todo">À faire</option>
          <option value="done">Terminées</option>
          <option value="all">Toutes</option>
        </select>
      </label>
      {' '}<button type="button" className="secondary-button" disabled={loading || busyId !== null}
        onClick={() => { void refresh() }}>Actualiser</button>
      {loading && <p role="status">Chargement…</p>}
      {!loading && !error && visible.length === 0 && <p>Aucune tâche dans cette vue.</p>}
      <ul className="task-list">
        {visible.map((task) => <li key={task.id}>
          <p className={task.status === 'done' ? 'task-done' : ''}>{task.title}</p>
          {task.description && <p>{task.description}</p>}
          <div className="task-actions">
            <button type="button" disabled={disabled || loading || busyId !== null}
              onClick={() => { void change(task, 'toggle') }}>
              {busyId === task.id ? 'Traitement…' : task.status === 'todo' ? 'Marquer comme faite' : 'Remettre à faire'}
            </button>
            <button type="button" className="secondary-button" disabled={disabled || loading || busyId !== null}
              onClick={() => { void change(task, 'delete') }}>Supprimer</button>
          </div>
        </li>)}
      </ul>
      {error && <p className="error" role="alert">{error}</p>}
    </div>}
  </section>
}

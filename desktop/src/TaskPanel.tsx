import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { isTask, notifyTasks, taskApiError } from './taskApi'
import type { Task } from './taskApi'

type EditDraft = { task: Task; title: string; description: string }

export function TaskPanel({ disabled }: { disabled: boolean }) {
  const [open, setOpen] = useState(false)
  const [tasks, setTasks] = useState<Task[]>([])
  const [filter, setFilter] = useState<'todo' | 'done' | 'all'>('todo')
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [edit, setEdit] = useState<EditDraft | null>(null)
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

  function togglePanel() {
    if (lock.current) return
    if (open && edit && !window.confirm('Abandonner les modifications non enregistrées ?')) return
    setEdit(null)
    setError(null)
    setOpen((current) => !current)
  }

  function beginEdit(task: Task) {
    if (disabled || lock.current || edit) return
    setError(null)
    setEdit({ task, title: task.title, description: task.description })
  }

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!edit || disabled || lock.current) return
    const title = edit.title.trim()
    if (!title) { setError('Le titre ne peut pas être vide.'); return }
    if (title.length > 200 || edit.description.length > 2000) {
      setError('Titre : 200 caractères maximum. Description : 2 000 maximum.')
      return
    }
    lock.current = true
    setBusyId(edit.task.id)
    setError(null)
    try {
      const response = await fetch(`/api/tasks/${edit.task.id}/`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, description: edit.description,
          expected_updated_at: edit.task.updated_at }),
      })
      const data: unknown = await response.json().catch(() => null)
      if (!response.ok) throw new Error(taskApiError(data))
      if (!isTask(data) || data.id !== edit.task.id) throw new Error('Réponse du serveur inattendue.')
      setTasks((current) => current.map((task) => task.id === data.id ? data : task))
      setEdit(null)
      notifyTasks({ task: data })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Erreur de connexion.')
    } finally {
      lock.current = false
      setBusyId(null)
    }
  }

  async function change(task: Task, action: 'toggle' | 'delete') {
    if (disabled || lock.current || edit) return
    if (action === 'delete' && !window.confirm(`Supprimer définitivement cette tâche ?\n\n${task.title}\n\nLe texte restera dans la conversation.`)) return
    lock.current = true
    setBusyId(task.id)
    setError(null)
    try {
      const response = await fetch(`/api/tasks/${task.id}/`, {
        method: action === 'delete' ? 'DELETE' : 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_updated_at: task.updated_at,
          ...(action === 'toggle' ? { status: task.status === 'todo' ? 'done' : 'todo' } : {}) }),
      })
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
      disabled={busyId !== null} onClick={togglePanel}>
      {open ? 'Fermer les tâches' : 'Mes tâches'}
    </button>
    {open && <div className="task-panel-body">
      <p>Pour ajouter : « Ajoute une tâche : ranger mon bureau. » Puis confirme dans le chat.</p>
      <label>Afficher :{' '}
        <select value={filter} disabled={edit !== null || busyId !== null}
          onChange={(event) => setFilter(event.target.value as typeof filter)}>
          <option value="todo">À faire</option><option value="done">Terminées</option><option value="all">Toutes</option>
        </select>
      </label>
      {' '}<button type="button" className="secondary-button" disabled={loading || busyId !== null || edit !== null}
        onClick={() => { void refresh() }}>Actualiser</button>
      {loading && <p role="status">Chargement…</p>}
      {!loading && !error && visible.length === 0 && <p>Aucune tâche dans cette vue.</p>}
      <ul className="task-list">
        {visible.map((task) => <li key={task.id}>
          {edit?.task.id === task.id ? <form onSubmit={(event) => { void saveEdit(event) }}
            style={{ display: 'grid', gap: 8 }}>
            <label>Titre
              <input aria-label="Titre de la tâche" value={edit.title} maxLength={200}
                disabled={disabled || busyId !== null} autoFocus required
                style={{ display: 'block', width: '100%', boxSizing: 'border-box' }}
                onChange={(event) => {
                  const title = event.target.value
                  setEdit((current) => current ? { ...current, title } : null)
                }} />
            </label>
            <label>Description
              <textarea aria-label="Description de la tâche" value={edit.description} maxLength={2000}
                disabled={disabled || busyId !== null} rows={3}
                style={{ display: 'block', width: '100%', boxSizing: 'border-box' }}
                onChange={(event) => {
                  const description = event.target.value
                  setEdit((current) => current ? { ...current, description } : null)
                }} />
            </label>
            <div className="task-actions">
              <button type="submit" disabled={disabled || busyId !== null || !edit.title.trim()}>
                {busyId === task.id ? 'Enregistrement…' : 'Enregistrer'}
              </button>
              <button type="button" className="secondary-button" disabled={busyId !== null}
                onClick={() => { setEdit(null); setError(null) }}>Annuler</button>
            </div>
          </form> : <>
            <p className={task.status === 'done' ? 'task-done' : ''}>{task.title}</p>
            {task.description && <p>{task.description}</p>}
            <div className="task-actions">
              <button type="button" className="secondary-button"
                disabled={disabled || loading || busyId !== null || edit !== null}
                onClick={() => beginEdit(task)}>Modifier</button>
              <button type="button" disabled={disabled || loading || busyId !== null || edit !== null}
                onClick={() => { void change(task, 'toggle') }}>
                {busyId === task.id ? 'Traitement…' : task.status === 'todo' ? 'Marquer comme faite' : 'Remettre à faire'}
              </button>
              <button type="button" className="secondary-button" disabled={disabled || loading || busyId !== null || edit !== null}
                onClick={() => { void change(task, 'delete') }}>Supprimer</button>
            </div>
          </>}
        </li>)}
      </ul>
      {error && <p className="error" role="alert">{error}</p>}
    </div>}
  </section>
}

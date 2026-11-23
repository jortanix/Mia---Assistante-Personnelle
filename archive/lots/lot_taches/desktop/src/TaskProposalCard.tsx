import { useEffect, useRef, useState } from 'react'
import { isTaskProposal, notifyTasks, taskApiError } from './taskApi'
import type { Task, TaskProposal } from './taskApi'

export function TaskProposalCard({ proposal, disabled }: {
  proposal: TaskProposal; disabled: boolean
}) {
  const [status, setStatus] = useState(proposal.status)
  const [task, setTask] = useState<Task | null>(proposal.task)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const lock = useRef(false)

  useEffect(() => {
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<{ task?: Task; deletedId?: number }>).detail
      if (!detail || !task) return
      if (detail.deletedId === task.id) setTask(null)
      else if (detail.task?.id === task.id) setTask(detail.task)
    }
    window.addEventListener('mia:tasks-updated', listener)
    return () => window.removeEventListener('mia:tasks-updated', listener)
  }, [task])

  async function resolve(action: 'confirm' | 'cancel') {
    if (disabled || lock.current || status !== 'pending') return
    lock.current = true
    setBusy(true)
    setError(null)
    try {
      const response = await fetch(`/api/action-proposals/${proposal.id}/${action}/`, { method: 'POST' })
      const data: unknown = await response.json().catch(() => null)
      if (!response.ok) throw new Error(taskApiError(data))
      if (!isTaskProposal(data) || data.id !== proposal.id ||
          data.data.title !== proposal.data.title || data.data.description !== proposal.data.description ||
          data.status !== (action === 'confirm' ? 'confirmed' : 'cancelled')) {
        throw new Error('Réponse inattendue. Rouvre la conversation avant de réessayer.')
      }
      setStatus(data.status)
      setTask(data.task)
      notifyTasks(data.task ? { task: data.task } : undefined)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Erreur de connexion.')
    } finally {
      lock.current = false
      setBusy(false)
    }
  }

  return <section className="task-proposal" aria-label="Proposition de tâche">
    <p>Tâche proposée :</p>
    <p>{proposal.data.title}</p>
    {proposal.data.description && <p>{proposal.data.description}</p>}
    {status === 'pending' ? <>
      <p>Rien n’est encore ajouté à tes tâches.</p>
      <div className="task-actions">
        <button type="button" disabled={disabled || busy}
          onClick={() => { void resolve('confirm') }}>Ajouter</button>
        <button type="button" className="secondary-button" disabled={disabled || busy}
          onClick={() => { void resolve('cancel') }}>Annuler</button>
      </div>
    </> : <p role="status">{status === 'cancelled' ? 'Proposition annulée.'
      : !task ? 'Tâche supprimée.'
      : task.status === 'done' ? 'Tâche terminée.' : 'Tâche ajoutée à Mes tâches.'}</p>}
    {busy && <p role="status">Traitement…</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>
}

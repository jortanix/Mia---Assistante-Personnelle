import { useEffect, useRef, useState } from 'react'

type Memory = { id: number; content: string; confirmed_at: string }

function isMemory(value: unknown): value is Memory {
  if (!value || typeof value !== 'object') return false
  const m = value as Record<string, unknown>
  return typeof m.id === 'number' && typeof m.content === 'string' &&
    typeof m.confirmed_at === 'string'
}

export function MemoryPanel({ enabled, onEnabledChange, disabled }: {
  enabled: boolean
  onEnabledChange: (value: boolean) => void
  disabled: boolean
}) {
  const [open, setOpen] = useState(false)
  const [memories, setMemories] = useState<Memory[]>([])
  const [loading, setLoading] = useState(false)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const deleteLock = useRef(false)
  const requestId = useRef(0)

  async function refresh() {
    const id = ++requestId.current
    setLoading(true)
    setError(null)
    try {
      const response = await fetch('/api/memories/')
      const data: unknown = await response.json()
      if (!response.ok || !Array.isArray(data) || !data.every(isMemory)) {
        throw new Error('Impossible de charger les préférences.')
      }
      if (id === requestId.current) setMemories(data)
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
    window.addEventListener('mia:memory-updated', listener)
    return () => {
      ++requestId.current
      window.removeEventListener('mia:memory-updated', listener)
    }
  }, [open])

  async function remove(memory: Memory) {
    if (deleteLock.current || disabled) return
    if (!window.confirm(`Supprimer cette préférence de la mémoire de Mia ?\n\n${memory.content}\n\nLe texte restera dans les anciennes conversations.`)) return
    deleteLock.current = true
    setDeleting(memory.id)
    setError(null)
    try {
      const response = await fetch(`/api/memories/${memory.id}/`, { method: 'DELETE' })
      if (!response.ok && response.status !== 404) throw new Error('Suppression impossible. Réessaie.')
      setMemories((current) => current.filter((item) => item.id !== memory.id))
      window.dispatchEvent(new CustomEvent('mia:memory-updated', {
        detail: { deletedId: memory.id },
      }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Erreur de connexion.')
    } finally {
      deleteLock.current = false
      setDeleting(null)
    }
  }

  return (
    <section aria-label="Mémoire personnelle" style={{ padding: '8px 16px', maxHeight: '45vh', overflowY: 'auto' }}>
      <button type="button" className="secondary-button" aria-expanded={open}
        onClick={() => setOpen((value) => !value)}>
        {open ? 'Fermer la mémoire' : 'Mémoire personnelle'}
      </button>
      {open && <div>
        <label>
          <input type="checkbox" checked={enabled} disabled={disabled || deleting !== null}
            onChange={(event) => onEnabledChange(event.target.checked)} />
          {' '}Utiliser mes préférences pour les prochains messages
        </label>
        <p><small>Option désactivée après actualisation. Jusqu’aux 10 préférences les plus récentes sont utilisées.
          Les messages de la conversation restent transmis même si cette option est désactivée.</small></p>
        <button type="button" className="secondary-button" disabled={loading || deleting !== null}
          onClick={() => { void refresh() }}>Actualiser la liste</button>
        {loading && <p role="status">Chargement…</p>}
        {!loading && !error && memories.length === 0 && <p>Aucune préférence enregistrée.</p>}
        {memories.map((memory) => <div key={memory.id} style={{ borderBottom: '1px solid currentColor', padding: 8 }}>
          <p style={{ whiteSpace: 'pre-wrap' }}>{memory.content}</p>
          <button type="button" className="secondary-button"
            disabled={disabled || deleting !== null || loading}
            onClick={() => { void remove(memory) }}>
            {deleting === memory.id ? 'Suppression…' : 'Supprimer'}
          </button>
        </div>)}
        <p><small>Supprimer retire la préférence de cette mémoire, pas des anciennes conversations.
          Une réponse déjà commencée n’est pas modifiée. Pour repartir sans cet ancien contexte, ouvre une nouvelle conversation.</small></p>
        {error && <p role="alert" className="error">{error}</p>}
      </div>}
    </section>
  )
}

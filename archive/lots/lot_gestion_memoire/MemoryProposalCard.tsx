import { useEffect, useRef, useState } from 'react'

export type MemoryProposal = {
  id: number
  assistant_message_id: number
  action: 'save_memory'
  data: { content: string }
  status: 'pending' | 'confirmed' | 'cancelled'
  memory?: { id: number } | null
}

export function isMemoryProposal(value: unknown): value is MemoryProposal {
  if (!value || typeof value !== 'object') return false
  const p = value as Record<string, unknown>
  const data = p.data
  const memoryValid = p.memory == null || (
    typeof p.memory === 'object' &&
    typeof (p.memory as Record<string, unknown>).id === 'number'
  )
  return typeof p.id === 'number' && Number.isInteger(p.id) &&
    typeof p.assistant_message_id === 'number' && p.action === 'save_memory' &&
    (p.status === 'pending' || p.status === 'confirmed' || p.status === 'cancelled') &&
    !!data && typeof data === 'object' &&
    typeof (data as Record<string, unknown>).content === 'string' && memoryValid
}

export function MemoryProposalCard({ proposal, disabled = false }: {
  proposal: MemoryProposal; disabled?: boolean
}) {
  const [status, setStatus] = useState(proposal.status)
  const [memoryId, setMemoryId] = useState(proposal.memory?.id ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const lock = useRef(false)

  useEffect(() => {
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<{ deletedId?: number }>).detail
      if (detail?.deletedId === memoryId) setMemoryId(null)
    }
    window.addEventListener('mia:memory-updated', listener)
    return () => window.removeEventListener('mia:memory-updated', listener)
  }, [memoryId])

  async function resolve(action: 'confirm' | 'cancel') {
    if (lock.current || disabled || status !== 'pending') return
    lock.current = true
    setBusy(true)
    setError(null)
    try {
      const response = await fetch(`/api/action-proposals/${proposal.id}/${action}/`, { method: 'POST' })
      const data: unknown = await response.json().catch(() => null)
      if (!response.ok) {
        const message = data && typeof data === 'object' &&
          typeof (data as Record<string, unknown>).error === 'string'
          ? (data as { error: string }).error : 'Impossible de traiter la proposition.'
        throw new Error(message)
      }
      if (!isMemoryProposal(data) || data.id !== proposal.id ||
          data.data.content !== proposal.data.content ||
          data.status !== (action === 'confirm' ? 'confirmed' : 'cancelled')) {
        throw new Error('Réponse inattendue. Rouvre la conversation avant de réessayer.')
      }
      setStatus(data.status)
      setMemoryId(data.memory?.id ?? null)
      window.dispatchEvent(new CustomEvent('mia:memory-updated'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Erreur de connexion.')
    } finally {
      lock.current = false
      setBusy(false)
    }
  }

  return <section aria-label="Proposition de mémoire" style={{
    border: '1px solid currentColor', borderRadius: 8, padding: 12, marginTop: 12,
  }}>
    <p>Préférence proposée :</p>
    <blockquote style={{ whiteSpace: 'pre-wrap' }}>{proposal.data.content}</blockquote>
    {status === 'pending' ? <>
      <p>Rien n’est encore ajouté à ta mémoire personnelle.</p>
      <div className="message-voice-controls">
        <button type="button" disabled={disabled || busy}
          onClick={() => { void resolve('confirm') }}>Retenir</button>
        <button type="button" className="secondary-button" disabled={disabled || busy}
          onClick={() => { void resolve('cancel') }}>Pas maintenant</button>
      </div>
      {busy && <p role="status">Traitement…</p>}
    </> : <p role="status">{status === 'cancelled'
      ? 'Proposition annulée : aucune préférence créée.'
      : memoryId === null ? 'Préférence supprimée de la mémoire.'
      : 'Préférence enregistrée. Son utilisation se règle dans Mémoire personnelle.'}</p>}
    <p><small>Le texte reste dans cet historique même après refus ou suppression.</small></p>
    {error && <p className="error" role="alert">{error}</p>}
  </section>
}

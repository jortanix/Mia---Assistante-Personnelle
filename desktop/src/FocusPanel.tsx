import { useEffect, useRef, useState } from 'react'
import { createFocus, FOCUS_MINUTES, formatFocusTime, getRemaining, pauseFocus,
  resetFocus, restoreFocus, sessionFromServer, settleFocus, startFocus,
  undoWindowLeft } from './focusTimer.mjs'
import type { FocusSession, ServerFocusSession as ServerClock } from './focusTimer.mjs'
import { isTask, notifyTasks, taskApiError } from './taskApi'
import type { Task } from './taskApi'

const STORAGE_KEY = 'mia:focus-session:v1'
const LINK_KEY = 'mia:focus-task-link:v1'

type FocusLink = { sessionId: number; taskId: number | null }
type CompletionState =
  | { status: 'done'; canUndo: boolean; task: Task | null; completedAt: string | null; cycle: number | null }
  | { status: 'already-done'; task: Task | null }
  | { status: 'no-task' }
  | { status: 'undone'; task: Task | null }
  | null

type ServerFocusSession = ServerClock & { id: number; task: Task | null }

function loadSession(): FocusSession {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw ? restoreFocus(raw) ?? createFocus() : createFocus()
  } catch { return createFocus() }
}

function loadLink(): FocusLink | null {
  try {
    const raw = window.localStorage.getItem(LINK_KEY)
    if (!raw) return null
    const value: unknown = JSON.parse(raw)
    if (typeof value !== 'object' || value === null) return null
    const link = value as Record<string, unknown>
    if (typeof link.sessionId !== 'number' || (link.taskId !== null && typeof link.taskId !== 'number')) return null
    return { sessionId: link.sessionId, taskId: link.taskId as number | null }
  } catch {
    window.localStorage.removeItem(LINK_KEY)
    return null
  }
}

export function FocusPanel() {
  const [open, setOpen] = useState(false)
  const [session, setSession] = useState<FocusSession>(loadSession)
  const [now, setNow] = useState(Date.now)
  const [storageError, setStorageError] = useState(false)
  const [link, setLink] = useState<FocusLink | null>(() => loadLink())
  const [linkLoaded, setLinkLoaded] = useState(false)
  const [linkError, setLinkError] = useState(false)
  const [linkedTask, setLinkedTask] = useState<Task | null>(null)
  const [linkDeleted, setLinkDeleted] = useState(false)
  const [tasks, setTasks] = useState<Task[]>([])
  const [tasksLoading, setTasksLoading] = useState(false)
  const [tasksError, setTasksError] = useState(false)
  const [apiBusy, setApiBusy] = useState(false)
  const [markBusy, setMarkBusy] = useState(false)
  const [undoBusy, setUndoBusy] = useState(false)
  const [completion, setCompletion] = useState<CompletionState>(null)
  const [feedback, setFeedback] = useState<{ kind: 'success' | 'info' | 'warn'; text: string } | null>(null)
  const completingRef = useRef(false)
  const completedRef = useRef<number | null>(null)
  const undoTimerRef = useRef<number | null>(null)
  const remaining = getRemaining(session, now)
  const canConfigure = session.phase === 'idle' || session.phase === 'finished'

  useEffect(() => {
    const update = () => setNow(Date.now())
    const timer = window.setInterval(update, 500)
    document.addEventListener('visibilitychange', update)
    window.addEventListener('focus', update)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', update)
      window.removeEventListener('focus', update)
    }
  }, [])

  useEffect(() => {
    setSession((current) => settleFocus(current, now))
  }, [now])

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
      setStorageError(false)
    } catch { setStorageError(true) }
  }, [session])

  useEffect(() => {
    const receive = (event: StorageEvent) => {
      if (event.storageArea !== window.localStorage || (event.key !== STORAGE_KEY && event.key !== null)) return
      const updated = event.newValue ? restoreFocus(event.newValue) : createFocus()
      if (updated) {
        setNow(Date.now())
        setSession(updated)
      }
    }
    window.addEventListener('storage', receive)
    return () => window.removeEventListener('storage', receive)
  }, [])

  useEffect(() => () => {
    if (undoTimerRef.current !== null) window.clearTimeout(undoTimerRef.current)
  }, [])

  // Restaure le lien session ↔ tâche enregistré côté MIA.
  useEffect(() => {
    let cancelled = false
    async function restore() {
      if (!link) {
        setLinkLoaded(true)
        return
      }
      try {
        const response = await fetch(`/api/focus-sessions/${link.sessionId}/`)
        if (response.status === 404) {
          window.localStorage.removeItem(LINK_KEY)
          if (!cancelled) { setLink(null); setLinkedTask(null); setLinkDeleted(false) }
          return
        }
        if (!response.ok) throw new Error()
        const data: unknown = await response.json()
        if (!data || typeof data !== 'object' || typeof (data as Record<string, unknown>).id !== 'number') {
          throw new Error()
        }
        const task: unknown = (data as Record<string, unknown>).task ?? null
        if (task !== null && !isTask(task)) throw new Error()
        const server = data as ServerFocusSession
        if (!cancelled) {
          // L'horloge de MIA est la référence : on reprend le décompte à partir
          // de l'état enregistré en base (rechargement en cours de session,
          // y compris après l'échéance, où la session tombe alors en "finished").
          setSession((current) => {
            const phase = (server.phase ?? 'idle')
            if (phase === 'running' || phase === 'paused' || phase === 'finished') {
              return settleFocus(sessionFromServer(server, Date.now()), Date.now())
            }
            return current
          })
          setLinkedTask(task as Task | null)
          // « tâche supprimée » uniquement si une tâche avait été liée : une
          // session sans tâche par choix (taskId null) n'affiche pas d'avertissement.
          setLinkDeleted(task === null && link.taskId !== null)
          setLinkError(false)
        }
      } catch {
        if (!cancelled) setLinkError(true)
      } finally {
        if (!cancelled) setLinkLoaded(true)
      }
    }
    void restore()
    return () => { cancelled = true }
  }, [link])

  // Chargement des tâches pour le choix (s'actualise aussi après un changement).
  useEffect(() => {
    if (!open || link) return
    void loadTasks()
    const listener = () => { void loadTasks() }
    window.addEventListener('mia:tasks-updated', listener)
    return () => window.removeEventListener('mia:tasks-updated', listener)
  }, [open, link])

  // Fin du minuteur : marquage automatique de la tâche liée.
  const prevPhaseRef = useRef(session.phase)
  useEffect(() => {
    const prev = prevPhaseRef.current
    prevPhaseRef.current = session.phase
    if (session.phase === 'finished' && prev !== 'finished') {
      void completeSession(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.phase])

  // Au rechargement d'une session déjà terminée, on relance le marquage.
  useEffect(() => {
    if (linkLoaded && session.phase === 'finished' && link && completedRef.current !== link.sessionId) {
      void completeSession(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkLoaded, link?.sessionId, session.phase])

  async function loadTasks() {
    setTasksLoading(true)
    setTasksError(false)
    try {
      const response = await fetch('/api/tasks/')
      const data: unknown = await response.json()
      if (!response.ok || !Array.isArray(data) || !data.every(isTask)) {
        throw new Error('Impossible de charger les tâches.')
      }
      setTasks(data)
    } catch {
      setTasksError(true)
    } finally {
      setTasksLoading(false)
    }
  }

  // Aligne une transition d'horloge du panneau avec la session MIA.
  async function syncPhase(sessionId: number, phase: 'running' | 'paused', remaining_time_ms?: number) {
    try {
      const response = await fetch(`/api/focus-sessions/${sessionId}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phase, ...(remaining_time_ms !== undefined ? { remaining_time_ms } : {}) }),
      })
      if (!response.ok) {
        const data: unknown = await response.json().catch(() => null)
        setFeedback({
          kind: 'warn',
          text: taskApiError(data) + ' La session enregistrée côté MIA n’a pas pu suivre le minuteur.',
        })
      }
    } catch {
      setFeedback({
        kind: 'warn',
        text: 'Impossible de synchroniser la session avec MIA. La tâche de la fin pourra être perdue si le serveur n’a pas suivi.',
      })
    }
  }

  // Persiste côté MIA une session sans tâche liée (comme les sessions liées) et
  // renvoie son identifiant, ou null si le serveur est injoignable.
  async function ensureServerSession(): Promise<number | null> {
    try {
      const response = await fetch('/api/focus-sessions/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          duration_minutes: session.durationMs / 60000,
          label: session.label,
        }),
      })
      const data: unknown = await response.json().catch(() => null)
      if (!response.ok) throw new Error(taskApiError(data))
      if (!data || typeof data !== 'object' || typeof (data as Record<string, unknown>).id !== 'number') {
        throw new Error('Réponse du serveur inattendue.')
      }
      const newLink: FocusLink = { sessionId: (data as { id: number }).id, taskId: null }
      try { window.localStorage.setItem(LINK_KEY, JSON.stringify(newLink)) } catch { /* lien perdu au rechargement */ }
      completedRef.current = null
      setLink(newLink)
      setLinkedTask(null)
      setLinkDeleted(false)
      setLinkLoaded(true)
      return newLink.sessionId
    } catch (caught) {
      setFeedback({
        kind: 'warn',
        text: (caught instanceof Error ? caught.message : 'Impossible d’enregistrer la session côté MIA.')
          + ' Le minuteur reste local pour cette session.',
      })
      return null
    }
  }

  function startOrPause() {
    const time = Date.now()
    setNow(time)
    if (session.phase === 'finished') {
      completedRef.current = null
      setCompletion(null)
      const next = startFocus(session, time)
      setSession(next)
      // Relance : on repart de la durée complète côté MIA.
      const sessionId = link?.sessionId ?? null
      if (sessionId) {
        void syncPhase(sessionId, 'running', next.remainingMs)
      } else {
        // Recommencer une session jamais persistée : on la persiste d'abord.
        void persistAndSync(next)
      }
      return
    }
    const isRunning = session.phase === 'running'
    const next = isRunning ? pauseFocus(session, time) : startFocus(session, time)
    setSession(next)
    const sessionId = link?.sessionId ?? null
    if (sessionId) {
      if (isRunning) {
        void syncPhase(sessionId, 'paused')
      } else {
        // Départ ou reprise (selon le cas, le serveur a gardé la durée restante,
        // mais on lui renvoie la valeur locale pour rester cohérent).
        void syncPhase(sessionId, 'running', next.phase === 'running' ? next.remainingMs : session.remainingMs)
      }
    } else if (session.phase === 'idle' && next.phase === 'running') {
      // Premier départ d'une session sans tâche liée : on l'enregistre côté MIA.
      void persistAndSync(next)
    }
  }

  async function persistAndSync(next: FocusSession) {
    const sessionId = await ensureServerSession()
    if (sessionId === null) return
    void syncPhase(sessionId, 'running', next.remainingMs)
  }

  const reset = () => {
    if ((session.phase === 'running' || session.phase === 'paused') &&
        !window.confirm('Réinitialiser cette session ? La durée repartira au début.')) return
    setNow(Date.now())
    setSession((current) => resetFocus(current))
    if (link && (session.phase === 'running' || session.phase === 'paused' || session.phase === 'finished')) {
      // Remise à zéro côté MIA aussi, sinon un rechargement relancerait
      // l'ancien décompte en base et re-marquerait la tâche à tort.
      // Efface aussi le résultat enregistré éventuel : après un réinitialisation,
      // plus rien à annuler ni à rejouer au rechargement.
      void fetch(`/api/focus-sessions/${link.sessionId}/reset/`, { method: 'POST' })
        .then(() => {
          completedRef.current = null
          setCompletion(null)
        })
        .catch(() => {
          setFeedback({ kind: 'warn', text: 'Le minuteur local est réinitialisé, mais la session enregistrée côté MIA n’a pas pu être remise à zéro.' })
        })
    }
  }

  const clear = () => {
    if ((session.label || session.phase !== 'idle') &&
        !window.confirm('Effacer cette session de concentration et son intitulé ? Les tâches ne seront pas modifiées.')) return
    setNow(Date.now())
    if (link) {
      window.localStorage.removeItem(LINK_KEY)
      void fetch(`/api/focus-sessions/${link.sessionId}/`, { method: 'DELETE' })
        .catch(() => {
          setFeedback({ kind: 'warn', text: 'La session enregistrée côté MIA n’a pas pu être supprimée. Le minuteur local est réinitialisé.' })
        })
      completedRef.current = null
      setLink(null)
      setLinkedTask(null)
      setLinkDeleted(false)
      setCompletion(null)
    }
    setSession(createFocus())
  }

  async function createSessionFromTask(task: Task) {
    setApiBusy(true)
    setFeedback(null)
    try {
      const response = await fetch('/api/focus-sessions/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          duration_minutes: session.durationMs / 60000,
          label: task.title,
          task: task.id,
        }),
      })
      const data: unknown = await response.json().catch(() => null)
      if (!response.ok) throw new Error(taskApiError(data))
      if (!data || typeof data !== 'object' || typeof (data as Record<string, unknown>).id !== 'number') {
        throw new Error('Réponse du serveur inattendue.')
      }
      const newLink: FocusLink = { sessionId: (data as { id: number }).id, taskId: task.id }
      try { window.localStorage.setItem(LINK_KEY, JSON.stringify(newLink)) } catch { /* lien perdu au rechargement */ }
      completedRef.current = null
      setLink(newLink)
      setLinkedTask(task)
      setLinkDeleted(false)
      setLinkLoaded(true)
      setSession((current) => createFocus(current.durationMs / 60000, task.title))
      setFeedback({ kind: 'success', text: `Session liée à la tâche « ${task.title} ». Elle sera marquée comme faite à la fin du minuteur.` })
    } catch (caught) {
      setFeedback({
        kind: 'warn',
        text: caught instanceof Error ? caught.message : 'Impossible de créer la session de concentration.',
      })
    } finally {
      setApiBusy(false)
    }
  }

  async function updateLinkedSession(updates: { duration_minutes?: number; label?: string }) {
    if (!link) return
    try {
      const response = await fetch(`/api/focus-sessions/${link.sessionId}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      })
      if (!response.ok) throw new Error()
    } catch {
      setFeedback({ kind: 'warn', text: 'La session enregistrée côté MIA n’a pas pu être mise à jour.' })
    }
  }

  async function completeSession(force: boolean) {
    if (!link || completingRef.current) return
    if (!force && completedRef.current === link.sessionId) return
    completingRef.current = true
    setMarkBusy(true)
    setFeedback(null)
    try {
      const response = await fetch(`/api/focus-sessions/${link.sessionId}/complete/`, { method: 'POST' })
      const data: unknown = await response.json().catch(() => null)
      if (!response.ok) throw new Error(taskApiError(data))
      if (!data || typeof data !== 'object') throw new Error('Réponse du serveur inattendue.')
      const body = data as Record<string, unknown>
      const reason = typeof body.reason === 'string' ? body.reason : 'completed'
      const task: unknown = body.task ?? null
      if (task !== null && !isTask(task)) throw new Error('Réponse du serveur inattendue.')
      const t = task as Task | null
      completedRef.current = link.sessionId
      setLinkedTask(t)
      setLinkDeleted(t === null)
      if (t) notifyTasks({ task: t })
      if (reason === 'completed') {
        // La fenêtre d'annulation part de l'instant du marquage côté MIA
        // (completed_at) : au rechargement, le délai n'est pas renouvelé pour
        // autant, il repart du même point de départ serveur.
        const completedAt = typeof body.completed_at === 'string' ? body.completed_at : null
        const cycle = typeof body.cycle === 'number' ? body.cycle : null
        const canUndo = completedAt ? undoWindowLeft(completedAt, Date.now()) > 0 : true
        setCompletion({ status: 'done', canUndo, task: t, completedAt, cycle })
        scheduleUndoExpiry(completedAt)
      } else if (reason === 'already_done') {
        setCompletion({ status: 'already-done', task: t })
      } else if (reason === 'undone') {
        // Rechargement après une annulation : la tâche reste à faire.
        setCompletion({ status: 'undone', task: t })
      } else {
        setCompletion({ status: 'no-task' })
      }
    } catch (caught) {
      setFeedback({
        kind: 'warn',
        text: (caught instanceof Error ? caught.message : 'Impossible de marquer la tâche comme faite.')
          + ' Tu peux réessayer ci-dessous.',
      })
    } finally {
      completingRef.current = false
      setMarkBusy(false)
    }
  }

  function scheduleUndoExpiry(completedAt: string | null) {
    if (undoTimerRef.current !== null) window.clearTimeout(undoTimerRef.current)
    const remaining = completedAt ? undoWindowLeft(completedAt, Date.now()) : 0
    if (remaining <= 0) {
      undoTimerRef.current = null
      setCompletion((current) => current && current.status === 'done'
        ? { status: 'done', canUndo: false, task: current.task, completedAt: current.completedAt, cycle: current.cycle }
        : current)
      return
    }
    undoTimerRef.current = window.setTimeout(() => {
      undoTimerRef.current = null
      setCompletion((current) => current && current.status === 'done'
        ? { status: 'done', canUndo: false, task: current.task, completedAt: current.completedAt, cycle: current.cycle }
        : current)
    }, remaining)
  }

  async function undoMark() {
    const target = completion && completion.status === 'done' && completion.canUndo ? completion.task : null
    if (!target || undoBusy || !link) return
    setUndoBusy(true)
    setFeedback(null)
    try {
      // Annulation durable côté MIA : seule une session qui a réellement marqué
      // la tâche (et sans modification concurrente) est annulable. Le cycle du
      // marquage accompagne la demande pour écarter toute demande rejouée d'un
      // parcours antérieur.
      const response = await fetch(`/api/focus-sessions/${link.sessionId}/undo/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cycle: completion && completion.status === 'done' ? completion.cycle : null }),
      })
      const data: unknown = await response.json().catch(() => null)
      if (!response.ok) throw new Error(taskApiError(data))
      if (!data || typeof data !== 'object') throw new Error('Réponse du serveur inattendue.')
      const body = data as Record<string, unknown>
      const task: unknown = body.task ?? null
      if (task !== null && !isTask(task)) throw new Error('Réponse du serveur inattendue.')
      const t = task as Task | null
      setLinkedTask(t)
      setLinkDeleted(t === null)
      if (t) notifyTasks({ task: t })
      setCompletion({ status: 'undone', task: t })
      setFeedback({ kind: 'success', text: 'Tâche remise à faire.' })
    } catch (caught) {
      setFeedback({
        kind: 'warn',
        text: caught instanceof Error ? caught.message : 'Impossible d’annuler le marquage de la tâche.',
      })
    } finally {
      setUndoBusy(false)
    }
  }

  const phaseLabel = session.phase === 'running' ? 'En cours'
    : session.phase === 'paused' ? 'En pause' : session.phase === 'finished' ? 'Terminée' : 'Prête'

  const manualMarkVisible = link && !linkDeleted && linkedTask?.status === 'todo' && completion === null

  return <section className="focus-panel" aria-label="Concentration">
    <button type="button" className="secondary-button" aria-expanded={open}
      onClick={() => setOpen((current) => !current)}>
      {open ? 'Fermer la concentration' : 'Concentration'}
      {session.phase === 'running' || session.phase === 'paused' ? ` · ${formatFocusTime(remaining)}` : ''}
      {session.phase === 'finished' ? ' · Terminée' : ''}
    </button>
    {open && <div className="focus-panel-body">
      <p>Une session, une chose à la fois. Tu peux faire une pause quand tu veux.</p>

      {!link && canConfigure && linkLoaded && (
        <div className="focus-task-selection">
          <h3>Lier la session à une tâche</h3>
          {tasksLoading ? (
            <p role="status">Chargement des tâches…</p>
          ) : tasksError ? (
            <p className="error" role="alert">Impossible de charger les tâches. Vérifie que MIA est lancée.</p>
          ) : tasks.length === 0 ? (
            <p>Aucune tâche. Ajoute-en une dans le chat, par exemple « Ajoute une tâche : ranger mon bureau. »</p>
          ) : (
            <>
              <ul className="focus-task-list">
                {tasks.map((task) => (
                  <li key={task.id}>
                    <span className={task.status === 'done' ? 'task-done' : ''}>{task.title}</span>
                    <button type="button" className="secondary-button"
                      disabled={apiBusy || task.status === 'done'}
                      onClick={() => { void createSessionFromTask(task) }}>
                      {apiBusy ? 'Création…' : task.status === 'done' ? 'Déjà faite' : 'Créer la session'}
                    </button>
                  </li>
                ))}
              </ul>
              <p className="focus-note">Une session liée sera enregistrée côté MIA et marquera la tâche comme faite à la fin du minuteur.</p>
            </>
          )}
        </div>
      )}

      {!linkLoaded && <p role="status">Restauration de la session…</p>}
      {linkError && link && (
        <div className="focus-feedback focus-feedback--warn" role="alert">
          <p>Impossible de retrouver la session enregistrée côté MIA (serveur indisponible ?). La session reste affichée.</p>
        </div>
      )}

      {link && linkLoaded && linkDeleted ? (
        <div className="focus-feedback focus-feedback--warn" role="status">
          <p>La tâche liée à cette session a été supprimée. Rien ne sera marqué comme fait.</p>
        </div>
      ) : link && linkLoaded && link.taskId === null ? (
        <div className="focus-linked-task">
          <p className="focus-note">Aucune tâche liée : rien ne sera marqué comme fait à la fin de la session.</p>
        </div>
      ) : link && linkLoaded && linkedTask ? (
        <div className="focus-linked-task">
          <p className={linkedTask.status === 'done' ? 'task-done' : ''}>
            <strong>Tâche liée :</strong> {linkedTask.title}
          </p>
          <p className="focus-note">{linkedTask.status === 'done'
            ? 'Cette tâche est déjà marquée comme faite.'
            : 'Cette tâche sera marquée comme faite à la fin de la session.'}</p>
        </div>
      ) : null}

      <label>Sur quoi veux-tu avancer ?{link && link.taskId !== null ? ' (suivi de la tâche liée)'
        : link ? ' (session sans tâche liée)' : ' (facultatif)'}
        <input value={session.label} maxLength={200}
          disabled={!canConfigure || (link !== null && link.taskId !== null)}
          placeholder="Ex. : ouvrir mon document"
          onChange={(event) => {
            const label = event.target.value
            setSession((current) => createFocus(current.durationMs / 60000, label))
            // L'intitulé d'une session sans tâche est modifiable et persisté côté MIA.
            if (link && link.taskId === null) void updateLinkedSession({ label })
          }} />
      </label>
      <label>Durée
        <select value={session.durationMs / 60000} disabled={!canConfigure}
          onChange={(event) => {
            const minutes = Number(event.target.value)
            setSession((current) => createFocus(minutes, current.label))
            if (link) void updateLinkedSession({ duration_minutes: minutes })
          }}>
          {FOCUS_MINUTES.map((minutes) => <option value={minutes} key={minutes}>{minutes} minutes</option>)}
        </select>
      </label>
      <p className="focus-clock" role="timer" aria-live="off">{formatFocusTime(remaining)}</p>
      <p>{phaseLabel}</p>
      <div className="task-actions">
        <button type="button" onClick={startOrPause}>
          {session.phase === 'running' ? 'Pause' : session.phase === 'paused' ? 'Reprendre'
            : session.phase === 'finished' ? 'Recommencer' : 'Démarrer'}
        </button>
        <button type="button" className="secondary-button" onClick={reset}>Réinitialiser</button>
        <button type="button" className="secondary-button" onClick={() => { void clear() }}>Effacer la session</button>
      </div>

      {markBusy && <p className="focus-note" role="status">Marquage de la tâche en cours…</p>}

      {session.phase === 'finished' && !link && (
        <p className="focus-note" role="status">Session terminée. Aucune tâche n’était liée : rien n’a été marqué comme fait.</p>
      )}

      {session.phase === 'finished' && link && linkDeleted && !completion && (
        <p className="error" role="status">La tâche liée n’existe plus : rien n’a été marqué.</p>
      )}

      {session.phase === 'finished' && completion?.status === 'done' && (
        <div className="focus-feedback focus-feedback--success" role="status">
          <p>La tâche « {completion.task?.title ?? ''} » a été marquée comme faite.</p>
          {completion.canUndo && !undoBusy && (
            <button type="button" className="secondary-button" onClick={() => { void undoMark() }}>
              Annuler la marque
            </button>
          )}
          {undoBusy && <p className="focus-note" role="status">Annulation…</p>}
        </div>
      )}

      {session.phase === 'finished' && completion?.status === 'already-done' && (
        <p className="success" role="status">
          La tâche « {completion.task?.title ?? ''} » était déjà marquée comme faite.
        </p>
      )}

      {session.phase === 'finished' && completion?.status === 'no-task' && (
        <p role="status">Aucune tâche n’était liée à cette session : rien n’a été marqué comme fait.</p>
      )}

      {session.phase === 'finished' && completion?.status === 'undone' && (
        <p className="success" role="status">La tâche a été remise à faire. La session, elle, est terminée.</p>
      )}

      {manualMarkVisible && (
        <div className="task-actions">
          <button type="button" className="secondary-button" disabled={markBusy}
            onClick={() => { void completeSession(true) }}>
            Marquer la tâche comme faite
          </button>
          {markBusy && <span className="focus-note" role="status">Marquage en cours…</span>}
        </div>
      )}

      {feedback && (
        <div className={`focus-feedback focus-feedback--${feedback.kind}`} role="status">
          <p>{feedback.text}</p>
          <button type="button" className="secondary-button" onClick={() => setFeedback(null)}>Fermer</button>
        </div>
      )}

      {storageError && <p role="alert">Le minuteur fonctionne, mais le navigateur ne permet pas sa sauvegarde. Il ne sera pas récupéré après fermeture.</p>}
      <p className="focus-note">Le minuteur est enregistré dans ce navigateur, sans son ni notification.
        {link ? ' La session et le lien avec la tâche sont enregistrés côté MIA.' : ' Aucune session n’est enregistrée côté MIA pour l’instant.'}</p>
    </div>}
  </section>
}

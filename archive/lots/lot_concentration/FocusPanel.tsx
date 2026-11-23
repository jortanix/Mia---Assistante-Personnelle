import { useEffect, useState } from 'react'
import { createFocus, FOCUS_MINUTES, formatFocusTime, getRemaining, pauseFocus,
  resetFocus, restoreFocus, settleFocus, startFocus } from './focusTimer.mjs'
import type { FocusSession } from './focusTimer.mjs'

const STORAGE_KEY = 'mia:focus-session:v1'

function loadSession(): FocusSession {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw ? restoreFocus(raw) ?? createFocus() : createFocus()
  } catch { return createFocus() }
}

export function FocusPanel() {
  const [open, setOpen] = useState(false)
  const [session, setSession] = useState<FocusSession>(loadSession)
  const [now, setNow] = useState(Date.now)
  const [storageError, setStorageError] = useState(false)
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

  function startOrPause() {
    const time = Date.now()
    setNow(time)
    setSession((current) => current.phase === 'running'
      ? pauseFocus(current, time) : startFocus(current, time))
  }

  function reset() {
    if ((session.phase === 'running' || session.phase === 'paused') &&
        !window.confirm('Réinitialiser cette session ? La durée repartira au début.')) return
    setNow(Date.now())
    setSession((current) => resetFocus(current))
  }

  function clear() {
    if ((session.label || session.phase !== 'idle') &&
        !window.confirm('Effacer cette session de concentration et son intitulé ? Les tâches ne seront pas modifiées.')) return
    setNow(Date.now())
    setSession(createFocus())
  }

  const phaseLabel = session.phase === 'running' ? 'En cours'
    : session.phase === 'paused' ? 'En pause' : session.phase === 'finished' ? 'Terminée' : 'Prête'

  return <section className="focus-panel" aria-label="Concentration">
    <button type="button" className="secondary-button" aria-expanded={open}
      onClick={() => setOpen((current) => !current)}>
      {open ? 'Fermer la concentration' : 'Concentration'}
      {session.phase === 'running' || session.phase === 'paused' ? ` · ${formatFocusTime(remaining)}` : ''}
      {session.phase === 'finished' ? ' · Terminée' : ''}
    </button>
    {open && <div className="focus-panel-body">
      <p>Une session, une chose à la fois. Tu peux faire une pause quand tu veux.</p>
      <label>Sur quoi veux-tu avancer ? (facultatif)
        <input value={session.label} maxLength={200} disabled={!canConfigure}
          placeholder="Ex. : ouvrir mon document"
          onChange={(event) => {
            const label = event.target.value
            setSession((current) => createFocus(current.durationMs / 60000, label))
          }} />
      </label>
      <label>Durée
        <select value={session.durationMs / 60000} disabled={!canConfigure}
          onChange={(event) => {
            const minutes = Number(event.target.value)
            setSession((current) => createFocus(minutes, current.label))
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
        <button type="button" className="secondary-button" onClick={clear}>Effacer la session</button>
      </div>
      {session.phase === 'finished' && <p role="status">Session terminée. Aucune tâche n’a été marquée comme faite.</p>}
      {storageError && <p role="alert">Le minuteur fonctionne, mais le navigateur ne permet pas sa sauvegarde. Il ne sera pas récupéré après fermeture.</p>}
      <p className="focus-note">Session enregistrée dans ce navigateur, pas dans la mémoire de Mia.
        Aucun son ni notification. Si la page est fermée, le résultat apparaît à sa réouverture.</p>
    </div>}
  </section>
}

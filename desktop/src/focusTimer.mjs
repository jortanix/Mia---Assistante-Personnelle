export const FOCUS_MINUTES = Object.freeze([5, 15, 25, 45])

// Durée d'affichage du bouton d'annulation après un marquage (10 s). C'est une
// fenêtre côté panneau, pas une limite métier imposée par le serveur : le
// serveur vérifie le cycle de parcours et la version de la tâche, pas le temps.
export const UNDO_WINDOW_MS = 10_000

// Temps restant avant l'expiration de la fenêtre d'annulation, calculé depuis
// completed_at renvoyé par /complete/ (l'instant exact du marquage serveur).
// Au rechargement, on repart de cet instant : le délai n'est pas renouvelé.
export function undoWindowLeft(completedAtIso, now = Date.now()) {
  const completedAt = Date.parse(completedAtIso)
  if (Number.isNaN(completedAt)) return 0
  return Math.max(0, UNDO_WINDOW_MS - (now - completedAt))
}

export function createFocus(minutes = 25, label = '') {
  if (!FOCUS_MINUTES.includes(minutes)) throw new Error('Durée non prise en charge.')
  if (typeof label !== 'string' || label.length > 200) throw new Error('Intitulé invalide.')
  const durationMs = minutes * 60000
  return { version: 1, label, durationMs, remainingMs: durationMs, deadline: null, phase: 'idle' }
}

export function getRemaining(session, now = Date.now()) {
  return session.phase === 'running'
    ? Math.max(0, Math.min(session.durationMs, session.deadline - now))
    : session.remainingMs
}

export function settleFocus(session, now = Date.now()) {
  if (session.phase === 'running' && getRemaining(session, now) === 0) {
    return { ...session, phase: 'finished', remainingMs: 0, deadline: null }
  }
  return session
}

export function startFocus(session, now = Date.now()) {
  if (session.phase === 'running') return settleFocus(session, now)
  const remainingMs = session.phase === 'finished' ? session.durationMs : session.remainingMs
  return { ...session, phase: 'running', remainingMs, deadline: now + remainingMs }
}

export function pauseFocus(session, now = Date.now()) {
  if (session.phase !== 'running') return session
  const remainingMs = getRemaining(session, now)
  return { ...session, remainingMs, deadline: null, phase: remainingMs > 0 ? 'paused' : 'finished' }
}

export function resetFocus(session) {
  return createFocus(session.durationMs / 60000, session.label)
}

export function restoreFocus(raw, now = Date.now()) {
  try {
    const s = JSON.parse(raw)
    if (!s || typeof s !== 'object' || s.version !== 1 ||
        typeof s.label !== 'string' || s.label.length > 200 ||
        !Number.isSafeInteger(s.durationMs) || !FOCUS_MINUTES.includes(s.durationMs / 60000) ||
        !Number.isSafeInteger(s.remainingMs) || s.remainingMs < 0 || s.remainingMs > s.durationMs ||
        !['idle', 'running', 'paused', 'finished'].includes(s.phase)) return null
    if (s.phase === 'running') {
      if (!Number.isSafeInteger(s.deadline) || s.deadline < 0 || s.remainingMs === 0) return null
    } else {
      if (s.deadline !== null) return null
      if (s.phase === 'idle' && s.remainingMs !== s.durationMs) return null
      if (s.phase === 'finished' && s.remainingMs !== 0) return null
      if (s.phase === 'paused' && s.remainingMs === 0) return null
    }
    return settleFocus({ version: 1, label: s.label, durationMs: s.durationMs,
      remainingMs: s.remainingMs, deadline: s.deadline, phase: s.phase }, now)
  } catch { return null }
}

export function formatFocusTime(milliseconds) {
  const seconds = Math.ceil(Math.max(0, milliseconds) / 1000)
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`
}

// Reconstitue la session locale à partir de l'état enregistré côté MIA.
// L'horloge de MIA est la référence : au rechargement (page rouverte, onglet
// revenu au premier plan), on reprend le décompte à partir de l'échéance
// stockée en base plutôt que de l'ancienne copie locale.
export function sessionFromServer(data, now = Date.now()) {
  const durationMs = data.duration_minutes * 60000
  if (data.phase === 'running' && data.deadline) {
    const deadlineMs = Date.parse(data.deadline)
    if (!Number.isNaN(deadlineMs)) {
      return {
        version: 1, label: data.label, durationMs,
        remainingMs: Math.max(0, deadlineMs - now),
        deadline: deadlineMs, phase: 'running',
      }
    }
  }
  if (data.phase === 'paused' && typeof data.remaining_time_ms === 'number') {
    return {
      version: 1, label: data.label, durationMs,
      remainingMs: data.remaining_time_ms, deadline: null, phase: 'paused',
    }
  }
  if (data.phase === 'finished') {
    return {
      version: 1, label: data.label, durationMs,
      remainingMs: 0, deadline: null, phase: 'finished',
    }
  }
  return createFocus(data.duration_minutes, data.label)
}

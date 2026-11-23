export const FOCUS_MINUTES = Object.freeze([5, 15, 25, 45])

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

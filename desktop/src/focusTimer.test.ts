import { describe, expect, it } from 'vitest'
import { createFocus, formatFocusTime, getRemaining, pauseFocus,
  restoreFocus, sessionFromServer, settleFocus, startFocus, undoWindowLeft,
  UNDO_WINDOW_MS } from './focusTimer.mjs'
import type { ServerFocusSession } from './focusTimer.mjs'

describe('Minuteur de concentration', () => {
  it('crée une session initiale de 25 minutes', () => {
    const s = createFocus()
    expect(s.phase).toBe('idle')
    expect(s.remainingMs).toBe(1500000)
  })

  it('valide durée et intitulé', () => {
    expect(() => createFocus(7)).toThrow()
    expect(() => createFocus(25, 'a'.repeat(201))).toThrow()
  })

  it('calcule le temps restant depuis la date de fin', () => {
    const s = startFocus(createFocus(5), 1000)
    expect(getRemaining(s, 11000)).toBe(290000)
  })

  it('fait une pause puis reprend sans perdre le temps restant', () => {
    const paused = pauseFocus(startFocus(createFocus(5), 1000), 11000)
    expect(paused.remainingMs).toBe(290000)
    expect(paused.deadline).toBeNull()
    const resumed = startFocus(paused, 50000)
    expect(resumed.deadline).toBe(340000)
  })

  it('recharge sans redémarrer le minuteur', () => {
    const s = startFocus(createFocus(5), 1000)
    const restored = restoreFocus(JSON.stringify(s), 11000)!
    expect(restored.deadline).toBe(s.deadline)
    expect(getRemaining(restored, 11000)).toBe(290000)
  })

  it('récupère une session échue pendant que la page était fermée', () => {
    const restored = restoreFocus(JSON.stringify(startFocus(createFocus(5), 0)), 400000)!
    expect(restored.phase).toBe('finished')
    expect(restored.remainingMs).toBe(0)
  })

  it('rejette les données corrompues', () => {
    for (const raw of ['oops', 'null', '{}', JSON.stringify({ ...createFocus(), version: 2 }),
      JSON.stringify({ ...createFocus(), phase: 'running', deadline: null }),
      JSON.stringify({ ...createFocus(), remainingMs: -1 })]) expect(restoreFocus(raw, 0)).toBeNull()
  })

  it('arrondit l’affichage vers le haut, jamais négatif', () => {
    expect(formatFocusTime(299999)).toBe('05:00')
    expect(formatFocusTime(1001)).toBe('00:02')
    expect(formatFocusTime(-5)).toBe('00:00')
  })

  it('démarrer deux fois ne prolonge pas la session', () => {
    const s = startFocus(createFocus(5), 0)
    expect(startFocus(s, 1000).deadline).toBe(s.deadline)
  })

  it('recommencer une session terminée repart de la durée choisie', () => {
    const finished = settleFocus(startFocus(createFocus(5), 0), 300000)
    const restarted = startFocus(finished, 400000)
    expect(restarted.deadline).toBe(700000)
    expect(restarted.phase).toBe('running')
  })

  it('ne modifie pas la session source lors des transitions', () => {
    const s = Object.freeze(createFocus(5))
    const started = startFocus(s, 0)
    expect(s.phase).toBe('idle')
    expect(started.phase).toBe('running')
  })
})

describe('Réconciliation avec l’état enregistré côté MIA (rechargement)', () => {
  const base: ServerFocusSession = { duration_minutes: 25, label: 'Lire', phase: 'idle', deadline: null, remaining_time_ms: null }

  it('reprend une session en cours depuis l’échéance serveur', () => {
    const restartedNow = 1_000_000
    const deadline = new Date(restartedNow + 900000).toISOString()
    const s = sessionFromServer({ ...base, phase: 'running', deadline }, restartedNow)
    expect(s.phase).toBe('running')
    expect(s.deadline).toBe(restartedNow + 900000)
    expect(s.remainingMs).toBe(900000)
  })

  it('reprend après l’échéance : décompte à zéro, prêt à être terminé', () => {
    const restartedNow = 2_000_000
    const deadline = new Date(restartedNow - 30000).toISOString()
    const s = sessionFromServer({ ...base, phase: 'running', deadline }, restartedNow)
    expect(s.phase).toBe('running')
    expect(s.remainingMs).toBe(0)
    expect(settleFocus(s, restartedNow).phase).toBe('finished')
  })

  it('restaure une session en pause avec son temps restant', () => {
    const s = sessionFromServer({ ...base, phase: 'paused', remaining_time_ms: 450000 }, 0)
    expect(s.phase).toBe('paused')
    expect(s.remainingMs).toBe(450000)
    expect(s.deadline).toBeNull()
  })

  it('restaure une session terminée à zéro', () => {
    const s = sessionFromServer({ ...base, phase: 'finished' }, 0)
    expect(s.phase).toBe('finished')
    expect(s.remainingMs).toBe(0)
    expect(s.deadline).toBeNull()
  })

  it('laisse une session jamais lancée en état de configuration', () => {
    const s = sessionFromServer(base, 0)
    expect(s.phase).toBe('idle')
    expect(s.durationMs).toBe(1500000)
    expect(s.label).toBe('Lire')
  })

  it('garde la durée du serveur pour une session rechargée', () => {
    const s = sessionFromServer({ ...base, phase: 'finished' }, 0)
    expect(s.durationMs).toBe(1500000)
  })
})

describe('Fenêtre d’annulation (part du marquage serveur, non renouvelable au rechargement)', () => {
  it('offre les 10 secondes complètes juste après le marquage', () => {
    const markedAt = '2026-11-17T15:00:00+00:00'
    expect(undoWindowLeft(markedAt, Date.parse(markedAt))).toBe(UNDO_WINDOW_MS)
  })

  it('décroît à partir de l’instant du marquage', () => {
    const markedAt = Date.parse('2026-11-17T15:00:00+00:00')
    const iso = new Date(markedAt).toISOString()
    expect(undoWindowLeft(iso, markedAt + 4000)).toBe(6000)
  })

  it('est expirée au-delà de 10 secondes, même après rechargement', () => {
    const markedAt = Date.parse('2026-11-17T15:00:00+00:00')
    const iso = new Date(markedAt).toISOString()
    expect(undoWindowLeft(iso, markedAt + UNDO_WINDOW_MS + 1000)).toBe(0)
  })

  it('est expirée à l’instant exact du départ du décompte', () => {
    const markedAt = Date.parse('2026-11-17T15:00:00+00:00')
    const iso = new Date(markedAt).toISOString()
    expect(undoWindowLeft(iso, markedAt + UNDO_WINDOW_MS)).toBe(0)
  })

  it('renvoie 0 si la date est invalide', () => {
    expect(undoWindowLeft('pas-une-date', 0)).toBe(0)
  })

  it('ne renouvelle pas le délai quand la page est rouverte plus tard', () => {
    // Rechargement 20 s après le marquage : le panneau doit masquer l'annulation.
    const markedAt = Date.parse('2026-11-17T15:00:00+00:00')
    const iso = new Date(markedAt).toISOString()
    expect(undoWindowLeft(iso, markedAt + 20000)).toBe(0)
  })
})

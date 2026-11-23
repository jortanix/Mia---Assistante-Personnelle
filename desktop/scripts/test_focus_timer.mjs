import test from 'node:test'
import assert from 'node:assert/strict'
import { createFocus, getRemaining, settleFocus, startFocus, pauseFocus, resetFocus,
  restoreFocus, formatFocusTime } from '../src/focusTimer.mjs'

test('session initiale de 25 minutes', () => {
  const s = createFocus()
  assert.equal(s.phase, 'idle'); assert.equal(s.remainingMs, 1500000)
})
test('validation de la durée et du titre', () => {
  assert.throws(() => createFocus(7)); assert.throws(() => createFocus(25, 'a'.repeat(201)))
})
test('temps restant calculé depuis la date de fin', () => {
  const s = startFocus(createFocus(5), 1000)
  assert.equal(getRemaining(s, 11000), 290000)
})
test('pause puis reprise sans perdre le temps restant', () => {
  const paused = pauseFocus(startFocus(createFocus(5), 1000), 11000)
  assert.equal(paused.remainingMs, 290000); assert.equal(paused.deadline, null)
  const resumed = startFocus(paused, 50000)
  assert.equal(resumed.deadline, 340000)
})
test('rechargement sans redémarrer le minuteur', () => {
  const s = startFocus(createFocus(5), 1000)
  const restored = restoreFocus(JSON.stringify(s), 11000)
  assert.equal(restored.deadline, s.deadline); assert.equal(getRemaining(restored, 11000), 290000)
})
test('récupération après échéance page fermée', () => {
  const restored = restoreFocus(JSON.stringify(startFocus(createFocus(5), 0)), 400000)
  assert.equal(restored.phase, 'finished'); assert.equal(restored.remainingMs, 0)
})
test('pause après échéance donne terminé', () => {
  assert.equal(pauseFocus(startFocus(createFocus(5), 0), 400000).phase, 'finished')
})
test('réinitialiser conserve intitulé et durée', () => {
  const reset = resetFocus(pauseFocus(startFocus(createFocus(15, 'Lire'), 0), 1000))
  assert.equal(reset.phase, 'idle'); assert.equal(reset.label, 'Lire'); assert.equal(reset.remainingMs, 900000)
})
test('données corrompues refusées', () => {
  for (const raw of ['oops', 'null', '{}', JSON.stringify({ ...createFocus(), version: 2 }),
    JSON.stringify({ ...createFocus(), phase: 'running', deadline: null }),
    JSON.stringify({ ...createFocus(), remainingMs: -1 })]) assert.equal(restoreFocus(raw, 0), null)
})
test('seuls les champs reconnus sont restaurés', () => {
  const restored = restoreFocus(JSON.stringify({ ...createFocus(), unwanted: 'x' }), 0)
  assert.equal('unwanted' in restored, false)
})
test('affichage arrondi vers le haut et jamais négatif', () => {
  assert.equal(formatFocusTime(299999), '05:00'); assert.equal(formatFocusTime(1001), '00:02')
  assert.equal(formatFocusTime(-5), '00:00')
})
test('démarrer deux fois ne prolonge pas la session', () => {
  const s = startFocus(createFocus(5), 0)
  assert.equal(startFocus(s, 1000).deadline, s.deadline)
})
test('recommencer une session terminée repart de la durée choisie', () => {
  const finished = settleFocus(startFocus(createFocus(5), 0), 300000)
  const restarted = startFocus(finished, 400000)
  assert.equal(restarted.deadline, 700000); assert.equal(restarted.phase, 'running')
})
test('les transitions ne modifient pas la session source', () => {
  const s = Object.freeze(createFocus(5))
  const started = startFocus(s, 0)
  assert.equal(s.phase, 'idle'); assert.equal(started.phase, 'running')
})

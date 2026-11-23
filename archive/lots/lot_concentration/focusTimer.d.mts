export type FocusPhase = 'idle' | 'running' | 'paused' | 'finished'
export type FocusSession = {
  version: 1
  label: string
  durationMs: number
  remainingMs: number
  deadline: number | null
  phase: FocusPhase
}
export const FOCUS_MINUTES: readonly number[]
export function createFocus(minutes?: number, label?: string): FocusSession
export function getRemaining(session: FocusSession, now?: number): number
export function settleFocus(session: FocusSession, now?: number): FocusSession
export function startFocus(session: FocusSession, now?: number): FocusSession
export function pauseFocus(session: FocusSession, now?: number): FocusSession
export function resetFocus(session: FocusSession): FocusSession
export function restoreFocus(raw: string, now?: number): FocusSession | null
export function formatFocusTime(milliseconds: number): string

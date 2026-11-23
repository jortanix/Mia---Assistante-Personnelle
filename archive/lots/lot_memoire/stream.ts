export type StreamEvent =
  | { type: 'start'; conversation_id: number }
  | { type: 'delta'; content: string }
  | { type: 'done'; conversation_id: number; action_proposal?: unknown }
  | { type: 'error'; message: string }

const decoder = new TextDecoder()

export function createStreamParser() {
  let buffer = ''

  return function processChunk(chunk: Uint8Array): StreamEvent[] {
    buffer += decoder.decode(chunk, { stream: true })
    const events: StreamEvent[] = []
    let newlineIndex: number

    while ((newlineIndex = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, newlineIndex).trim()
      buffer = buffer.slice(newlineIndex + 1)

      if (!line) continue

      try {
        events.push(JSON.parse(line) as StreamEvent)
      } catch {
        // Ligne JSON incomplète ou invalide ; on ignore.
      }
    }

    return events
  }
}

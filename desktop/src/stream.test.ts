import { describe, expect, it } from 'vitest'
import { createStreamParser } from './stream'

function encode(text: string): Uint8Array {
  return new TextEncoder().encode(text)
}

function textFromBytes(bytes: number[]): Uint8Array {
  return new Uint8Array(bytes)
}

describe('createStreamParser', () => {
  it('parses complete lines from a single fragment', () => {
    const process = createStreamParser()
    const events = process(
      encode('{"type":"start","conversation_id":3}\n{"type":"delta","content":"Bonjour"}\n'),
    )
    expect(events).toEqual([
      { type: 'start', conversation_id: 3 },
      { type: 'delta', content: 'Bonjour' },
    ])
  })

  it('buffers partial lines across fragments', () => {
    const process = createStreamParser()
    const first = process(encode('{"type":"delta","content":"B'))
    const second = process(encode('onjour"}\n'))
    expect(first).toEqual([])
    expect(second).toEqual([{ type: 'delta', content: 'Bonjour' }])
  })

  it('handles several lines within a single fragment', () => {
    const process = createStreamParser()
    const events = process(
      encode('{"type":"delta","content":"a"}\n{"type":"delta","content":"b"}\n{"type":"done","conversation_id":3}\n'),
    )
    expect(events).toEqual([
      { type: 'delta', content: 'a' },
      { type: 'delta', content: 'b' },
      { type: 'done', conversation_id: 3 },
    ])
  })

  it('decodes accented characters split across multi-byte fragments', () => {
    const process = createStreamParser()
    const bytes = Array.from(encode('{"type":"delta","content":"é à ç ï"}\n'))
    const mid = Math.floor(bytes.length / 2)

    const first = process(textFromBytes(bytes.slice(0, mid)))
    const second = process(textFromBytes(bytes.slice(mid)))

    expect([...first, ...second]).toEqual([{ type: 'delta', content: 'é à ç ï' }])
  })

  it('keeps an accented character intact when it straddles a fragment boundary', () => {
    const process = createStreamParser()

    const bytes = Array.from(encode('{"type":"delta","content":"é"}\n'))
    const boundary = bytes.findIndex(
      (b, i) =>
        i > 0 && (bytes[i - 1] & 0xc0) === 0xc0 && (b & 0xc0) === 0x80,
    )

    const first = process(textFromBytes(bytes.slice(0, boundary)))
    const second = process(textFromBytes(bytes.slice(boundary)))

    expect([...first, ...second]).toEqual([{ type: 'delta', content: 'é' }])
  })

  it('ignores malformed JSON lines without throwing', () => {
    const process = createStreamParser()
    const events = process(encode('not-json\n{"type":"delta","content":"ok"}\n'))
    expect(events).toEqual([{ type: 'delta', content: 'ok' }])
  })
})

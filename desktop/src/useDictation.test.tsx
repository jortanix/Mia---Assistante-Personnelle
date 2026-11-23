import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDictation } from './useDictation'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function makeStream() {
  const stop = vi.fn()
  const tracks = [{ stop }]
  const stream = { getTracks: () => tracks } as unknown as MediaStream
  return { stream, stop }
}

class MockMediaRecorder {
  static instances: MockMediaRecorder[] = []
  static isTypeSupported = () => true

  mimeType = 'audio/webm'
  state: 'inactive' | 'recording' = 'inactive'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(_stream: MediaStream, opts?: { mimeType?: string }) {
    if (opts?.mimeType) this.mimeType = opts.mimeType
    MockMediaRecorder.instances.push(this)
  }

  start() {
    this.state = 'recording'
  }

  stop() {
    this.state = 'inactive'
    this.onstop?.()
  }
}

function setGetUserMedia(impl: () => Promise<MediaStream>) {
  const fn = vi.fn(impl)
  Object.defineProperty(globalThis.navigator, 'mediaDevices', {
    value: { getUserMedia: fn },
    configurable: true,
  })
  return fn
}

function okResponse(text: string) {
  return {
    ok: true,
    json: async () => ({ text }),
  }
}

beforeEach(() => {
  MockMediaRecorder.instances = []
  vi.stubGlobal('MediaRecorder', MockMediaRecorder)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('useDictation lifecycle', () => {
  it('only calls getUserMedia once on a double click during pending authorization', async () => {
    const auth = deferred<MediaStream>()
    const getUserMedia = setGetUserMedia(() => auth.promise)

    const { result } = renderHook(() =>
      useDictation({ isDisabled: false, onText: vi.fn() }),
    )

    await act(async () => {
      result.current.startRecording()
      result.current.startRecording()
    })

    expect(getUserMedia).toHaveBeenCalledTimes(1)
    expect(result.current.state).toBe('requesting')
  })

  it('reports isBusy while the authorization is pending', async () => {
    const auth = deferred<MediaStream>()
    setGetUserMedia(() => auth.promise)

    const { result } = renderHook(() =>
      useDictation({ isDisabled: false, onText: vi.fn() }),
    )

    await act(async () => {
      result.current.startRecording()
    })

    expect(result.current.isBusy).toBe(true)
    expect(result.current.isRecording).toBe(false)
  })

  it('stops the resolved stream and starts no recorder when getUserMedia resolves after cleanup', async () => {
    const auth = deferred<MediaStream>()
    setGetUserMedia(() => auth.promise)
    const { stream, stop } = makeStream()

    const { result, unmount } = renderHook(() =>
      useDictation({ isDisabled: false, onText: vi.fn() }),
    )

    await act(async () => {
      result.current.startRecording()
    })

    unmount()

    await act(async () => {
      auth.resolve(stream)
    })

    expect(stop).toHaveBeenCalled()
    expect(MockMediaRecorder.instances).toHaveLength(0)
  })

  it('does not call onText when the component unmounts during transcription', async () => {
    setGetUserMedia(async () => makeStream().stream)
    const transcribe = deferred<ReturnType<typeof okResponse>>()
    const fetchMock = vi.fn(() => transcribe.promise)
    vi.stubGlobal('fetch', fetchMock)

    const onText = vi.fn()
    const { result, unmount } = renderHook(() =>
      useDictation({ isDisabled: false, onText }),
    )

    await act(async () => {
      await result.current.startRecording()
    })
    expect(result.current.state).toBe('recording')

    const recorder = MockMediaRecorder.instances[0]
    await act(async () => {
      recorder.ondataavailable?.({ data: new Blob(['audio']) })
      recorder.stop()
    })

    expect(result.current.state).toBe('transcribing')
    expect(fetchMock).toHaveBeenCalledTimes(1)

    unmount()

    await act(async () => {
      transcribe.resolve(okResponse('Bonjour'))
    })

    expect(onText).not.toHaveBeenCalled()
  })

  it('does not upload after a recording error followed by a stale onstop', async () => {
    setGetUserMedia(async () => makeStream().stream)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() =>
      useDictation({ isDisabled: false, onText: vi.fn() }),
    )

    await act(async () => {
      await result.current.startRecording()
    })

    const recorder = MockMediaRecorder.instances[0]
    const staleOnstop = recorder.onstop

    await act(async () => {
      recorder.onerror?.()
    })

    await act(async () => {
      staleOnstop?.()
    })

    expect(fetchMock).not.toHaveBeenCalled()
  })
})

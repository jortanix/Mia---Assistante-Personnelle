import { useCallback, useEffect, useRef, useState } from 'react'

export type DictationState =
  | 'idle'
  | 'requesting'
  | 'recording'
  | 'transcribing'
  | 'error'

const MAX_DURATION_SECONDS = 60
const TRANSCRIBE_URL = '/api/audio/transcribe/'
const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']

type UseDictationOptions = {
  isDisabled: boolean
  onText: (text: string) => void
}

function isPermissionError(error: unknown): boolean {
  if (typeof error !== 'object' || error === null) return false
  const name = (error as { name?: unknown }).name
  return name === 'NotAllowedError' || name === 'PermissionDeniedError'
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined
  for (const candidate of MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported(candidate)) return candidate
  }
  return undefined
}

function apiMessage(value: unknown, fallback: string): string {
  if (typeof value === 'object' && value !== null) {
    const data = value as Record<string, unknown>
    if (typeof data.error === 'string') return data.error
    if (typeof data.detail === 'string') return data.detail
  }
  return fallback
}

function extractText(value: unknown): string {
  if (typeof value === 'object' && value !== null) {
    const text = (value as Record<string, unknown>).text
    if (typeof text === 'string') return text.trim()
  }
  return ''
}

export function useDictation({ isDisabled, onText }: UseDictationOptions) {
  const [state, setState] = useState<DictationState>('idle')
  const [error, setError] = useState<string | null>(null)
  const [duration, setDuration] = useState(0)
  const [transcript, setTranscript] = useState<string | null>(null)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<number | null>(null)
  const transcribeControllerRef = useRef<AbortController | null>(null)
  const disabledRef = useRef(isDisabled)
  const onTextRef = useRef(onText)
  const mountedRef = useRef(true)
  const startingRef = useRef(false)
  const opIdRef = useRef(0)

  useEffect(() => {
    disabledRef.current = isDisabled
  }, [isDisabled])

  useEffect(() => {
    onTextRef.current = onText
  }, [onText])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const stopTracks = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }, [])

  const finalize = useCallback(
    async (opId: number) => {
      const recorder = recorderRef.current
      const mimeType = recorder?.mimeType
      const chunks = chunksRef.current
      chunksRef.current = []

      stopTracks()
      clearTimer()
      recorderRef.current = null

      if (opIdRef.current !== opId || !mountedRef.current) return

      setDuration(0)
      setState('transcribing')

      const blob = new Blob(chunks, { type: mimeType })
      if (blob.size === 0) {
        setState('error')
        setError("Aucun son n'a été enregistré.")
        return
      }

      const controller = new AbortController()
      transcribeControllerRef.current = controller
      const formData = new FormData()
      formData.append('audio', blob, 'dictation.webm')

      try {
        const response = await fetch(TRANSCRIBE_URL, {
          method: 'POST',
          body: formData,
          signal: controller.signal,
        })
        const data: unknown = await response.json().catch(() => null)

        if (opIdRef.current !== opId || !mountedRef.current) return

        if (!response.ok) {
          setState('error')
          setError(apiMessage(data, 'La transcription a échoué.'))
          return
        }

        const text = extractText(data)
        if (text) {
          setTranscript(text)
          onTextRef.current(text)
        }
        setState('idle')
      } catch (caught) {
        if (opIdRef.current !== opId || !mountedRef.current) return
        if (isAbortError(caught)) return
        setState('error')
        setError('La transcription a échoué.')
      } finally {
        if (transcribeControllerRef.current === controller) {
          transcribeControllerRef.current = null
        }
      }
    },
    [clearTimer, stopTracks],
  )

  const stopRecording = useCallback(() => {
    clearTimer()
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop()
    }
  }, [clearTimer])

  const startRecording = useCallback(async () => {
    if (
      disabledRef.current ||
      state === 'recording' ||
      state === 'transcribing' ||
      state === 'requesting'
    ) {
      return
    }
    if (startingRef.current) return

    startingRef.current = true
    const opId = ++opIdRef.current
    setError(null)
    setState('requesting')

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (caught) {
      startingRef.current = false
      if (opIdRef.current !== opId || !mountedRef.current) return
      setState('error')
      setError(
        isPermissionError(caught)
          ? 'Accès au microphone refusé.'
          : 'Aucun microphone disponible.',
      )
      return
    }

    if (opIdRef.current !== opId || !mountedRef.current) {
      stream.getTracks().forEach((track) => track.stop())
      startingRef.current = false
      return
    }

    startingRef.current = false
    streamRef.current = stream

    const mimeType = pickMimeType()
    let recorder: MediaRecorder
    try {
      recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream)
    } catch {
      stopTracks()
      setState('error')
      setError("L'enregistrement audio n'est pas pris en charge par ce navigateur.")
      return
    }

    chunksRef.current = []
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        chunksRef.current.push(event.data)
      }
    }
    recorder.onstop = () => {
      if (opIdRef.current === opId && mountedRef.current) {
        void finalize(opId)
      }
    }
    recorder.onerror = () => {
      opIdRef.current += 1
      recorder.onstop = null
      clearTimer()
      stopTracks()
      recorderRef.current = null
      chunksRef.current = []
      if (mountedRef.current) {
        setState('error')
        setError("Une erreur est survenue pendant l'enregistrement.")
      }
    }

    recorder.start()
    recorderRef.current = recorder
    setState('recording')
    setDuration(0)

    timerRef.current = window.setInterval(() => {
      setDuration((current) => {
        const next = current + 1
        if (next >= MAX_DURATION_SECONDS) {
          stopRecording()
        }
        return next
      })
    }, 1000)
  }, [clearTimer, finalize, state, stopTracks, stopRecording])

  const cleanup = useCallback(() => {
    startingRef.current = false
    opIdRef.current += 1
    transcribeControllerRef.current?.abort()
    transcribeControllerRef.current = null
    clearTimer()
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.onstop = null
      recorder.stop()
    }
    stopTracks()
    recorderRef.current = null
    chunksRef.current = []
  }, [clearTimer, stopTracks])

  useEffect(() => cleanup, [cleanup])

  const resetError = useCallback(() => {
    setState('idle')
    setError(null)
  }, [])

  const cancelTranscript = useCallback(() => {
    setTranscript(null)
    setState('idle')
    setError(null)
  }, [])

  const confirmTranscript = useCallback(() => {
    if (transcript) {
      onTextRef.current(transcript)
    }
    setTranscript(null)
    setState('idle')
    setError(null)
  }, [transcript, onTextRef])

  return {
    state,
    error,
    duration,
    isRecording: state === 'recording',
    isBusy:
      state === 'requesting' ||
      state === 'recording' ||
      state === 'transcribing',
    startRecording,
    stopRecording,
    resetError,
    transcript,
    cancelTranscript,
    confirmTranscript,
  }
}
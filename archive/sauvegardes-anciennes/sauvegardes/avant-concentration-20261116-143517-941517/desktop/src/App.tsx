import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent, UIEvent } from 'react'
import './App.css'
import { Markdown } from './Markdown'
import { createStreamParser } from './stream'
import { useDictation } from './useDictation'
import { MemoryPanel } from './MemoryPanel'
import { TaskPanel } from './TaskPanel'
import { TaskProposalCard } from './TaskProposalCard'
import { isTaskProposal } from './taskApi'
import type { TaskProposal } from './taskApi'
import { MemoryProposalCard, isMemoryProposal } from './MemoryProposalCard'
import type { MemoryProposal } from './MemoryProposalCard'

type Role = 'user' | 'assistant'

type Message = {
  id: number
  role: Role
  content: string
  created_at: string
}

type Conversation = {
  id: number
  title: string
  created_at: string
  updated_at: string
}

type ConversationDetail = Conversation & {
  messages: Message[]
  action_proposals?: unknown[]
}

type LocalMessage = {  id: string
  role: Role
  content: string
  status?: 'streaming' | 'error' | 'done'
  memoryProposal?: MemoryProposal
  taskProposal?: TaskProposal
}

const STORAGE_KEY = 'mia.selectedConversation'
const NEAR_BOTTOM_THRESHOLD = 120

function getApiError(value: unknown): string {
  if (typeof value === 'object' && value !== null) {
    const data = value as Record<string, unknown>

    if (typeof data.error === 'string') return data.error
    if (typeof data.detail === 'string') return data.detail
  }

  return "Impossible d'obtenir une réponse de MIA."
}

function toLocalMessages(
  messages: Message[],
  proposals: unknown[] = [],
): LocalMessage[] {
  const memories = proposals.filter(isMemoryProposal)
  const tasks = proposals.filter(isTaskProposal)
  return messages.map((message) => ({
    id: String(message.id),
    role: message.role,
    content: message.content,
    status: 'done',
    memoryProposal: memories.find(
      (proposal) => proposal.assistant_message_id === message.id,
    ),
    taskProposal: tasks.find(
      (proposal) => proposal.assistant_message_id === message.id,
    ),
  }))
}

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [messages, setMessages] = useState<LocalMessage[]>([])
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showScrollButton, setShowScrollButton] = useState(false)
  const [autoSpeak, setAutoSpeak] = useState(false)
  const [useMemory, setUseMemory] = useState(false)
  const [autoSendDictation, setAutoSendDictation] = useState(false)
  const autoSendDictationRef = useRef(false)
  const autoSpeakRef = useRef(false)

  async function speakReply(text: string, automatic = false) {
    if (!text.trim()) return

    if (!('speechSynthesis' in window)) {
      setError('La lecture vocale n’est pas disponible dans ce navigateur.')
      return
    }

    const synth = window.speechSynthesis

    const findVoice = () =>
      synth.getVoices().find(
        (candidate) =>
          candidate.localService &&
          /^fr(?:[-_]|$)/i.test(candidate.lang)
      )

    let voice = findVoice()

    if (!voice) {
      await new Promise<void>((resolve) => {
        const finish = () => {
          window.clearTimeout(timeout)
          window.clearInterval(interval)
          synth.removeEventListener('voiceschanged', check)
          resolve()
        }

        const check = () => {
          if (findVoice()) finish()
        }

        const timeout = window.setTimeout(finish, 3000)
        const interval = window.setInterval(check, 100)

        synth.addEventListener('voiceschanged', check)
        check()
      })

      voice = findVoice()
    }

    // Ne pas lancer la lecture si l’option a été décochée pendant l’attente.
    if (automatic && !autoSpeakRef.current) return

    if (!voice) {
      setError('Aucune voix française locale disponible après trois secondes.')
      return
    }

    setError(null)
    synth.cancel()

    const speech = new SpeechSynthesisUtterance(text)
    speech.voice = voice
    speech.lang = voice.lang
    speech.rate = 1

    speech.onerror = (event) => {
      if (
        event.error !== 'canceled' &&
        event.error !== 'interrupted'
      ) {
        setError('La lecture vocale a échoué : ' + event.error)
      }
    }
    synth.speak(speech)
  }
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')
  const [renameError, setRenameError] = useState<string | null>(null)

  const [deletingConversation, setDeletingConversation] =
    useState<Conversation | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const openRequestRef = useRef(0)
  const scrollRef = useRef<HTMLElement | null>(null)
  const nearBottomRef = useRef(true)
  const deleteModalRef = useRef<HTMLDivElement | null>(null)
  const lastFocusedRef = useRef<HTMLElement | null>(null)
  const cancelButtonRef = useRef<HTMLButtonElement | null>(null)
  const isDeletingRef = useRef(isDeleting)
  const cancelDeleteRef = useRef<() => void>(() => {})

  useEffect(() => {
    isDeletingRef.current = isDeleting
  }, [isDeleting])

  useEffect(() => {
    cancelDeleteRef.current = cancelDelete
  })

  useEffect(() => {
    if (!deletingConversation) {
      const origin = lastFocusedRef.current
      lastFocusedRef.current = null
      if (!origin) return
      if (document.contains(origin)) {
        origin.focus()
      } else {
        document.querySelector<HTMLButtonElement>('.new-chat-button')?.focus()
      }
      return
    }

    lastFocusedRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    cancelButtonRef.current?.focus()

    const modal = deleteModalRef.current

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        if (!isDeletingRef.current) {
          event.preventDefault()
          cancelDeleteRef.current()
        }
        return
      }

      if (event.key !== 'Tab' || !modal) return

      const focusables = Array.from(
        modal.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute('disabled'))

      if (focusables.length === 0) return

      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      const active = document.activeElement

      if (event.shiftKey) {
        if (active === first || !modal.contains(active)) {
          event.preventDefault()
          last.focus()
        }
      } else if (active === last || !modal.contains(active)) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [deletingConversation])

  const appendDictatedText = (text: string) => {
    const dictatedText = text.trim()
    if (!dictatedText) return

    if (autoSendDictationRef.current && !isLoading) {
      const draft = input.trim()
      const content = draft
        ? `${draft} ${dictatedText}`
        : dictatedText

      void sendMessage(content)
      return
    }

    setInput((current) => {
      const trimmed = current.trim()
      return trimmed ? `${trimmed} ${dictatedText}` : dictatedText
    })
  }

  const dictation = useDictation({
    isDisabled: isLoading,
    onText: appendDictatedText,
  })

  useEffect(() => {
    loadConversations()
    restoreSelection()
  }, [])

  async function loadConversations() {
    try {
      const response = await fetch('/api/conversations/')
      if (!response.ok) return

      const data: unknown = await response.json()
      if (!Array.isArray(data)) return

      setConversations(
        data
          .filter(isConversation)
          .sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
      )
    } catch {
      // La liste est optionnelle ; on ignore les erreurs de chargement.
    }
  }

  function isConversation(value: unknown): value is Conversation {
    if (typeof value !== 'object' || value === null) return false
    const data = value as Record<string, unknown>
    return (
      typeof data.id === 'number' &&
      typeof data.title === 'string' &&
      typeof data.updated_at === 'string'
    )
  }

  function restoreSelection() {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === null) return

    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'number' || !Number.isInteger(parsed)) {
      localStorage.removeItem(STORAGE_KEY)
      return
    }

    openConversation(parsed)
  }

  async function openConversation(id: number) {
    const requestToken = ++openRequestRef.current

    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch(`/api/conversations/${id}/`)

      if (response.status === 404) {
        if (requestToken !== openRequestRef.current) return
        localStorage.removeItem(STORAGE_KEY)
        setSelectedId(null)
        setConversationId(null)
        setMessages([])
        return
      }

      const data: unknown = await response.json()

      if (!response.ok) {
        throw new Error(getApiError(data))
      }

      if (!isConversationDetail(data)) {
        throw new Error('Le serveur a renvoyé une réponse inattendue.')
      }

      if (requestToken !== openRequestRef.current) return

      setSelectedId(data.id)
      setConversationId(data.id)
      setMessages(toLocalMessages(
        data.messages,
        Array.isArray(data.action_proposals) ? data.action_proposals : [],
      ))
      localStorage.setItem(STORAGE_KEY, String(data.id))
      scrollToBottom(true)
    } catch (caught) {
      if (requestToken !== openRequestRef.current) return
      setError(
        caught instanceof Error
          ? caught.message
          : 'Impossible de rouvrir cette conversation.',
      )
    } finally {
      if (requestToken === openRequestRef.current) {
        setIsLoading(false)
      }
    }
  }

  function isConversationDetail(value: unknown): value is ConversationDetail {
    if (typeof value !== 'object' || value === null) return false
    const data = value as Record<string, unknown>
    return (
      typeof data.id === 'number' &&
      typeof data.title === 'string' &&
      typeof data.updated_at === 'string' &&
      Array.isArray(data.messages) &&
      data.messages.every(isMessage)
    )
  }

  function isMessage(value: unknown): value is Message {
    if (typeof value !== 'object' || value === null) return false
    const data = value as Record<string, unknown>
    return (
      typeof data.id === 'number' &&
      (data.role === 'user' || data.role === 'assistant') &&
      typeof data.content === 'string'
    )
  }

  function handleScroll(event: UIEvent<HTMLElement>) {
    const el = event.currentTarget
    const distanceFromBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight
    const nearBottom = distanceFromBottom <= NEAR_BOTTOM_THRESHOLD

    nearBottomRef.current = nearBottom
    setShowScrollButton(!nearBottom)
  }

  function scrollToBottom(force = false) {
    const el = scrollRef.current
    if (!el) return
    if (!force && !nearBottomRef.current) return

    el.scrollTop = el.scrollHeight
  }

  function appendToMessage(id: string, delta: string) {
    setMessages((previous) =>
      previous.map((message) =>
        message.id === id
          ? { ...message, content: message.content + delta }
          : message,
      ),
    )
    scrollToBottom()
  }

  function markAssistantMessage(id: string, status: LocalMessage['status']) {
    setMessages((previous) =>
      previous.map((message) =>
        message.id === id ? { ...message, status } : message,
      ),
    )
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (dictation.isBusy) return

    await sendMessage(input)
  }

  async function sendMessage(text: string) {
    const content = text.trim()
    if (!content || isLoading) return

    const userMessageId = crypto.randomUUID()
    const assistantMessageId = crypto.randomUUID()

    setMessages((previous) => [
      ...previous,
      { id: userMessageId, role: 'user', content },
      { id: assistantMessageId, role: 'assistant', content: '', status: 'streaming' },
    ])
    setInput('')
    setIsLoading(true)
    setError(null)
    scrollToBottom(true)

    const previousConversationId = conversationId

    try {
      const response = await fetch('/api/chat/stream/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: content,
          use_memory: useMemory,
          ...(conversationId !== null
            ? { conversation_id: conversationId }
            : {}),
        }),
      })

      if (!response.ok || !response.body) {
        const data: unknown = await response.json().catch(() => null)
        throw new Error(getApiError(data))
      }

      const reader = response.body.getReader()
      const parser = createStreamParser()
      let interrupted = true
      let replyText = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        for (const event of parser(value)) {
          if (event.type === 'start') {
            setConversationId(event.conversation_id)
            setSelectedId(event.conversation_id)
            if (previousConversationId === null) {
              localStorage.setItem(STORAGE_KEY, String(event.conversation_id))
            }
          } else if (event.type === 'delta') {
            replyText += event.content
            appendToMessage(assistantMessageId, event.content)
          } else if (event.type === 'done') {
            const proposal = event.action_proposal
            if (isMemoryProposal(proposal)) {
              setMessages((previous) => previous.map((message) =>
                message.id === assistantMessageId
                  ? { ...message, memoryProposal: proposal }
                  : message,
              ))
            }
            if (isTaskProposal(proposal)) {
              setMessages((previous) => previous.map((message) =>
                message.id === assistantMessageId
                  ? { ...message, taskProposal: proposal }
                  : message,
              ))
            }
            markAssistantMessage(assistantMessageId, 'done')
            interrupted = false

            if (autoSpeakRef.current) {
              void speakReply(replyText, true)
            }
          } else if (event.type === 'error') {
            markAssistantMessage(assistantMessageId, 'error')
            setError(event.message)
            interrupted = false
          }
        }
      }

      if (interrupted) {
        markAssistantMessage(assistantMessageId, 'error')
        setError('La réponse de MIA a été interrompue.')
      } else {
        loadConversations()
      }
    } catch (caught) {
      markAssistantMessage(assistantMessageId, 'error')
      setError(
        caught instanceof Error
          ? caught.message
          : 'Une erreur inattendue est survenue.',
      )
    } finally {
      setIsLoading(false)
    }
  }

  function startNewConversation() {
    if (isLoading || dictation.isBusy) return

    setSelectedId(null)
    setConversationId(null)
    setMessages([])
    setInput('')
    setError(null)
    setShowScrollButton(false)
    nearBottomRef.current = true
    localStorage.removeItem(STORAGE_KEY)
  }

  function startRename(conversation: Conversation) {
    setRenameError(null)
    setEditingId(conversation.id)
    setEditValue(conversation.title)
  }

  function cancelRename() {
    setEditingId(null)
    setEditValue('')
    setRenameError(null)
  }

  async function submitRename(conversation: Conversation) {
    const title = editValue.trim()
    if (!title) {
      setRenameError('Le titre ne peut pas être vide.')
      return
    }

    try {
      const response = await fetch(`/api/conversations/${conversation.id}/`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ title }),
      })
      const data: unknown = await response.json().catch(() => null)

      if (!response.ok) {
        throw new Error(getApiError(data))
      }

      setConversations((previous) =>
        previous
          .map((item) =>
            item.id === conversation.id
              ? {
                  ...item,
                  title: data && typeof data === 'object'
                    ? ((data as Record<string, unknown>).title as string) ?? title
                    : title,
                }
              : item,
          )
          .sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
      )
      cancelRename()
    } catch (caught) {
      setRenameError(
        caught instanceof Error
          ? caught.message
          : 'Impossible de renommer cette conversation.',
      )
    }
  }

  function handleRenameKeyDown(
    event: KeyboardEvent<HTMLInputElement>,
    conversation: Conversation,
  ) {
    if (event.key === 'Enter') {
      void submitRename(conversation)
    } else if (event.key === 'Escape') {
      cancelRename()
    }
  }

  function requestDelete(conversation: Conversation) {
    setDeleteError(null)
    setDeletingConversation(conversation)
  }

  function cancelDelete() {
    if (isDeleting) return
    setDeletingConversation(null)
    setDeleteError(null)
  }

  async function confirmDelete() {
    if (!deletingConversation || isDeleting) return
    const conversation = deletingConversation

    setIsDeleting(true)
    setDeleteError(null)

    try {
      const response = await fetch(`/api/conversations/${conversation.id}/`, {
        method: 'DELETE',
      })

      if (!response.ok && response.status !== 204) {
        const data: unknown = await response.json().catch(() => null)
        throw new Error(getApiError(data))
      }

      setConversations((previous) =>
        previous.filter((item) => item.id !== conversation.id),
      )

      if (selectedId === conversation.id) {
        setSelectedId(null)
        setConversationId(null)
        setMessages([])
        setInput('')
        setError(null)
        setShowScrollButton(false)
        nearBottomRef.current = true
        localStorage.removeItem(STORAGE_KEY)
      }

      setDeletingConversation(null)
    } catch (caught) {
      setDeleteError(
        caught instanceof Error
          ? caught.message
          : 'Impossible de supprimer cette conversation.',
      )
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <main className="app">
      <aside className="sidebar" aria-label="Conversations">
        <button
          className="secondary-button new-chat-button"
          onClick={startNewConversation}
          disabled={isLoading || dictation.isBusy}
        >
          Nouvelle conversation
        </button>

        <ul className="conversation-list">
          {conversations.map((conversation) => {
            const isEditing = editingId === conversation.id
            const itemBusy = isLoading || dictation.isBusy

            return (
              <li key={conversation.id}>
                {isEditing ? (
                  <div className="conversation-edit">
                    <input
                      className="conversation-edit-input"
                      value={editValue}
                      onChange={(event) => setEditValue(event.target.value)}
                      onKeyDown={(event) =>
                        handleRenameKeyDown(event, conversation)
                      }
                      maxLength={200}
                      autoFocus
                      aria-label="Nouveau titre"
                    />
                    {renameError && (
                      <p className="error conversation-edit-error">{renameError}</p>
                    )}
                    <div className="conversation-edit-actions">
                      <button
                        type="button"
                        onClick={() => void submitRename(conversation)}
                      >
                        OK
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={cancelRename}
                      >
                        Annuler
                      </button>
                    </div>
                  </div>
                ) : (
                  <div
                    className={`conversation-item-row ${
                      conversation.id === selectedId
                        ? 'conversation-item-row--active'
                        : ''
                    }`}
                  >
                    <button
                      type="button"
                      className="conversation-item"
                      onClick={() => openConversation(conversation.id)}
                      disabled={itemBusy}
                      title={conversation.title}
                    >
                      {conversation.title}
                    </button>
                    <button
                      type="button"
                      className="conversation-action"
                      onClick={() => startRename(conversation)}
                      disabled={itemBusy}
                      aria-label={`Renommer ${conversation.title}`}
                      title="Renommer"
                    >
                      ✏️
                    </button>
                    <button
                      type="button"
                      className="conversation-action"
                      onClick={() => requestDelete(conversation)}
                      disabled={itemBusy}
                      aria-label={`Supprimer ${conversation.title}`}
                      title="Supprimer"
                    >
                      🗑️
                    </button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      </aside>

      {deletingConversation && (
        <div className="modal-backdrop" onClick={cancelDelete}>
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-modal-title"
            aria-busy={isDeleting}
            ref={deleteModalRef}
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="delete-modal-title">Supprimer la conversation ?</h2>
            <p>
              « {deletingConversation.title} » et tous ses messages seront
              définitivement supprimés. Cette action est irréversible.
            </p>
            {deleteError && (
              <p className="error" role="alert">
                {deleteError}
              </p>
            )}
            <div className="modal-actions">
              <button
                type="button"
                className="danger-button"
                onClick={() => void confirmDelete()}
                disabled={isDeleting}
              >
                {isDeleting ? 'Suppression…' : 'Supprimer'}
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={cancelDelete}
                disabled={isDeleting}
                ref={cancelButtonRef}
              >
                Annuler
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="content">
        <header className="header">
          <div>
            <p className="eyebrow">ASSISTANTE PERSONNELLE LOCALE</p>
            <h1>MIA</h1>
            <TaskPanel disabled={isLoading || dictation.isBusy} />
            <MemoryPanel
              enabled={useMemory}
              onEnabledChange={setUseMemory}
              disabled={isLoading || dictation.isBusy}
            />
            <label>
              <input
                type="checkbox"
                checked={autoSpeak}
                onChange={(event) => {
                  const enabled = event.target.checked
                  setAutoSpeak(enabled)
                  autoSpeakRef.current = enabled

                  if ('speechSynthesis' in window) {
                    window.speechSynthesis.getVoices()

                    if (!enabled) {
                      window.speechSynthesis.cancel()
                    }
                  }
                }}
              />
              {' '}Lecture automatique
            </label>
            <label>
              <input
                type="checkbox"
                checked={autoSendDictation}
                disabled={isLoading || dictation.isBusy}
                onChange={(event) => {
                  const enabled = event.target.checked
                  setAutoSendDictation(enabled)
                  autoSendDictationRef.current = enabled
                }}
              />
              {' '}Envoyer après la dictée
            </label>
          </div>
        </header>

        <section
          ref={scrollRef}
          className="conversation"
          aria-label="Conversation avec MIA"
          aria-live="polite"
          aria-busy={isLoading}
          onScroll={handleScroll}
        >
          {messages.length === 0 && !isLoading && (
            <div className="empty-state">
              <span className="orb" aria-hidden="true" />
              <h2>Bonjour, je suis MIA.</h2>
              <p>Sur quoi veux-tu avancer aujourd’hui ?</p>
            </div>
          )}

          {messages.map((message) => (
            <article
              key={message.id}
              className={`message message--${message.role}`}
            >
              <span className="message-author">
                {message.role === 'user' ? 'Toi' : 'MIA'}
              </span>

              {message.role === 'assistant' && message.status === 'streaming' && !message.content && (
                <p className="message-streaming" role="status">
                  MIA écrit…
                </p>
              )}

              {message.content &&
                (message.role === 'assistant' ? (
                  <div className="markdown">
                    <Markdown>{message.content}</Markdown>
                  </div>
                ) : (
                  <p>{message.content}</p>
                ))}
		              {message.role === 'assistant' &&
                message.content &&
                message.status !== 'streaming' &&
                message.status !== 'error' && (
                  <div className="message-voice-controls">
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => { void speakReply(message.content) }}
                    >
                      Écouter
                    </button>
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => {
                        if ('speechSynthesis' in window) {
                          window.speechSynthesis.cancel()
                        }
                      }}
                    >
                      Arrêter
                    </button>
                  </div>
                )}
              {message.taskProposal && (
                <TaskProposalCard
                  key={message.taskProposal.id}
                  proposal={message.taskProposal}
                  disabled={isLoading || dictation.isBusy}
                />
              )}
              {message.memoryProposal && (
                <MemoryProposalCard
                  key={message.memoryProposal.id}
                  proposal={message.memoryProposal}
                  disabled={isLoading || dictation.isBusy}
                />
              )}
              {message.role === 'assistant' && message.status === 'error' && (
                <p className="message-error">Réponse incomplète</p>
              )}
            </article>
          ))}
        </section>

        {showScrollButton && (
          <button
            type="button"
            className="secondary-button scroll-down-button"
            onClick={() => scrollToBottom(true)}
          >
            Revenir en bas
          </button>
        )}

        <footer className="composer">
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          <form onSubmit={handleSubmit}>
            <label className="sr-only" htmlFor="message">
              Ton message
            </label>

            <textarea
              id="message"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder={
                dictation.state === 'transcribing'
                  ? 'Transcription en cours…'
                  : dictation.state === 'requesting'
                    ? 'Autorisation du microphone en attente…'
                    : 'Écris à MIA…'
              }
              rows={3}
              maxLength={4000}
              disabled={isLoading || dictation.isBusy}
            />

            <button
              type="button"
              className={`mic-button ${dictation.isRecording ? 'mic-button--recording' : ''}`}
              onClick={
                dictation.isRecording
                  ? dictation.stopRecording
                  : dictation.startRecording
              }
              disabled={
                isLoading ||
                dictation.state === 'transcribing' ||
                dictation.state === 'requesting'
              }
              aria-label={
                dictation.isRecording
                  ? 'Arrêter l’enregistrement'
                  : 'Dicter un message'
              }
            >
              {dictation.isRecording ? 'Arrêter' : '🎤'}
              {dictation.isRecording && (
                <span className="recording-duration" aria-live="off">
                  {dictation.duration}s
                </span>
              )}
            </button>

            <button
              type="submit"
              disabled={isLoading || dictation.isBusy || !input.trim()}
            >
              {isLoading ? 'En cours…' : 'Envoyer'}
            </button>
          </form>

          {dictation.error && (
            <p className="error dictation-error" role="alert">
              {dictation.error}
              <button
                type="button"
                className="secondary-button dictation-dismiss"
                onClick={dictation.resetError}
              >
                Fermer
              </button>
            </p>
          )}

          <p className="footer-note">
            MIA peut se tromper. Vérifie les informations importantes.
          </p>
        </footer>
      </div>
    </main>
  )
}

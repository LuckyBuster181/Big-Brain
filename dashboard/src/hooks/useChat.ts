/** Verwaltet den Nachrichtenverlauf und das Senden von Fragen. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { askJarvis } from '../services/api'
import type { ChatMessage, HistoryMessage } from '../types/chat'

let idCounter = 0
const nextId = (): string => `msg-${++idCounter}`

/** Wie viele frühere Nachrichten mitgeschickt werden (Frage + Antwort = 2). */
const MAX_HISTORY_MESSAGES = 10

/**
 * Baut den Verlauf für das Backend. Fehlermeldungen gehören nicht dazu - die
 * hat Claude nie geschrieben. Das Backend kürzt zusätzlich selbst.
 */
function toHistory(messages: ChatMessage[]): HistoryMessage[] {
  return messages
    .filter((message) => !message.error)
    .slice(-MAX_HISTORY_MESSAGES)
    .map(({ role, content }) => ({ role, content }))
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)

  // Aktueller Stand für send(), ohne dass send() bei jeder Nachricht neu entsteht
  const messagesRef = useRef<ChatMessage[]>([])
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  const send = useCallback(async (text: string, topK: number): Promise<void> => {
    const question = text.trim()
    if (!question) return

    const history = toHistory(messagesRef.current)
    setMessages((prev) => [...prev, { id: nextId(), role: 'user', content: question }])
    setIsLoading(true)

    try {
      const response = await askJarvis({ message: question, top_k: topK, history })
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: 'assistant',
          content: response.answer,
          sources: response.sources,
          usedVault: response.used_vault,
        },
      ])
    } catch (error) {
      // Fehler landen als Nachricht im Verlauf statt in einem separaten Banner -
      // so bleibt sichtbar, welche Frage fehlgeschlagen ist.
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: 'assistant',
          content: error instanceof Error ? error.message : 'Unbekannter Fehler',
          error: true,
        },
      ])
    } finally {
      setIsLoading(false)
    }
  }, [])

  const reset = useCallback(() => setMessages([]), [])

  return { messages, isLoading, send, reset }
}

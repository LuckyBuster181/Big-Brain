/** Hauptansicht: Kopfzeile, Nachrichtenverlauf, Eingabe. */

import { useEffect, useRef, useState } from 'react'
import { useChat } from '../hooks/useChat'
import { useHealth } from '../hooks/useHealth'
import { useReindex } from '../hooks/useReindex'
import { ChatInput } from './ChatInput'
import { MessageBubble } from './MessageBubble'
import { ReindexButton } from './ReindexButton'
import { StatusBar } from './StatusBar'

const EXAMPLE_QUESTIONS = [
  'Was ist der aktuelle Stand des Jarvis-Projekts?',
  'Fasse zusammen, was ich zu Trading-Bots notiert habe.',
  'Welche offenen Punkte stehen in meinen Notizen?',
]

/** Startbildschirm, solange noch nichts gefragt wurde. */
function EmptyState({ onPick, disabled }: { onPick: (text: string) => void; disabled: boolean }) {
  return (
    <div className="empty">
      <h2>Was willst du wissen?</h2>
      <p>
        Jarvis durchsucht deinen Obsidian-Vault und antwortet mit Quellenangabe. Wenn nichts
        Passendes im Vault steht, sagt er das - statt sich etwas auszudenken. Rückfragen zur
        letzten Antwort versteht er auch.
      </p>
      <div className="examples">
        {EXAMPLE_QUESTIONS.map((question) => (
          <button
            key={question}
            type="button"
            className="example"
            onClick={() => onPick(question)}
            disabled={disabled}
          >
            {question}
          </button>
        ))}
      </div>
    </div>
  )
}

export function ChatView() {
  const { messages, isLoading, send, reset } = useChat()
  const { health, healthError, refresh } = useHealth()
  // Nach jedem Indexlauf die Chunk-Anzahl in der Statusanzeige aktualisieren
  const reindex = useReindex(refresh)
  const [topK, setTopK] = useState(5)
  const endRef = useRef<HTMLDivElement>(null)

  // Nach jeder neuen Nachricht ans Ende springen
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, isLoading])

  const handleSend = (text: string): void => {
    void send(text, topK)
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true">
            J
          </span>
          <div className="brand-text">
            <h1>Jarvis</h1>
            <p>Dein Big Brain, durchsuchbar</p>
          </div>
        </div>

        <div className="topbar-right">
          <label className="topk" title="Wie viele Vault-Ausschnitte als Kontext an Claude gehen">
            <span>Kontext</span>
            <select value={topK} onChange={(event) => setTopK(Number(event.target.value))}>
              {[3, 5, 8, 12].map((count) => (
                <option key={count} value={count}>
                  {count}
                </option>
              ))}
            </select>
          </label>

          <ReindexButton
            status={reindex.status}
            notice={reindex.notice}
            requestError={reindex.requestError}
            disabled={healthError !== null}
            onStart={(full) => {
              void reindex.start(full)
            }}
          />

          <StatusBar
            health={health}
            error={healthError}
            reindexing={reindex.running}
            onRetry={() => {
              void refresh()
              void reindex.refresh()
            }}
          />

          {messages.length > 0 && (
            <button type="button" className="ghost" onClick={reset} disabled={isLoading}>
              Neu
            </button>
          )}
        </div>
      </header>

      <main className="chat">
        <div className="chat-inner">
          {messages.length === 0 ? (
            <EmptyState onPick={handleSend} disabled={isLoading || healthError !== null} />
          ) : (
            messages.map((message) => <MessageBubble key={message.id} message={message} />)
          )}

          {isLoading && (
            <div className="message message-assistant">
              <div className="bubble bubble-thinking">
                <span className="dot-pulse" />
                <span className="dot-pulse" />
                <span className="dot-pulse" />
                <span className="thinking-text">durchsucht den Vault...</span>
              </div>
            </div>
          )}

          <div ref={endRef} />
        </div>
      </main>

      <footer className="composer-wrap">
        <div className="composer-inner">
          <ChatInput onSend={handleSend} disabled={isLoading} />
          <p className="hint">Enter senden · Shift+Enter neue Zeile</p>
        </div>
      </footer>
    </div>
  )
}

/** Eine einzelne Nachricht im Verlauf - Frage, Antwort oder Fehler. */

import ReactMarkdown from 'react-markdown'
import type { ChatMessage } from '../types/chat'
import { SourceList } from './SourceList'

interface Props {
  message: ChatMessage
}

export function MessageBubble({ message }: Props) {
  if (message.role === 'user') {
    return (
      <div className="message message-user">
        <div className="bubble">{message.content}</div>
      </div>
    )
  }

  if (message.error) {
    return (
      <div className="message message-assistant">
        <div className="bubble bubble-error">
          <strong className="error-title">Fehler</strong>
          <p className="error-text">{message.content}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="message message-assistant">
      <div className="bubble">
        {/*
          react-markdown rendert rohes HTML absichtlich nicht (kein rehype-raw
          eingebunden) - der Antworttext aus dem Vault kann also kein Markup
          einschleusen.
        */}
        <div className="markdown">
          <ReactMarkdown>{message.content}</ReactMarkdown>
        </div>

        {message.usedVault === false && (
          <p className="no-vault-hint">
            Ohne Vault-Treffer beantwortet - diese Antwort stützt sich nicht auf deine Notizen.
          </p>
        )}

        {message.sources && <SourceList sources={message.sources} />}
      </div>
    </div>
  )
}

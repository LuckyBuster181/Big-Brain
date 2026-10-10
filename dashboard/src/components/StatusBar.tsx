/** Kleine Statusanzeige oben rechts: läuft das Backend, ist der Vault indexiert? */

import type { HealthResponse } from '../types/chat'

interface Props {
  health: HealthResponse | null
  error: string | null
  /** Läuft gerade ein Indexlauf? Dann ist ein leerer Index kein Fehler, sondern "im Aufbau". */
  reindexing: boolean
  onRetry: () => void
}

export function StatusBar({ health, error, reindexing, onRetry }: Props) {
  if (error) {
    return (
      <div className="status status-offline" title={error}>
        <span className="status-dot" />
        <span>Backend offline</span>
        <button type="button" className="status-retry" onClick={onRetry}>
          erneut prüfen
        </button>
      </div>
    )
  }

  if (!health) {
    return (
      <div className="status status-pending">
        <span className="status-dot" />
        <span>verbinde...</span>
      </div>
    )
  }

  const model = health.embedding_model ? `Embedding-Modell: ${health.embedding_model}` : ''

  if (!health.vault_indexed) {
    if (reindexing) {
      return (
        <div className="status status-pending" title={`Der Index wird gerade aufgebaut. ${model}`}>
          <span className="status-dot" />
          <span>Index im Aufbau</span>
        </div>
      )
    }
    return (
      <div className="status status-warn" title="Knopf „Vault einlesen“ drücken">
        <span className="status-dot" />
        <span>Vault nicht indexiert</span>
      </div>
    )
  }

  return (
    <div className="status status-online" title={`Backend erreichbar, Vault indexiert. ${model}`}>
      <span className="status-dot" />
      <span>{(health.chunk_count ?? 0).toLocaleString('de-DE')} Chunks</span>
    </div>
  )
}

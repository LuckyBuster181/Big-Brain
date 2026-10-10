/**
 * Knopf "Vault einlesen" in der Kopfzeile.
 * Klick: nur geänderte Notizen neu einlesen (dauert meist Sekunden).
 * Shift+Klick: Index komplett neu aufbauen.
 */

import type { MouseEvent } from 'react'
import type { ReindexNotice } from '../hooks/useReindex'
import type { ReindexStatus } from '../types/chat'

interface Props {
  status: ReindexStatus | null
  notice: ReindexNotice | null
  requestError: string | null
  disabled: boolean
  onStart: (full: boolean) => void
}

/** "Wissen/04 - Trading/08 - Backtesting.md" -> "08 - Backtesting" */
function shortName(path: string | null | undefined): string {
  if (!path) return ''
  return (path.split(/[/\\]/).pop() ?? path).replace(/\.md$/i, '')
}

function tooltip(status: ReindexStatus | null): string {
  const lines = ['Geänderte Notizen neu einlesen', 'Shift+Klick: Index komplett neu aufbauen']
  const result = status?.last_result
  if (result && status?.finished_at) {
    const time = new Date(status.finished_at).toLocaleTimeString('de-DE', {
      hour: '2-digit',
      minute: '2-digit',
    })
    lines.push(
      '',
      `Letzter Lauf ${time} (${result.duration_s.toLocaleString('de-DE')} s, Modell ${result.model}):`,
      `${result.files_new} neu, ${result.files_changed} geändert, ${result.files_removed} entfernt, ` +
        `${result.files_unchanged} unverändert`,
      `${result.collection_count.toLocaleString('de-DE')} Chunks im Index`,
    )
  }
  if (status?.error) lines.push('', `Fehler: ${status.error}`)
  return lines.join('\n')
}

export function ReindexButton({ status, notice, requestError, disabled, onStart }: Props) {
  if (status?.running) {
    const progress = status.progress
    const label = progress ? `${progress.done}/${progress.total}` : ''
    return (
      <div
        className="reindex reindex-running"
        title={progress?.current_file ? `Aktuell: ${shortName(progress.current_file)}` : 'Vault wird geprüft'}
      >
        <span className="spinner spinner-sm" aria-hidden="true" />
        <span>{status.full ? 'Baue Index neu' : 'Lese Vault ein'}</span>
        {label && <span className="reindex-count">{label}</span>}
      </div>
    )
  }

  function handleClick(event: MouseEvent<HTMLButtonElement>): void {
    onStart(event.shiftKey)
  }

  return (
    <div className="reindex">
      <button
        type="button"
        className="ghost"
        onClick={handleClick}
        disabled={disabled}
        title={requestError ?? tooltip(status)}
      >
        Vault einlesen
      </button>
      {notice && (
        <span className={`reindex-notice${notice.error ? ' is-error' : ''}`} title={notice.text}>
          {notice.text}
        </span>
      )}
    </div>
  )
}

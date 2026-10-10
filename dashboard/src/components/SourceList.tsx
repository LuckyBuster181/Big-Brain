/** Aufklappbare Liste der Vault-Ausschnitte, auf die sich eine Antwort stützt. */

import { useState } from 'react'
import type { Source } from '../types/chat'

interface Props {
  sources: Source[]
}

/** "Wissen/03 - KI/05 - Jarvis Anweisung.md" -> "05 - Jarvis Anweisung" */
function fileName(path: string): string {
  const last = path.split(/[/\\]/).pop() ?? path
  return last.replace(/\.md$/i, '')
}

/** Ordnerpfad ohne Dateinamen, für die Zeile unter dem Titel. */
function folder(path: string): string {
  const parts = path.split(/[/\\]/)
  parts.pop()
  return parts.join(' / ')
}

export function SourceList({ sources }: Props) {
  const [open, setOpen] = useState(false)

  if (sources.length === 0) return null

  // Die Scores sind absolute Ähnlichkeitswerte und liegen typisch bei 0.05-0.3.
  // Für den Balken wird deshalb relativ zum besten Treffer skaliert, sonst
  // sähe jede Quelle nach "fast nichts" aus.
  const best = Math.max(...sources.map((s) => s.score), 0.0001)

  return (
    <div className="sources">
      <button
        type="button"
        className="sources-toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className={`chevron${open ? ' is-open' : ''}`} aria-hidden="true">
          ▸
        </span>
        {sources.length} {sources.length === 1 ? 'Quelle' : 'Quellen'} aus dem Vault
      </button>

      {open && (
        <ol className="source-list">
          {sources.map((source, index) => (
            <li key={`${source.file_path}-${source.heading_path}-${index}`} className="source">
              <div className="source-head">
                <span className="source-index">[{index + 1}]</span>
                <span className="source-title" title={source.file_path}>
                  {fileName(source.file_path)}
                </span>
                <span className="source-score" title="Relevanz-Score des Retrievers">
                  {source.score.toFixed(3)}
                </span>
              </div>
              <div className="source-path">{folder(source.file_path)}</div>
              <div className="source-heading">{source.heading_path}</div>
              <div
                className="score-bar"
                title="Balkenlänge relativ zum besten Treffer dieser Antwort"
              >
                <div className="score-fill" style={{ width: `${(source.score / best) * 100}%` }} />
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

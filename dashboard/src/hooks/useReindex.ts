/**
 * Neu-Einlesen des Vaults: starten, Fortschritt abfragen, Ergebnis kurz anzeigen.
 *
 * Das Backend liest beim Start und über die Vault-Überwachung (Watcher) selbst
 * geänderte Notizen ein. Deshalb fragt das Dashboard den Status auch ohne
 * Knopfdruck ab: beim Laden der Seite und danach alle 15 Sekunden, solange der
 * Tab sichtbar ist. Läuft ein Lauf, jede Sekunde. Ein Lauf, der zwischen zwei
 * Abfragen begonnen und geendet hat, wird am neuen finished_at erkannt.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { getReindexStatus, startReindex } from '../services/api'
import type { ReindexStatus } from '../types/chat'

const POLL_INTERVAL_MS = 1000
/** Abfrage im Leerlauf, damit Läufe des Watchers ohne Neuladen sichtbar werden */
const IDLE_POLL_INTERVAL_MS = 15000
const NOTICE_DURATION_MS = 8000

export interface ReindexNotice {
  text: string
  error: boolean
}

function describe(status: ReindexStatus): ReindexNotice {
  if (status.error) return { text: `Einlesen fehlgeschlagen: ${status.error}`, error: true }
  const result = status.last_result
  if (!result) return { text: 'Einlesen beendet', error: false }
  if (result.files_indexed === 0 && result.files_removed === 0) {
    return { text: 'Index ist aktuell', error: false }
  }
  const parts: string[] = []
  if (result.files_new) parts.push(`${result.files_new} neu`)
  if (result.files_changed) parts.push(`${result.files_changed} geändert`)
  if (result.files_removed) parts.push(`${result.files_removed} entfernt`)
  return { text: `Notizen: ${parts.join(', ')}`, error: false }
}

export function useReindex(onFinished?: () => void) {
  const [status, setStatus] = useState<ReindexStatus | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [notice, setNotice] = useState<ReindexNotice | null>(null)

  const wasRunning = useRef(false)
  /** finished_at des zuletzt gesehenen Laufs; undefined = noch nichts abgefragt */
  const lastFinishedAt = useRef<string | null | undefined>(undefined)
  const noticeTimer = useRef<number | undefined>(undefined)
  const onFinishedRef = useRef(onFinished)
  useEffect(() => {
    onFinishedRef.current = onFinished
  }, [onFinished])

  const apply = useCallback((next: ReindexStatus): void => {
    // Beendet: entweder beim Laufen beobachtet, oder zwischen zwei Abfragen im
    // Leerlauf gestartet und fertig geworden (neues finished_at)
    const finishedUnseen =
      lastFinishedAt.current !== undefined &&
      next.finished_at !== null &&
      next.finished_at !== lastFinishedAt.current
    if (!next.running && (wasRunning.current || finishedUnseen)) {
      window.clearTimeout(noticeTimer.current)
      setNotice(describe(next))
      noticeTimer.current = window.setTimeout(() => setNotice(null), NOTICE_DURATION_MS)
      onFinishedRef.current?.()
    }
    wasRunning.current = next.running
    lastFinishedAt.current = next.finished_at
    setStatus(next)
    setRequestError(null)
  }, [])

  const refresh = useCallback(async (): Promise<void> => {
    try {
      apply(await getReindexStatus())
    } catch (error) {
      // Backend weg: Polling endet, weil sich status nicht mehr ändert
      wasRunning.current = false
      setStatus(null)
      setRequestError(error instanceof Error ? error.message : 'Unbekannter Fehler')
    }
  }, [apply])

  const start = useCallback(
    async (full: boolean): Promise<void> => {
      try {
        apply(await startReindex(full))
      } catch (error) {
        setRequestError(error instanceof Error ? error.message : 'Unbekannter Fehler')
      }
    },
    [apply],
  )

  // Beim Laden einmal nachsehen, ob das Backend gerade selbst einliest
  useEffect(() => {
    void refresh()
    return () => window.clearTimeout(noticeTimer.current)
  }, [refresh])

  // Solange ein Lauf aktiv ist, jede Sekunde den Fortschritt holen.
  // Im Leerlauf alle 15 s nachsehen, ob der Watcher einen Lauf gestartet hat
  // (nur bei sichtbarem Tab, sonst beim nächsten Sichtbarwerden).
  useEffect(() => {
    const running = status?.running ?? false
    const timer = window.setTimeout(
      () => {
        if (running || document.visibilityState === 'visible') void refresh()
      },
      running ? POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS,
    )
    return () => window.clearTimeout(timer)
  }, [status, requestError, refresh])

  // Tab wieder sichtbar: sofort nachsehen statt bis zu 15 s zu warten
  useEffect(() => {
    function onVisible(): void {
      if (document.visibilityState === 'visible') void refresh()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [refresh])

  return { status, running: status?.running ?? false, requestError, notice, start, refresh }
}

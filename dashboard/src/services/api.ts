/** HTTP-Zugriff auf das Auron-Backend. */

import axios, { type AxiosError } from 'axios'
import type { ChatRequest, ChatResponse, HealthResponse, ReindexStatus } from '../types/chat'

/**
 * Backend-Adresse.
 *
 * Standard ist ein leerer String: die Anfragen gehen dann an dieselbe Adresse
 * wie das Frontend (localhost:5173) und werden vom Vite-Proxy ans Backend
 * weitergereicht - siehe server.proxy in vite.config.ts. Das spart CORS.
 *
 * Direkt aufs Backend zeigen (z.B. für einen Produktions-Build) geht über eine
 * .env-Datei im dashboard-Ordner:
 *   VITE_API_URL=http://192.168.1.50:8000
 */
export const BASE_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

/** Nur für Fehlermeldungen: die Adresse, die der Nutzer prüfen soll. */
const BACKEND_HINT = BASE_URL || 'localhost:8000 (über den Vite-Proxy)'

const client = axios.create({
  baseURL: BASE_URL,
  // Claude braucht mit viel Vault-Kontext auch mal 30-60 Sekunden
  timeout: 120_000,
  headers: { 'Content-Type': 'application/json' },
})

/** Übersetzt Axios-Fehler in eine Meldung, die im UI etwas taugt. */
function toReadableError(error: unknown): Error {
  if (axios.isAxiosError(error)) {
    const err = error as AxiosError<{ detail?: string }>

    const offlineHint =
      `Backend nicht erreichbar (${BACKEND_HINT}). Läuft der Server? ` +
      'Start im backend-Ordner: python -m uvicorn main:app --reload --port 8000'

    if (err.code === 'ERR_NETWORK') return new Error(offlineHint)

    if (err.code === 'ECONNABORTED') {
      return new Error('Zeitüberschreitung - das Backend hat länger als 2 Minuten gebraucht.')
    }

    // FastAPI packt Fehlertexte (auch HTTPException) in das Feld "detail"
    const detail = err.response?.data?.detail
    if (detail) return new Error(detail)

    if (err.response) {
      // Läuft das Backend nicht, kann der Vite-Proxy nicht weiterleiten und
      // antwortet selbst mit 500/504 - ohne "detail"-Feld. Sieht für axios wie
      // ein Serverfehler aus, ist aber in Wahrheit "Backend aus".
      if (err.response.status === 500 || err.response.status === 504) return new Error(offlineHint)

      return new Error(`Backend antwortete mit ${err.response.status} ${err.response.statusText}`)
    }
  }

  return error instanceof Error ? error : new Error('Unbekannter Fehler')
}

/** Stellt eine Frage an Auron (RAG-Suche im Vault + Claude-Antwort). */
export async function askJarvis(request: ChatRequest): Promise<ChatResponse> {
  try {
    const { data } = await client.post<ChatResponse>('/api/chat', {
      top_k: 5,
      ...request,
    })
    return data
  } catch (error) {
    throw toReadableError(error)
  }
}

/** Prüft, ob das Backend läuft und der Vault indexiert ist. */
export async function checkHealth(): Promise<HealthResponse> {
  try {
    const { data } = await client.get<HealthResponse>('/api/health')
    return data
  } catch (error) {
    throw toReadableError(error)
  }
}

/**
 * Startet das Neu-Einlesen des Vaults im Hintergrund.
 * full=false: nur geänderte Notizen (Sekunden). full=true: kompletter Neuaufbau.
 * Läuft schon ein Lauf, kommt dessen Status zurück - es startet kein zweiter.
 */
export async function startReindex(full = false): Promise<ReindexStatus> {
  try {
    const { data } = await client.post<ReindexStatus>('/api/reindex', null, { params: { full } })
    return data
  } catch (error) {
    throw toReadableError(error)
  }
}

/** Fortschritt bzw. Ergebnis des letzten Indexlaufs. */
export async function getReindexStatus(): Promise<ReindexStatus> {
  try {
    const { data } = await client.get<ReindexStatus>('/api/reindex/status')
    return data
  } catch (error) {
    throw toReadableError(error)
  }
}

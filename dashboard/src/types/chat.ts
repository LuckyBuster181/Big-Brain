/**
 * Typen für die Backend-Kommunikation.
 *
 * Spiegelt die Pydantic-Schemas aus backend/app/schemas.py wider - wenn dort
 * etwas geändert wird, muss es hier mitgezogen werden.
 */

/** Ein Vault-Ausschnitt, der als Quelle für die Antwort gedient hat. */
export interface Source {
  file_path: string
  heading_path: string
  score: number
}

/** Frühere Nachricht im Gespräch - damit versteht Jarvis Rückfragen. */
export interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatRequest {
  message: string
  /** Anzahl der Vault-Ausschnitte, die als Kontext an Claude gehen (1-20). */
  top_k?: number
  /** Optionaler Filter auf das Frontmatter-Feld "status" (z.B. nur "bestätigt"). */
  status?: string | null
  /** Bisheriger Verlauf, älteste Nachricht zuerst, ohne die aktuelle Frage. */
  history?: HistoryMessage[]
}

export interface ChatResponse {
  answer: string
  sources: Source[]
  /** False, wenn der Retriever nichts gefunden hat - Antwort kam dann ohne Vault-Kontext. */
  used_vault: boolean
}

export interface HealthResponse {
  status: string
  vault_indexed: boolean
  chunk_count: number | null
  /** Kurzname des Embedding-Modells, z.B. "e5-base". */
  embedding_model?: string | null
  reindex_running?: boolean
}

/** Ergebnis eines Indexlaufs (siehe build_index in backend/rag/embeddings.py). */
export interface ReindexResult {
  model: string
  full: boolean
  files_total: number
  files_indexed: number
  files_new: number
  files_changed: number
  files_removed: number
  files_unchanged: number
  files_empty: number
  chunks_written: number
  collection_count: number
  duration_s: number
}

export interface ReindexProgress {
  done: number
  total: number
  current_file: string | null
}

export interface ReindexStatus {
  running: boolean
  full: boolean
  started_at: string | null
  finished_at: string | null
  progress: ReindexProgress | null
  last_result: ReindexResult | null
  error: string | null
}

/**
 * Eine Nachricht im Verlauf. Das Backend speichert nichts - der Verlauf wird
 * bei jeder Frage als `history` mitgeschickt.
 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  usedVault?: boolean
  /** True, wenn die "Antwort" in Wahrheit eine Fehlermeldung ist. */
  error?: boolean
}

/** Fragt beim Start (und auf Knopfdruck) den Backend-Status ab. */

import { useCallback, useEffect, useState } from 'react'
import { checkHealth } from '../services/api'
import type { HealthResponse } from '../types/chat'

export function useHealth() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)

  const refresh = useCallback(async (): Promise<void> => {
    try {
      setHealth(await checkHealth())
      setHealthError(null)
    } catch (error) {
      setHealth(null)
      setHealthError(error instanceof Error ? error.message : 'Unbekannter Fehler')
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return { health, healthError, refresh }
}

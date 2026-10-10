/** Eingabefeld: Enter sendet, Shift+Enter macht eine neue Zeile. */

import { useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react'

interface Props {
  onSend: (text: string) => void
  disabled: boolean
}

const MAX_HEIGHT_PX = 200

export function ChatInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  function autoGrow(element: HTMLTextAreaElement): void {
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT_PX)}px`
  }

  function submit(): void {
    if (disabled || !value.trim()) return
    onSend(value)
    setValue('')
    // Ohne Reset bliebe das Feld nach einer langen Frage aufgebläht stehen
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  function handleChange(event: ChangeEvent<HTMLTextAreaElement>): void {
    setValue(event.target.value)
    autoGrow(event.target)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className="composer">
      <textarea
        ref={textareaRef}
        className="composer-input"
        value={value}
        rows={1}
        placeholder="Frag dein Big Brain..."
        onChange={handleChange}
        onKeyDown={handleKeyDown}
      />
      <button
        type="button"
        className="composer-send"
        onClick={submit}
        disabled={disabled || !value.trim()}
        title="Senden (Enter)"
      >
        {disabled ? <span className="spinner" aria-label="Lädt" /> : 'Senden'}
      </button>
    </div>
  )
}

/* The question mark that sits beside a field and explains it in plain words.

   A popover rather than a browser tooltip: a `title=` attribute waits a second, cannot be read on a
   touchscreen, and vanishes the moment the pointer moves — none of which suits an explanation someone
   is trying to read. This one opens on click and stays until it is closed.

   The words themselves are in helpText.ts, never here. */

import { useEffect, useRef, useState } from 'react'

import Icon from './Icon'
import { HELP } from './helpText'

export default function Help({ topic, align = 'left' }: { topic: keyof typeof HELP; align?: 'left' | 'right' }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLSpanElement | null>(null)
  const t = HELP[topic]

  // Clicking anywhere else, or pressing Escape, puts it away — the two things everyone tries first.
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    const key = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', key)
    }
  }, [open])

  return (
    <span className="help" ref={box}>
      <button
        type="button"
        className="help-btn"
        aria-expanded={open}
        aria-label={`What is "${t.title}"?`}
        onClick={(e) => {
          e.preventDefault() // the icon often sits inside a <label>, which would otherwise focus the field
          setOpen((v) => !v)
        }}
      >
        <Icon name="help" size={12} width={2.2} />
      </button>
      {open && (
        <span className={`help-pop help-pop-${align}`} role="dialog" aria-label={t.title}>
          <b className="grot">{t.title}</b>
          {t.body.map((line, i) => (
            <span key={i}>{line}</span>
          ))}
        </span>
      )}
    </span>
  )
}

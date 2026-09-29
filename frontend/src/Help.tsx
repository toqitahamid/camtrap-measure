/* The question mark that sits beside a field and explains it in plain words, and the About panel in the
   header, which opens the same way.

   A popover rather than a browser tooltip: a `title=` attribute waits a second, cannot be read on a
   touchscreen, and vanishes the moment the pointer moves. None of that suits an explanation someone
   is trying to read. This one opens on click and stays until it is closed.

   The words themselves are in helpText.ts, never here. */

import { useEffect, useRef, useState, type ReactNode } from 'react'

import Icon from './Icon'
import { HELP } from './helpText'

/** Open state for a popover that clicking elsewhere, or pressing Escape, puts away: the two things everyone tries first. */
function usePopover() {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLSpanElement | null>(null)
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
  return { open, setOpen, box }
}

export default function Help({ topic, align = 'left' }: { topic: keyof typeof HELP; align?: 'left' | 'right' }) {
  const { open, setOpen, box } = usePopover()
  const t = HELP[topic]

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

/** The header's About button: a small panel of name and value pairs, for the details nobody acts on day to day. */
export function About({ rows }: { rows: [string, ReactNode][] }) {
  const { open, setOpen, box } = usePopover()
  return (
    <span className="help" ref={box}>
      <button type="button" className="btn btn-sm" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        About
      </button>
      {open && (
        <span className="help-pop help-pop-right" role="dialog" aria-label="About" style={{ top: 30, width: 380 }}>
          <b className="grot">CamTrap Measure</b>
          <span className="kv">
            {rows.map(([k, v]) => [
              <span key={`${k}-k`} className="dim">{k}</span>,
              <span key={`${k}-v`} style={{ overflowWrap: 'anywhere' }}>{v}</span>,
            ])}
          </span>
        </span>
      )}
    </span>
  )
}

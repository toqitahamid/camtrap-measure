/* The question mark that sits beside a field and explains it in plain words, and the About panel in the
   header, which opens the same way.

   A popover rather than a browser tooltip: a `title=` attribute waits a second, cannot be read on a
   touchscreen, and vanishes the moment the pointer moves. None of that suits an explanation someone
   is trying to read. This one opens on click and stays until it is closed.

   The words themselves are in helpText.ts, never here. */

import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'

import Icon from './Icon'
import { HELP } from './helpText'

/** Open state for a popover that clicking elsewhere, or pressing Escape, puts away: the two things everyone tries first.

    The popover is placed against the window (position: fixed), not inside the panel it was opened from: a
    panel that scrolls clips whatever pokes out of it, which cut the Density screen's help off at the right
    edge (2026-09-29). It flips above its icon when there is no room below, and closes when anything scrolls,
    because it would no longer sit beside its icon. */
function usePopover(align: 'left' | 'right') {
  const [open, setOpen] = useState(false)
  const [place, setPlace] = useState<CSSProperties | null>(null)
  const box = useRef<HTMLSpanElement | null>(null)
  const pop = useRef<HTMLSpanElement | null>(null)
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    const key = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    const moved = (e: Event) => {
      if (!pop.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', key)
    window.addEventListener('scroll', moved, true)
    window.addEventListener('resize', moved)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', key)
      window.removeEventListener('scroll', moved, true)
      window.removeEventListener('resize', moved)
    }
  }, [open])
  useLayoutEffect(() => {
    // Runs before the browser paints, so the popover never shows where it was last time.
    if (!open || !box.current || !pop.current) return
    const b = box.current.getBoundingClientRect()
    const p = pop.current.getBoundingClientRect()
    const edge = 8
    const want = align === 'right' ? b.right + 6 - p.width : b.left - 6
    const left = Math.max(edge, Math.min(want, window.innerWidth - p.width - edge))
    const below = b.bottom + 6
    const top = below + p.height <= window.innerHeight - edge ? below : Math.max(edge, b.top - 6 - p.height)
    setPlace({ position: 'fixed', left, top, right: 'auto' })
  }, [open, align])
  // Drawn once out of sight to be measured, then shown where it fits.
  const style: CSSProperties = place ?? { position: 'fixed', left: 0, top: 0, visibility: 'hidden' }
  return { open, setOpen, box, pop, style }
}

export default function Help({ topic, align = 'left' }: { topic: keyof typeof HELP; align?: 'left' | 'right' }) {
  const { open, setOpen, box, pop, style } = usePopover(align)
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
        <span ref={pop} className="help-pop" style={style} role="dialog" aria-label={t.title}>
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
  const { open, setOpen, box, pop, style } = usePopover('right')
  return (
    <span className="help" ref={box}>
      <button type="button" className="btn btn-sm" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        About
      </button>
      {open && (
        <span ref={pop} className="help-pop" role="dialog" aria-label="About" style={{ ...style, width: 380 }}>
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

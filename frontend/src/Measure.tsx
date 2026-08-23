/* MEASURE — the folder as a list, one frame at a time, and the number the run read from it.
   The shell owns the bars, the run and the folder listing; this section only renders what
   /api/folder returned and asks for the photos the user picked to be measured. */

import Icon from './Icon'
import { useEffect, useRef, useState } from 'react'
import {
  STATE_LABEL,
  band,
  clock,
  flagSrc,
  lead,
  metres,
  photoSrc,
  plural,
  stamp,
  state,
  type Det,
  type Folder,
  type Methods,
  type Row,
  type Scope,
  type State,
} from './ui'

type View = 'all' | 'new' | 'flagged'

const VIEWS: { key: View; label: string; keep: (r: Row) => boolean }[] = [
  { key: 'all', label: 'All', keep: () => true },
  { key: 'new', label: 'Not measured', keep: (r) => !r.measured },
  { key: 'flagged', label: 'Needs a look', keep: (r) => state(r) === 'flagged' },
]

/** The mark at the right of a list row: the one glance that says what happened to this photo. */
const DOT: Record<State, string> = {
  clean: 'var(--ok)',
  flagged: 'var(--bad)',
  empty: 'var(--edge)',
  new: 'var(--info)',
  stale: 'var(--dim)',
}

/** The second line of a list row: the time, plus whatever the reviewer needs to know about it. */
function note(r: Row): string {
  const time = clock(r.captured_at)
  switch (state(r)) {
    case 'flagged':
      return r.reasons.join('; ')
    case 'empty':
      return `${time} · no animal`
    case 'new':
      return `${time} · not measured`
    case 'stale':
      return `${time} · answer out of date`
    default:
      return time
  }
}

/* The ruler runs 0–25 m: past that a camera-trap distance is guesswork anyway. */
const SCALE_M = 25
const pct = (m: number) => Math.min(100, Math.max(0, (m / SCALE_M) * 100))
const interval = (d: Det) => (d.q05_m === null || d.q95_m === null ? '—' : `${band(d)} m`)

export default function Measure({
  scope,
  folder,
  methods,
  busy,
  running,
  onMeasure,
  focus,
  error,
}: {
  scope: Scope
  folder: Folder | null
  methods: Methods
  busy: boolean
  running: boolean // a run is actually in flight; `busy` is also true while the models load
  onMeasure: (paths: string[]) => void
  // ponytail: optional because the ticket's signature stops above — the shell hands these over when the table
  // opens a row here, and when the folder listing itself failed. Omitting them changes nothing.
  focus?: string | null
  error?: string | null
}) {
  const [path, setPath] = useState<string | null>(null)
  const [view, setView] = useState<View>('all')
  const [showFlag, setShowFlag] = useState(false)
  const [showBoxes, setShowBoxes] = useState(true)
  const [hot, setHot] = useState<number | null>(null)

  // scroll the selected row into view when the SELECTION moves, not on every render: a run polls once a
  // second, and re-scrolling then would drag a reviewer who is reading ahead back up the list
  const seen = useRef<HTMLDivElement | null>(null) // the animal the pointer is on, in the frame or in the panel

  const rows = folder?.rows ?? []
  const list = rows.filter(VIEWS.find((v) => v.key === view)?.keep ?? (() => true))
  // selection is a path, not an index: a run reloads the listing and the same photo must stay put
  const at = Math.max(0, list.findIndex((r) => r.path === path))
  const cur: Row | undefined = list[at]
  useEffect(() => {
    seen.current?.scrollIntoView({ block: 'nearest' })
  }, [cur?.path])
  const methodLabel = (m: string | null) => (m ? (methods.methods[m]?.label ?? m) : '—')

  const go = (r: Row) => {
    setPath(r.path)
    setHot(null)
  }
  const step = (d: number) => {
    // no useCallback: the compiler memoizes `list`, so the key handler below re-binds only when it changes
    const next = list[Math.min(list.length - 1, Math.max(0, at + d))]
    if (next) go(next)
  }
  useEffect(() => {
    // arrow keys are how a reviewer walks a folder; typing in a field still wins
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return
      const d = e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 0
      if (!d) return
      e.preventDefault()
      step(d)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list, at])

  useEffect(() => {
    // another section pointed at one photo: show it whatever filter the list was left on
    if (!focus) return
    setPath(focus)
    setView('all')
    setHot(null)
  }, [focus])

  const st = cur ? state(cur) : null
  const best = cur ? lead(cur) : null
  const against = cur ? (cur.flag_image ?? scope.flag) : scope.flag
  const boxes = cur && !showFlag && showBoxes ? cur.detections : []
  const pos = (n: number) => String(n).padStart(String(list.length).length, '0')

  return (
    <>
      {/* ── Photo list ───────────────────────────────────────────── */}
      <div className="pane pane-l" style={{ width: 288, flex: 'none' }}>
        <div className="pane-head">
          <span className="cap">Photos</span>
          <span className="mono tiny faint">{rows.length}</span>
        </div>
        {rows.length > 0 && (
          <div className="row" style={{ gap: 3, padding: '8px 11px', borderBottom: '1px solid var(--hair)' }}>
            {VIEWS.map((v) => (
              <button key={v.key} className="chip" aria-pressed={view === v.key} onClick={() => setView(v.key)}>
                {v.label} {rows.filter(v.keep).length}
              </button>
            ))}
          </div>
        )}
        {error ? (
          <div className="empty">
            <p className="notice notice-error">{error}</p>
          </div>
        ) : folder === null ? (
          <div className="empty">
            <p className="dim small">No folder chosen yet. Pick the folder of camera-trap photos in the bar above.</p>
          </div>
        ) : rows.length === 0 ? (
          <div className="empty">
            <p className="dim small">
              No JPEGs in this folder.
              {folder.unreadable > 0 && ` ${plural(folder.unreadable, 'file')} here could not be read.`}
            </p>
          </div>
        ) : list.length === 0 ? (
          <div className="empty">
            <p className="dim small">No photo is {view === 'new' ? 'still unmeasured' : 'flagged for a look'} — every one of the {rows.length} is fine.</p>
            <button className="btn btn-sm" onClick={() => setView('all')}>Show all {rows.length}</button>
          </div>
        ) : (
          <div className="scroll">
            {list.map((r) => {
              const sel = r.path === cur?.path
              const rst = state(r)
              const d = lead(r)
              // a div, not a button: the row holds a button of its own, and a button inside a button is
              // invalid HTML. Same shape the table's rows use, so both lists behave alike.
              return (
                <div
                  key={r.path}
                  className="item"
                  role="button"
                  tabIndex={0}
                  aria-current={sel}
                  onClick={() => go(r)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      go(r)
                    }
                  }}
                  ref={sel ? seen : undefined}
                >
                  <img className="thumb" src={photoSrc(r.path, 'thumb')} alt="" loading="lazy" />
                  <span className="item-text">
                    <span className="mono small">{r.name}</span>
                    <span className={`tiny ${rst === 'flagged' ? 'warn' : 'faint'}`}>{note(r)}</span>
                  </span>
                  {/* measuring one photo has to be one click, so the button lives in the row and
                      stopPropagation keeps it from also selecting */}
                  {!r.measured ? (
                    <button
                      type="button"
                      className={`btn btn-sm${sel ? ' btn-amber' : ''}`}
                      title="Measure just this photo"
                      disabled={busy}
                      onClick={(e) => {
                        e.stopPropagation()
                        onMeasure([r.path])
                      }}
                    >
                      Measure
                    </button>
                  ) : (
                    d && <span className="grot" style={{ fontWeight: 600 }}>{metres(d)}</span>
                  )}
                  <span className="dot" style={{ color: DOT[rst] }} />
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* ── Viewer ───────────────────────────────────────────────── */}
      <div className="viewer">
        {!cur ? (
          <div className="stage">
            <p className="dim small">{folder === null ? 'Choose a folder to see its photos here.' : 'Nothing to show.'}</p>
          </div>
        ) : (
          <>
            <div className="pane-head" style={{ background: 'var(--pane)' }}>
              <span className="mono small">{cur.name}</span>
              <span className="small faint">{stamp(cur.captured_at)}</span>
              <div className="spacer" />
              <button
                className="btn btn-sm"
                aria-pressed={showFlag}
                disabled={!against}
                title="Show the frame every distance in this photo is read against"
                style={{ color: showFlag ? 'var(--amber)' : undefined }}
                onClick={() => setShowFlag((f) => !f)}
              >
                <Icon name="flag" size={12} />
                Flag photo
              </button>
              <button
                className="btn btn-sm"
                aria-pressed={showBoxes}
                disabled={showFlag}
                style={{ color: showBoxes && !showFlag ? 'var(--amber)' : undefined }}
                onClick={() => setShowBoxes((b) => !b)}
              >
                <Icon name="table" size={12} />
                Boxes
              </button>
              <span className="mono tiny faint">{pos(at + 1)} / {pos(list.length)}</span>
              <button className="btn btn-sm btn-icon" aria-label="Previous photo (left arrow)" disabled={at === 0} onClick={() => step(-1)}>
                <Icon name="left" size={13} width={2.3} />
              </button>
              <button className="btn btn-sm btn-icon" aria-label="Next photo (right arrow)" disabled={at === list.length - 1} onClick={() => step(1)}>
                <Icon name="right" size={13} width={2.3} />
              </button>
            </div>
            <div className="stage">
              <div className="frame">
                <img src={showFlag ? flagSrc(scope.site, against) : photoSrc(cur.path, 'full')} alt={cur.name} />
                {boxes.map((d, i) => (
                  <div
                    key={`${d.method}-${d.idx}`}
                    className={`bbox${d.reasons.length ? ' bbox-flagged' : ''}${hot === i ? ' bbox-hot' : ''}${d.y1 < 0.08 ? ' bbox-low' : ''}`}
                    style={{
                      left: `${d.x1 * 100}%`,
                      top: `${d.y1 * 100}%`,
                      width: `${(d.x2 - d.x1) * 100}%`,
                      height: `${(d.y2 - d.y1) * 100}%`,
                    }}
                    onMouseEnter={() => setHot(i)}
                    onMouseLeave={() => setHot(null)}
                  >
                    <span className="tag">{i + 1} · {d.species} · {metres(d)}</span>
                    {/* the dashed line sits where the ground was read — the distance is that line's, not the box's */}
                    <span className="foot" />
                  </div>
                ))}
                {showFlag && <span className="frame-note">Flag photo {against} — every distance is read against this frame</span>}
              </div>
            </div>
          </>
        )}
      </div>

      {/* ── Measurement ──────────────────────────────────────────── */}
      <div className="pane pane-r" style={{ width: 336, flex: 'none' }}>
        <div className="pane-head">
          <span className="cap">Measurement</span>
          <div className="spacer" />
          {st && (
            running && !cur?.measured ? (
              <span className="pill pill-running"><span className="dot" /> Running</span>
            ) : (
              <span className={`pill pill-${st}`}><span className="dot" /> {STATE_LABEL[st]}</span>
            )
          )}
        </div>

        {!cur ? (
          <div className="empty">
            <p className="dim small">
              {folder === null
                ? 'Nothing is measured yet. Pick a camera, a flag photo and a folder in the bar above.'
                : 'Select a photo on the left to see its measurement.'}
            </p>
          </div>
        ) : running && !cur.measured ? (
          /* a run is in flight and this photo has no number: it is being measured or is waiting its turn */
          <div className="empty">
            <span className="spin" style={{ color: 'var(--amber)' }}><Icon name="spinner" size={30} width={1.8} /></span>
            <div className="grot" style={{ fontSize: 14, fontWeight: 600 }}>Measuring…</div>
            <p className="dim small" style={{ lineHeight: 1.55 }}>
              Detecting animals, then aligning the frame to <span className="mono">{against}</span> to read the ground distance.
              Distances appear here as each photo finishes.
            </p>
          </div>
        ) : !cur.measured ? (
          <div className="empty">
            <span style={{ color: 'var(--edge)' }}><Icon name="mark" size={42} width={1.4} /></span>
            <div>
              <div className="grot" style={{ fontSize: 15, fontWeight: 600 }}>Not measured yet</div>
              <p className="dim small" style={{ marginTop: 7, lineHeight: 1.55 }}>
                This photo has no distance. Measure it on its own to check one frame, or run the whole folder from the bar above.
              </p>
            </div>
            <button className="btn btn-amber btn-wide" style={{ height: 34, fontSize: 13 }} onClick={() => onMeasure([cur.path])}>
              <Icon name="measure" size={15} width={2.1} />
              Measure this photo
            </button>
            <div className="kv" style={{ width: '100%', textAlign: 'left', paddingTop: 6, borderTop: '1px solid var(--hair)' }}>
              <span className="cap">Camera</span>
              <span>{scope.site || '—'}</span>
              <span className="cap">Will measure against</span>
              <span>{against || '—'}</span>
              <span className="cap">Read at</span>
              <span>{methodLabel(scope.method)}</span>
            </div>
          </div>
        ) : (
          <>
            <div className="scroll">
              <div style={{ padding: '18px 16px 16px' }}>
                {best === null || best.distance_m === null ? (
                  <p className="dim small">
                    {cur.detections.length === 0
                      ? 'No animal was detected in this photo.'
                      : 'An animal was found, but no distance could be read from this frame.'}
                  </p>
                ) : (
                  <>
                    <div className="row" style={{ alignItems: 'baseline', gap: 7 }}>
                      <span className="hero">{best.distance_m.toFixed(1)}</span>
                      <span className="grot dim" style={{ fontSize: 17 }}>m</span>
                      <div className="spacer" />
                      <div style={{ textAlign: 'right' }}>
                        <div className="cap">90% between</div>
                        <div className="mono small" style={{ color: 'var(--text-2)' }}>{interval(best)}</div>
                      </div>
                    </div>
                    <div style={{ marginTop: 18 }}>
                      <div className="scale">
                        <div className="rule" />
                        {best.q05_m !== null && best.q95_m !== null && (
                          <div className="span" style={{ left: `${pct(best.q05_m)}%`, width: `${pct(best.q95_m) - pct(best.q05_m)}%` }} />
                        )}
                        <div className="tick" style={{ left: `${pct(best.distance_m)}%` }} />
                        <div className="ticks" />
                      </div>
                      <div className="mono faint" style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10 }}>
                        {[0, 5, 10, 15, 20, 25].map((m) => (
                          <span key={m}>{m === SCALE_M ? `${m} m` : m}</span>
                        ))}
                      </div>
                    </div>
                  </>
                )}
              </div>

              {cur.detections.length > 0 && (
                <div style={{ padding: '0 16px 14px' }}>
                  <div className="cap" style={{ marginBottom: 9 }}>Animals found — {cur.detections.length}</div>
                  <div className="stack">
                    {cur.detections.map((d, i) => (
                      <button
                        key={`${d.method}-${d.idx}`}
                        className={`animal${d.reasons.length ? ' animal-flagged' : ''}`}
                        aria-current={hot === i}
                        title={d.reasons.join('; ') || undefined}
                        onMouseEnter={() => setHot(i)}
                        onMouseLeave={() => setHot(null)}
                        onFocus={() => setHot(i)}
                        onClick={() => setHot(hot === i ? null : i)} // click pins the box so the pointer can leave
                      >
                        <span className="n">{i + 1}</span>
                        <span style={{ flex: 1, minWidth: 0 }}>
                          <span className="ellipsis" style={{ display: 'block' }}>{d.species}</span>
                          <span className="mono tiny faint" style={{ display: 'block' }}>box confidence {d.confidence.toFixed(2)}</span>
                        </span>
                        <span className="grot" style={{ fontSize: 15, fontWeight: 600 }}>{metres(d)}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* ponytail: the design also showed when the photo was measured, but a Row carries no measured-at
                  timestamp — left out rather than faked from the capture time. */}
              <div className="kv" style={{ padding: '14px 16px', borderTop: '1px solid var(--hair)' }}>
                <span className="cap">Camera</span>
                <span>{scope.site || '—'}</span>
                <span className="cap">Measured against</span>
                <span>{cur.flag_image ?? '—'}</span>
                <span className="cap">Alignment</span>
                <span className={cur.match_score === null ? 'warn' : undefined}>
                  {cur.match_score === null ? 'no alignment' : plural(cur.match_score, 'point')}
                </span>
                <span className="cap">Read at</span>
                <span>{methodLabel(cur.method)}</span>
              </div>
            </div>

            <div className="stack" style={{ padding: '14px 16px', borderTop: '1px solid var(--line)', gap: 9 }}>
              <button className="btn btn-wide" disabled={busy} onClick={() => onMeasure([cur.path])}>
                <Icon name="sync" />
                Measure this photo again
              </button>
              <span className="tiny faint" style={{ textAlign: 'center' }}>Uses the flag photo and method set in the bar above</span>
            </div>
          </>
        )}
      </div>
    </>
  )
}

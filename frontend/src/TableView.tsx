import Icon from './Icon'
import { useMemo, useState } from 'react'
import {
  STATE_LABEL,
  band,
  clock,
  lead,
  metres,
  photoSrc,
  plural,
  state,
  thousands,
  type Det,
  type Folder,
  type Methods,
  type Row,
  type Scope,
  type State,
} from './ui'

/** The one animal a row speaks for. lead() picks the nearest measured box; a photo can hold boxes that got
    no distance at all, and the table must still name the animal it found. */
const animal = (r: Row): Det | null => lead(r) ?? r.detections[0] ?? null

/** The engine words every reason it holds; matching its words is how the table knows which number went wrong.
    ponytail: string matching, because the thresholds (MIN_INLIERS, LOW_CONF) live in the engine and the
    window is never told them — move to a machine-readable reason code if a third caller needs this. */
const because = (reasons: string[], word: string) => reasons.some((why) => why.includes(word))
const weakBox = (d: Det | null) => !!d && because(d.reasons, 'confidence')
const unsure = (d: Det | null) => !!d && because(d.reasons, 'unsure')
// alignment is the photo's, not a box's, so this one reads the photo's reasons
const weakFit = (r: Row) => because(r.reasons, 'align') || because(r.reasons, 'poor match')

const TONE: Record<State, string> = {
  clean: 'var(--ok)',
  flagged: 'var(--bad)',
  empty: 'var(--faint)',
  new: 'var(--info)',
  stale: 'var(--dim)',
}

const FILTERS = {
  all: { label: 'All', keep: () => true, empty: 'No photo here.' },
  new: { label: 'Not measured', keep: (r: Row) => !r.measured, empty: 'Every photo in this folder has been measured.' },
  flagged: { label: 'Needs a look', keep: (r: Row) => r.reasons.length > 0, empty: 'No photo here needs a look.' },
} satisfies Record<string, { label: string; keep: (r: Row) => boolean; empty: string }>
type Filter = keyof typeof FILTERS

type SortKey = 'name' | 'time' | 'species' | 'dist' | 'band' | 'conf' | 'align' | 'status'
/* ponytail: the header follows the approved mockup and the .tr grid template in index.css — dist, 90%, conf,
   align — not the ticket's prose order; the column widths (74 / 100 / 58 / 74) are cut for exactly this. */
const COLUMNS: { key: SortKey; label: string; num?: true }[] = [
  { key: 'name', label: 'File' },
  { key: 'time', label: 'Time' },
  { key: 'species', label: 'Species' },
  { key: 'dist', label: 'Dist m', num: true },
  { key: 'band', label: '90% m', num: true },
  { key: 'conf', label: 'Conf', num: true },
  { key: 'align', label: 'Align', num: true },
  { key: 'status', label: 'Status' },
]

/** What a reviewer wants at the top when sorting by status: the rows that still ask something of them. */
const STATUS_ORDER: Record<State, number> = { flagged: 0, new: 1, stale: 2, empty: 3, clean: 4 }
const SORT: Record<SortKey, (r: Row) => string | number | null> = {
  name: (r) => r.name,
  time: (r) => r.captured_at,
  species: (r) => animal(r)?.species ?? null,
  dist: (r) => lead(r)?.distance_m ?? null,
  band: (r) => lead(r)?.q05_m ?? null,
  conf: (r) => animal(r)?.confidence ?? null,
  align: (r) => r.match_score,
  status: (r) => STATUS_ORDER[state(r)],
}

const dist = (d: Det | null) => (d && d.distance_m !== null ? d.distance_m.toFixed(1) : '—') // the heading carries the unit
const interval = (d: Det | null) => (band(d) === '—' ? 'no interval' : `${band(d)} m`)
const RULER_M = 25
const pct = (m: number) => `${Math.max(0, Math.min(100, (m / RULER_M) * 100))}%`
const fix = (n: number | null) => (n === null ? '—' : n.toFixed(1))

/** Every JPEG in the chosen folder as one sortable row, beside the photo the selected row was measured on.
    Sorting and filtering are done here over the listing the shell already holds — nothing is refetched. */
export default function TableView({
  scope,
  folder,
  methods,
  busy,
  onMeasure,
  onOpen,
  error,
}: {
  scope: Scope
  folder: Folder | null
  methods: Methods
  busy: boolean
  onMeasure: (paths: string[]) => void
  onOpen: (path: string) => void
  // ponytail: optional because the ticket's signature stops above — the shell hands the folder-listing
  // failure over so the table says why there are no rows instead of blaming the user for not picking one.
  error?: string | null
}) {
  const [filter, setFilter] = useState<Filter>('all')
  const [find, setFind] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'name', dir: 1 })
  const [ticked, setTicked] = useState<ReadonlySet<string>>(new Set())
  const [at, setAt] = useState<string | null>(null)

  const all = useMemo(() => folder?.rows ?? [], [folder]) // one identity per listing: the sort below memoizes on it
  const found = useMemo(() => {
    const q = find.trim().toLowerCase()
    return q ? all.filter((r) => r.name.toLowerCase().includes(q)) : all
  }, [all, find])
  const rows = useMemo(() => {
    const value = SORT[sort.key]
    return found.filter(FILTERS[filter].keep).sort((a, b) => {
      const x = value(a)
      const y = value(b)
      // a missing value is not a small one: it sits at the bottom whichever way the column is turned
      if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1
      const by = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))
      return sort.dir * by
    })
  }, [found, filter, sort])

  const picked = all.filter((r) => ticked.has(r.path)) // a path the listing no longer holds simply stops counting
  const allTicked = rows.length > 0 && rows.every((r) => ticked.has(r.path))
  const cur = all.find((r) => r.path === at) ?? null
  const shot = cur && lead(cur)

  const tick = (path: string) =>
    setTicked((t) => {
      const next = new Set(t)
      if (!next.delete(path)) next.add(path)
      return next
    })
  const tickAll = () =>
    setTicked((t) => {
      const next = new Set(t)
      for (const r of rows) {
        if (allTicked) next.delete(r.path)
        else next.add(r.path)
      }
      return next
    })
  const sortBy = (key: SortKey) =>
    setSort((s) => ({ key, dir: s.key === key ? ((s.dir * -1) as 1 | -1) : 1 }))

  const animals = rows.reduce((n, r) => n + r.detections.length, 0)
  const ms = rows
    .map((r) => lead(r)?.distance_m ?? null)
    .filter((m): m is number => m !== null)
    .sort((a, b) => a - b)
  const half = ms.length >> 1
  const median = ms.length === 0 ? null : ms.length % 2 ? ms[half] : (ms[half - 1] + ms[half]) / 2
  const mean = ms.length === 0 ? null : ms.reduce((s, m) => s + m, 0) / ms.length

  return (
    <>
      <div className="grid">
        <div className="pane-head" style={{ gap: 4 }}>
          {(Object.keys(FILTERS) as Filter[]).map((k) => (
            <button key={k} className="chip" aria-pressed={filter === k} onClick={() => setFilter(k)}>
              {FILTERS[k].label} {found.filter(FILTERS[k].keep).length}
            </button>
          ))}
          <div className="sep" style={{ margin: '9px 6px' }} />
          <label className="find">
            <Icon name="search" size={13} />
            <input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find a file…" aria-label="Find a file" />
          </label>
          <div className="spacer" />
          <span className="mono tiny faint">
            {plural(rows.length, 'row')} · {plural(animals, 'animal')}
          </span>
          <a
            className="btn btn-sm"
            href={`/api/export.csv?site=${encodeURIComponent(scope.site)}`}
            download
            title={`Every measured row stored for ${scope.site || 'this camera'} — the CSV is scoped to the camera, not to the filter above`}
          >
            <Icon name="download" size={12} />
            {/* the CSV is the camera's, not this folder's or this filter's — say so rather than imply a count */}
            Export {scope.site || 'all cameras'}
          </a>
        </div>

        {picked.length > 0 && (
          <div className="selbar">
            <button className="box" role="checkbox" aria-checked="true" aria-label="Clear the selection" onClick={() => setTicked(new Set())}>
              <Icon name="check" size={9} width={3.6} />
            </button>
            <span className="small" style={{ color: 'var(--amber)', fontWeight: 600 }}>
              {plural(picked.length, 'photo')} selected
            </span>
            <div className="spacer" />
            <button className="btn btn-amber btn-sm" disabled={busy} onClick={() => onMeasure(picked.map((r) => r.path))}>
              <Icon name="measure" size={12} />
              Measure these {picked.length}
            </button>
            <button className="btn btn-sm" onClick={() => setTicked(new Set())}>
              Clear
            </button>
          </div>
        )}

        {folder === null && error ? (
          <div className="empty">
            <p className="notice notice-error">{error}</p>
            <p className="faint small">Fix the path in the bar above, or use Browse… to pick the folder.</p>
          </div>
        ) : folder === null ? (
          <div className="empty">
            <p className="dim">No photo folder chosen yet.</p>
            <p className="faint small">Pick this camera's folder in the bar above — every JPEG in it lands here, measured or not.</p>
          </div>
        ) : all.length === 0 ? (
          <div className="empty">
            <p className="dim">
              No JPEG in <span className="mono small">{folder.folder}</span>.
            </p>
            <p className="faint small">
              {folder.unreadable > 0
                ? `${plural(folder.unreadable, 'file')} there could not be read.`
                : 'Choose the folder that holds the camera cards, not the one above it.'}
            </p>
          </div>
        ) : (
          <>
            <div className="tr tr-head">
              <button
                className="box"
                role="checkbox"
                aria-checked={allTicked}
                aria-label={allTicked ? 'Untick every row in view' : 'Tick every row in view'}
                disabled={rows.length === 0}
                onClick={tickAll}
              >
                <Icon name="check" size={9} width={3.6} />
              </button>
              {COLUMNS.map((c) => (
                <button
                  key={c.key}
                  className={c.num ? 'th num' : 'th'}
                  aria-sort={sort.key === c.key ? (sort.dir === 1 ? 'ascending' : 'descending') : undefined}
                  onClick={() => sortBy(c.key)}
                >
                  {c.label}
                  {sort.key === c.key && <Icon name={sort.dir === 1 ? 'up' : 'down'} size={10} width={3} />}
                </button>
              ))}
            </div>

            {rows.length === 0 ? (
              <div className="empty">
                <p className="dim">{find.trim() ? `No file name here matches "${find.trim()}".` : FILTERS[filter].empty}</p>
                {find.trim() !== '' && filter !== 'all' && (
                  <p className="faint small">The {FILTERS[filter].label.toLowerCase()} filter is on as well.</p>
                )}
                <button
                  className="btn btn-sm"
                  onClick={() => {
                    setFilter('all')
                    setFind('')
                  }}
                >
                  Show all {all.length}
                </button>
              </div>
            ) : (
              <>
                <div className="scroll">
                  {rows.map((r) => {
                    const d = animal(r)
                    const s = state(r)
                    return (
                      <div
                        key={r.path}
                        className={`tr${r.reasons.length > 0 ? ' tr-flagged' : ''}`}
                        aria-current={r.path === at ? 'true' : undefined}
                        tabIndex={0}
                        onClick={() => setAt(r.path)}
                        onKeyDown={(e) => {
                          if (e.key !== 'Enter' && e.key !== ' ') return
                          e.preventDefault()
                          setAt(r.path)
                        }}
                      >
                        <button
                          className="box"
                          role="checkbox"
                          aria-checked={ticked.has(r.path)}
                          aria-label={`Tick ${r.name}`}
                          onClick={(e) => {
                            e.stopPropagation() // ticking a row is not looking at it
                            tick(r.path)
                          }}
                        >
                          <Icon name="check" size={9} width={3.6} />
                        </button>
                        <span className="mono small ellipsis">{r.name}</span>
                        <span className="mono small dim">{clock(r.captured_at)}</span>
                        <span
                          className="small ellipsis"
                          style={{ color: unsure(d) ? 'var(--bad)' : d ? undefined : 'var(--faint)' }}
                        >
                          {d ? d.species : r.measured ? 'no animal' : '—'}
                        </span>
                        <span className="num" style={{ fontWeight: 600, color: d?.distance_m == null ? 'var(--faint)' : undefined }}>
                          {dist(d)}
                        </span>
                        <span className="num small dim">{band(lead(r))}</span>
                        <span className="num small" style={{ color: weakBox(d) ? 'var(--bad)' : d ? 'var(--dim)' : 'var(--faint)' }}>
                          {d ? d.confidence.toFixed(2) : '—'}
                        </span>
                        <span className="num small" style={{ color: weakFit(r) ? 'var(--bad)' : r.match_score === null ? 'var(--faint)' : 'var(--dim)' }}>
                          {r.match_score === null ? '—' : thousands(r.match_score)}
                        </span>
                        {r.measured ? (
                          <span className="row small" style={{ color: TONE[s], gap: 6 }}>
                            <span className="dot" />
                            {STATE_LABEL[s]}
                          </span>
                        ) : (
                          <button
                            className="btn btn-sm"
                            style={{ justifySelf: 'start' }}
                            disabled={busy}
                            onClick={(e) => {
                              e.stopPropagation()
                              onMeasure([r.path])
                            }}
                          >
                            Measure
                          </button>
                        )}
                      </div>
                    )
                  })}
                </div>

                <div className="row tiny faint" style={{ height: 34, flex: 'none', padding: '0 14px', borderTop: '1px solid var(--line)' }}>
                  {ms.length === 0 ? (
                    <span>No distance among these rows yet</span>
                  ) : (
                    <>
                      <span className="mono">median {fix(median)} m</span>
                      <span style={{ color: 'var(--line)' }}>·</span>
                      <span className="mono">mean {fix(mean)} m</span>
                      <span style={{ color: 'var(--line)' }}>·</span>
                      <span className="mono">
                        range {fix(ms[0])} – {fix(ms[ms.length - 1])} m
                      </span>
                    </>
                  )}
                  <div className="spacer" />
                  <span>Click a heading to sort · click a row to see the photo</span>
                </div>
              </>
            )}
          </>
        )}
      </div>

      <div className="pane pane-r" style={{ width: 372, flex: 'none' }}>
        <div className="pane-head">
          <span className="cap">Preview</span>
          <span className="mono tiny dim ellipsis">{cur?.name}</span>
          <div className="spacer" />
          <button className="btn btn-sm" disabled={cur === null} onClick={() => cur && onOpen(cur.path)}>
            Open in Measure
            <Icon name="right" size={11} />
          </button>
        </div>

        {cur === null ? (
          <div className="empty">
            <p className="dim">No row picked.</p>
            <p className="faint small">Click a row to see its photo and the box each distance was read from.</p>
          </div>
        ) : (
          <>
            <div className="scroll" style={{ padding: 14 }}>
              <div className="frame">
                <img src={photoSrc(cur.path, 'full')} alt={cur.name} />
                {cur.detections.map((d) => (
                  <div
                    key={`${d.method}-${d.idx}`}
                    className={`bbox${d.reasons.length > 0 ? ' bbox-flagged' : ''}${d.y1 < 0.08 ? ' bbox-low' : ''}`}
                    style={{ left: `${d.x1 * 100}%`, top: `${d.y1 * 100}%`, width: `${(d.x2 - d.x1) * 100}%`, height: `${(d.y2 - d.y1) * 100}%` }}
                  >
                    <span className="tag">
                      {d.species} · {metres(d)}
                    </span>
                    {d.distance_m !== null && <span className="foot" />}
                  </div>
                ))}
              </div>

              <div className="row" style={{ alignItems: 'baseline', gap: 7, marginTop: 16 }}>
                <span className="hero">{dist(shot)}</span>
                <span className="grot dim" style={{ fontSize: 15 }}>
                  m
                </span>
                <div className="spacer" />
                <span className="mono small">{interval(shot)}</span>
              </div>

              {/* ponytail: the ruler stops at 25 m — past that a camera-trap distance is guesswork, so a farther
                  animal pins to the end rather than squashing every near one into the first centimetre. */}
              <div className="scale" style={{ marginTop: 14 }}>
                <div className="rule" />
                {shot && shot.q05_m !== null && shot.q95_m !== null && (
                  <div className="span" style={{ left: pct(shot.q05_m), width: pct(Math.max(0, shot.q95_m - shot.q05_m)) }} />
                )}
                {shot && shot.distance_m !== null && <div className="tick" style={{ left: pct(shot.distance_m) }} />}
              </div>
              <div className="row mono tiny faint" style={{ justifyContent: 'space-between' }}>
                <span>0</span>
                <span>5</span>
                <span>10</span>
                <span>15</span>
                <span>20</span>
                <span>25 m</span>
              </div>

              <div className="kv" style={{ marginTop: 18 }}>
                <span className="cap">Species</span>
                <span>{animal(cur)?.species ?? (cur.measured ? 'no animal' : 'not measured')}</span>
                <span className="cap">Measured against</span>
                <span>{cur.flag_image ?? '—'}</span>
                <span className="cap">Alignment</span>
                <span style={{ color: weakFit(cur) ? 'var(--bad)' : undefined }}>
                  {cur.match_score === null ? 'did not align' : plural(cur.match_score, 'match point')}
                </span>
                <span className="cap">Read at</span>
                <span>{cur.method ? methods.methods[cur.method]?.label ?? cur.method : '—'}</span>
              </div>

              {cur.reasons.length > 0 && (
                <p className="warn small" style={{ marginTop: 14 }}>
                  {cur.reasons.join('; ')}
                </p>
              )}
            </div>

            <div style={{ flex: 'none', padding: 14, borderTop: '1px solid var(--line)' }}>
              <button className="btn btn-wide" disabled={busy} onClick={() => onMeasure([cur.path])}>
                <Icon name="sync" />
                {cur.measured ? 'Measure this photo again' : 'Measure this photo'}
              </button>
            </div>
          </>
        )}
      </div>
    </>
  )
}

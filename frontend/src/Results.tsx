/* RESULTS: what the measured photos add up to, and the file the researcher takes away. The filters on this
   screen are the export's filters — one query string feeds both, so the file can never disagree with the
   numbers above it. Nothing here writes: the engine is asked, the answer is drawn. */

import Help from './Help'
import Icon from './Icon'
import { useEffect, useState, type ReactNode } from 'react'
import { plural, thousands, type Summary } from './ui'

type Bin = Summary['histogram'][number]

/** ponytail: the engine sends binned counts, not the distances themselves, so the honest "median" is the bin
    the middle measurement falls in — a single interpolated number would claim a precision we were not given. */
function medianBin(bins: Bin[]): Bin | null {
  const total = bins.reduce((n, b) => n + b.n, 0)
  let seen = 0
  for (const b of bins) {
    seen += b.n
    if (seen * 2 >= total) return b
  }
  return null
}

/** Both dates are parsed the same way, so the difference is exact whatever the browser's zone. */
const spanDays = (from: string, to: string) =>
  Math.max(0, Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000) + 1)

/** Nothing to draw: one card, one honest line, and a way out where there is one. The card only — the caller
    owns the sheet, because a sheet with nothing measured in it may still carry the clear panel beside it. */
function Message({ icon, title, line, action }: { icon: 'warn' | 'results'; title: string; line: string; action?: ReactNode }) {
  return (
    <div className="card" style={{ flex: 1 }}>
      <div className="empty">
        <span className={icon === 'warn' ? 'warn' : 'faint'}>
          <Icon name={icon} size={22} />
        </span>
        <div className="stack" style={{ justifyItems: 'center' }}>
          <b className="grot">{title}</b>
          <span className="small dim">{line}</span>
        </div>
        {action}
      </div>
    </div>
  )
}

export default function Results({ site, sites, folder, onClear }: {
  site: string
  sites: string[]
  folder: string
  onClear: (what: { path?: string; site?: string; everything?: boolean }) => void | Promise<void>
}) {
  // The screen answers for the folder in the bar, not for everything this computer has ever measured:
  // otherwise a fresh window shows the last run's numbers over photos the researcher has not opened.
  const [where, setWhere] = useState<'folder' | 'all'>('folder')
  const onlyFolder = where === 'folder'
  // The shell's camera is the default; a local pick holds until the shell is pointed at another camera.
  const [pick, setPick] = useState<{ shell: string; value: string } | null>(null)
  const camera = pick && pick.shell === site ? pick.value : site
  const chooseCamera = (value: string) => setPick({ shell: site, value })

  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [allSpecies, setAllSpecies] = useState(false)
  const [includeSuspicious, setIncludeSuspicious] = useState(false)
  const [summary, setSummary] = useState<Summary | null>(null)
  // Measured photos on this computer, filters ignored. The clear buttons hang off this and not off the
  // summary: someone who has measured something and then narrowed the screen down to nothing still has
  // measurements to throw away, and still needs the button that throws them away.
  const [stored, setStored] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  // Clearing throws away work, so it asks once. Two clicks rather than a modal: the window has no dialog
  // of its own, and a browser confirm() blocks the whole WebView until it is answered.
  const [confirmClear, setConfirmClear] = useState(false)
  const [confirmAll, setConfirmAll] = useState(false)

  // The one place the filters become a query: the summary reads it, the export link appends to it.
  const params = new URLSearchParams()
  if (camera) params.set('site', camera)
  if (from) params.set('date_from', from)
  if (to) params.set('date_to', to)
  if (allSpecies) params.set('all_species', 'true')
  if (onlyFolder && folder) params.set('folder', folder)
  const query = params.toString()

  useEffect(() => {
    let live = true
    fetch(`/api/summary?${query}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`the engine answered ${r.status}`))))
      .then((s: Summary) => {
        if (live) {
          setSummary(s)
          setError(null)
        }
      })
      .catch((e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : 'the engine could not be reached')
      })
    return () => {
      live = false
    }
  }, [query, attempt])

  // The same endpoint asked with no filters at all: the whole store, counted once per visit to this screen
  // and again after anything is cleared.
  useEffect(() => {
    let live = true
    fetch('/api/summary')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('unreadable'))))
      .then((s: Summary) => {
        if (live) setStored(s.photos)
      })
      .catch(() => {
        if (live) setStored(0)
      })
    return () => {
      live = false
    }
  }, [attempt])

  /** Clear, then re-read: the numbers on this screen described rows that no longer exist. */
  const clear = (what: { site?: string; everything?: boolean }) => {
    void Promise.resolve(onClear(what)).then(() => setAttempt((n) => n + 1))
  }

  // A camera the shell points at but /api/cameras has not listed would otherwise render as a blank select.
  const cameraOptions = camera && !sites.includes(camera) ? [camera, ...sites] : sites

  const filters = (
    <div className="row" style={{ flex: 'none', gap: 6, padding: '9px 14px', borderBottom: '1px solid var(--line)', flexWrap: 'wrap', rowGap: 10 }}>
      <div className="field" style={{ width: 186, minWidth: 149 }}>
        <span className="cap">Photos</span>
        <div className="field-val">
          <select className="bare" value={where} onChange={(e) => setWhere(e.target.value === 'all' ? 'all' : 'folder')}>
            <option value="folder">The chosen folder</option>
            <option value="all">Everything measured</option>
          </select>
          <span className="chev">
            <Icon name="down" size={12} width={2.4} />
          </span>
        </div>
      </div>
      <div className="sep" />
      <div className="field" style={{ width: 168, minWidth: 134 }}>
        <span className="cap">Camera</span>
        <div className="field-val">
          <select className="bare" value={camera} onChange={(e) => chooseCamera(e.target.value)}>
            <option value="">All cameras</option>
            {cameraOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <span className="chev">
            <Icon name="down" size={12} width={2.4} />
          </span>
        </div>
      </div>
      <div className="sep" />
      <div className="field" style={{ width: 132, minWidth: 106 }}>
        <span className="cap">Captured from</span>
        <div className="field-val">
          <input className="bare mono" style={{ fontSize: 12 }} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
      </div>
      <div className="sep" />
      <div className="field" style={{ width: 132, minWidth: 106 }}>
        <span className="cap">To</span>
        <div className="field-val">
          <input className="bare mono" style={{ fontSize: 12 }} type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
      </div>
      <div className="sep" />
      <div className="field" style={{ width: 232, minWidth: 186 }}>
        <span className="cap">Species</span>
        <div className="field-val">
          <select className="bare" value={allSpecies ? 'all' : 'deer'} onChange={(e) => setAllSpecies(e.target.value === 'all')}>
            <option value="deer">White-tailed deer + unsure</option>
            <option value="all">All species</option>
          </select>
          <span className="chev">
            <Icon name="down" size={12} width={2.4} />
          </span>
        </div>
      </div>
    </div>
  )

  /* Clearing is the one thing on this screen that writes. It clears the CAMERA, never the filters above
     it: a date range or a species tick is a way of looking, not a way of choosing what to delete, and a
     button that quietly meant "the 43 rows currently on screen" would be the wrong button. By the same
     reasoning these buttons do not hide when the filters show nothing — they answer for the store. */
  const clearBox = stored > 0 && (
    <div className="stack" style={{ gap: 8 }}>
      {camera && (
        <button
          className="btn"
          style={{ height: 32, fontSize: 12,
                   ...(confirmClear ? { color: 'var(--warn)', borderColor: 'var(--warn)' } : {}) }}
          onBlur={() => setConfirmClear(false)}
          onClick={() => {
            if (!confirmClear) return setConfirmClear(true)
            setConfirmClear(false)
            clear({ site: camera })
          }}
        >
          <Icon name="trash" size={14} width={2} />
          {confirmClear
            ? `Clear every measurement for ${camera} — click again`
            : `Clear ${camera}'s measurements`}
        </button>
      )}
      {/* Every camera, every folder, everything this computer has measured. Asked for by name rather than
          by leaving the camera blank, because the difference between a mistake and this button is the
          whole database. */}
      <button
        className="btn"
        style={{ height: 32, fontSize: 12,
                 ...(confirmAll ? { color: 'var(--bad)', borderColor: 'var(--bad-line)' } : {}) }}
        onBlur={() => setConfirmAll(false)}
        onClick={() => {
          if (!confirmAll) return setConfirmAll(true)
          setConfirmAll(false)
          clear({ everything: true })
        }}
      >
        <Icon name="trash" size={14} width={2} />
        {confirmAll
          ? 'Clear EVERY measurement on this computer — click again'
          : 'Clear all measurements'}
      </button>
      <span className="tiny faint" style={{ textAlign: 'center' }}>
        Your photos and everything synced are kept <Help topic="clearCamera" align="right" />
      </span>
    </div>
  )

  // The same buttons as a panel of their own, for the screens that have no export to hang them off.
  const clearCard = clearBox && (
    <div className="card" style={{ width: 336, flex: 'none' }}>
      <div className="pane-head">
        <span className="cap">Stored measurements</span>
      </div>
      <div className="scroll" style={{ padding: 16, display: 'grid', gap: 14, alignContent: 'start' }}>
        <p className="small dim" style={{ lineHeight: 1.6 }}>
          {plural(stored, 'photo')} measured on this computer, whatever the filters above are showing.
        </p>
        {clearBox}
      </div>
    </div>
  )

  if (error !== null)
    return (
      <>
        {filters}
        <div className="sheet">
          <Message
            icon="warn"
            title="The engine is not answering"
            line={`These numbers come from the engine, and it could not be reached — ${error}.`}
            action={
              <button className="btn" onClick={() => setAttempt(attempt + 1)}>
                <Icon name="sync" size={13} />
                Try again
              </button>
            }
          />
        </div>
      </>
    )
  if (onlyFolder && !folder)
    return (
      <>
        {filters}
        <div className="sheet">
          <Message
            icon="results"
            title="No photo folder chosen"
            line="These are the results for one folder of photos. Pick a folder in MEASURE, or set Photos to everything measured to see every result on this computer."
          />
          {clearCard}
        </div>
      </>
    )
  if (summary === null)
    return (
      <>
        {filters}
        <div className="sheet">
          <Message icon="results" title="Reading the results…" line="Counting what has been measured in this selection." />
        </div>
      </>
    )
  if (summary.photos === 0)
    return (
      <>
        {filters}
        <div className="sheet">
          <Message
            icon="results"
            title={onlyFolder ? 'Nothing measured in this folder yet' : 'Nothing measured in this selection'}
            line={
              onlyFolder
                ? 'Measure this folder in MEASURE, or set Photos to everything measured.'
                : 'Measure a folder in MEASURE, or widen the camera and dates above.'
            }
          />
          {clearCard}
        </div>
      </>
    )

  const bins = summary.histogram
  const measured = bins.reduce((n, b) => n + b.n, 0)
  const peak = Math.max(1, ...bins.map((b) => b.n))
  const mid = medianBin(bins)
  const binWidth = bins.length > 0 ? bins[0].hi - bins[0].lo : 0
  const bad = summary.suspicious > 0
  // Suspicious rows are counted inside `deer`, so what the file will hold is one subtraction, not a guess.
  const exported = includeSuspicious ? summary.deer : summary.deer - summary.suspicious
  // Bars compare cameras against each other, so the camera whose animals stand furthest off fills the width.
  const widest = Math.max(1, ...summary.cameras.map((c) => c.median_m ?? 0))

  const exportParams = new URLSearchParams(query)
  if (includeSuspicious) exportParams.set('include_suspicious', 'true')
  const fileName = `camtrap-measure_${camera || 'all'}_${from || 'start'}_${to || 'end'}.csv`

  return (
    <>
      {filters}
      <div className="sheet">
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="tiles">
            <div className="card tile">
              <div className="cap">Photos</div>
              <b>{thousands(summary.photos)}</b>
            </div>
            <div className="card tile">
              <div className="cap">Animals</div>
              <b>{thousands(summary.detections)}</b>
            </div>
            <div className="card tile">
              {/* ponytail: with every species kept this repeats Animals — true, and clearer than hiding the tile. */}
              <div className="cap">{allSpecies ? 'All species' : 'Deer'}</div>
              <b>{thousands(summary.deer)}</b>
            </div>
            <div className="card tile">
              <div className="cap">Median distance</div>
              <b>
                {mid ? `${mid.lo}–${mid.hi}` : '—'}
                <span className="dim" style={{ fontSize: 14 }}> m</span>
              </b>
            </div>
            <div className="card tile" style={bad ? { borderColor: 'var(--bad-line)' } : undefined}>
              <div className={bad ? 'cap warn' : 'cap'}>Needs a look</div>
              <b className={bad ? 'warn' : 'faint'}>{thousands(summary.suspicious)}</b>
            </div>
          </div>

          <div className="card" style={{ flex: 'none' }}>
            <div className="pane-head">
              <span className="cap">{allSpecies ? 'Distances' : 'Deer distances'}</span>
              {bins.length > 0 && (
                <span className="small faint">
                  {binWidth} m bins · {plural(measured, 'measurement')}
                </span>
              )}
              <div className="spacer" />
              {mid && (
                <span className="mono tiny faint">
                  median in the {mid.lo}–{mid.hi} m bin
                </span>
              )}
            </div>
            <div style={{ padding: '16px 16px 10px' }}>
              {bins.length === 0 ? (
                <p className="small dim">
                  No distances in this selection. An animal enters the histogram once the ground could be read under it — the
                  rows that need a look say why it could not.
                </p>
              ) : (
                <div className="hist">
                  {bins.map((b, i) => (
                    <div key={b.lo} title={`${b.lo}–${b.hi} m · ${plural(b.n, 'animal')}`}>
                      {/* the tallest bin is full amber and the thin ones fade, so the shape reads before the labels do */}
                      <div style={{ height: Math.max(1, Math.round((124 * b.n) / peak)), opacity: 0.28 + (0.72 * b.n) / peak }} />
                      <span style={mid && b.lo === mid.lo ? { color: 'var(--text-2)' } : undefined}>
                        {i === bins.length - 1 ? `${b.lo} m` : b.lo}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="card" style={{ flex: 1 }}>
            <div className="pane-head">
              <span className="cap">By camera</span>
              <div className="spacer" />
              <span className="small faint">click a camera to see only its numbers</span>
            </div>
            <div className="scroll" style={{ padding: '12px 2px 0' }}>
              <table>
                <thead>
                  <tr>
                    <th>Camera</th>
                    <th className="num">Photos</th>
                    <th className="num">Animals</th>
                    <th className="num">{allSpecies ? 'Kept' : 'Deer'}</th>
                    <th className="num">Median m</th>
                    <th className="num">Needs a look</th>
                    <th style={{ width: 190 }}>Distances</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.cameras.map((c) => (
                    <tr key={c.site}>
                      <td>
                        <button
                          className="bare mono"
                          title={c.site === camera ? 'Show every camera again' : `Show only ${c.site}`}
                          onClick={() => chooseCamera(c.site === camera ? '' : c.site)}
                        >
                          {c.site}
                        </button>
                      </td>
                      <td className="num">{thousands(c.photos)}</td>
                      <td className="num">{thousands(c.detections)}</td>
                      <td className="num">{thousands(c.deer)}</td>
                      <td className="num">{c.median_m ?? '—'}</td>
                      <td className={c.suspicious > 0 ? 'num warn' : 'num faint'}>{c.suspicious}</td>
                      <td>
                        {c.median_m === null ? (
                          <span className="tiny faint">no distance read</span>
                        ) : (
                          <div
                            style={{
                              height: 6,
                              borderRadius: 2,
                              background: `linear-gradient(90deg, var(--amber) 0 ${Math.round((100 * c.median_m) / widest)}%, var(--raised) ${Math.round((100 * c.median_m) / widest)}% 100%)`,
                            }}
                          />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="card" style={{ width: 336, flex: 'none' }}>
          <div className="pane-head">
            <span className="cap">Export</span>
          </div>
          {/* Scrolls rather than clips: on a short window the panel is taller than the card, and what fell
              off the bottom used to be the clear buttons. */}
          <div className="scroll" style={{ padding: 16, display: 'grid', gap: 14, alignContent: 'start' }}>
            <p className="small dim" style={{ lineHeight: 1.6 }}>
              One row per animal, with its distance, the 90% interval and the flag photo it was measured against. Columns and
              units are written into the file's header lines.
            </p>

            <label className="check">
              <input type="checkbox" checked={allSpecies} onChange={(e) => setAllSpecies(e.target.checked)} />
              <span>
                Write every species the detector named.
                <br />
                <span className="faint">Unticked, the file keeps white-tailed deer and unsure only.</span>
              </span>
            </label>
            <label className="check">
              <input type="checkbox" checked={includeSuspicious} onChange={(e) => setIncludeSuspicious(e.target.checked)} />
              <span>
                Write the {plural(summary.suspicious, 'row')} that need{summary.suspicious === 1 ? 's' : ''} a look.
                <br />
                <span className="faint">Each one carries its reason in the flag column.</span>
              </span>
            </label>

            {!includeSuspicious && bad && (
              <div className="notice notice-warn row" style={{ gap: 7 }}>
                <Icon name="warn" />
                {plural(summary.suspicious, 'row')} will be left out
              </div>
            )}

            {exported > 0 ? (
              <>
                <a
                  className="btn btn-amber btn-wide"
                  style={{ height: 36, fontSize: 13 }}
                  href={`/api/export.csv?${exportParams}`}
                  download={fileName}
                >
                  <Icon name="download" size={15} width={2} />
                  Download CSV
                </a>
                <span className="mono tiny faint" style={{ textAlign: 'center' }}>
                  {fileName}
                </span>
              </>
            ) : (
              <p className="small faint" style={{ textAlign: 'center' }}>
                No rows to write: everything in this selection is filtered out.
              </p>
            )}

            {/* Outside the export gate on purpose: the file is what the filters say, the store is not. */}
            {clearBox}
          </div>

          {/* No spacer above: the scrolling body takes the slack, so the footer sits at the bottom anyway. */}
          <div style={{ flex: 'none', padding: '14px 16px', borderTop: '1px solid var(--hair)' }}>
            <div className="cap" style={{ marginBottom: 9 }}>
              In this selection
            </div>
            <div className="kv">
              <span className="small dim">Rows exported</span>
              <span>{thousands(exported)}</span>
              <span className="small dim">Cameras</span>
              <span>{summary.cameras.length}</span>
              <span className="small dim">Date span</span>
              <span>{from && to ? plural(spanDays(from, to), 'day') : 'all dates'}</span>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

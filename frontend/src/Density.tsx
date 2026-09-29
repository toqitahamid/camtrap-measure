/* DENSITY: deer per square kilometre from the measured distances, and the file R's Distance package reads.
   The filters are RESULTS' filters with the species fixed to white-tailed deer; one query string feeds the
   estimate and the export, so the file holds the deer the screen counted. The survey setup is the one thing
   here that writes: it is saved on this computer and the engine works the numbers out again from it. */

import Help from './Help'
import Icon from './Icon'
import { useEffect, useState, type ReactNode } from 'react'
import { plural, post, thousands, type Density as Result, type SurveyCamera } from './ui'

/** Nothing to draw: one card, one honest line. */
function Message({ icon, title, line, action }: { icon: 'warn' | 'density'; title: string; line: string; action?: ReactNode }) {
  return (
    <div className="card" style={{ flex: 1 }}>
      <div className="empty">
        <span className={icon === 'warn' ? 'warn' : 'faint'}>
          <Icon name={icon} size={22} />
        </span>
        <div className="stack" style={{ justifyItems: 'center' }}>
          <b className="grot">{title}</b>
          {line && <span className="small dim">{line}</span>}
        </div>
        {action}
      </div>
    </div>
  )
}

/** A number the researcher types. Saved when the field is left or Enter is pressed, not on every key, since
    each save has the engine refit the whole survey. Blank puts the default back. */
function NumberInput({ value, isDefault, onSave, width = 64, label }: {
  value: number | null
  isDefault: boolean
  onSave: (v: number | null) => void
  width?: number
  label: string
}) {
  const [text, setText] = useState<string | null>(null)
  const shown = text ?? (value === null ? '' : String(+value.toFixed(2)))
  const commit = () => {
    if (text === null) return
    setText(null)
    const t = text.trim()
    if (t === '') return onSave(null)
    const v = Number(t)
    if (Number.isFinite(v) && v > 0 && v !== value) onSave(v)
  }
  return (
    <input
      className="bare mono"
      aria-label={label}
      inputMode="decimal"
      style={{ width, fontSize: 12, textAlign: 'right', color: isDefault ? 'var(--dim)' : 'var(--text)' }}
      value={shown}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
    />
  )
}

const MODEL_NAME: Record<string, string> = { 'half-normal': 'Half-normal', 'hazard-rate': 'Hazard-rate' }

const shortDay = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })

/** Where a camera's numbers came from, in one short line: the dates its active days run between, and a warning
    when the field of view is a guess. Shown whether or not a number was typed over them. The full source (which
    flag calibration) is in the cell's tooltip. */
function found(c: SurveyCamera): string {
  const parts = []
  const d = c.days_source
  if (d && d.days !== null) {
    const start = d.from_kind === 'flag' ? `${shortDay(d.from)} (flag photo)` : d.from_kind === 'photo' ? `${shortDay(d.from)} (first photo)` : shortDay(d.from)
    const end = d.to_kind === 'photo' ? `${shortDay(d.to)} (last photo)` : 'the To date'
    parts.push(`${start} to ${end}`)
  }
  if (!c.fov_source) parts.push(`field of view unknown, ${c.fov_default}° is a guess`)
  return parts.length ? `${parts.join('. ')}.` : ''
}

/** Round a density for reading: two significant figures below 10, whole numbers above. */
const perKm2 = (d: number) => (d >= 10 ? d.toFixed(0) : d >= 1 ? d.toFixed(1) : d.toPrecision(2))

/** The histogram of distances up to w with the fitted curve over it, both in deer per bin. */
function DetectionChart({ r }: { r: Result }) {
  const W = 900
  const H = 230
  const pad = { l: 8, r: 8, t: 10, b: 22 }
  const w = r.truncation_m ?? 1
  const peak = Math.max(1, ...r.bins.map((b) => b.n), ...r.curve.map((c) => c.n))
  const x = (m: number) => pad.l + ((W - pad.l - pad.r) * m) / w
  const y = (n: number) => H - pad.b - ((H - pad.t - pad.b) * n) / peak
  const line = r.curve.map((c, i) => `${i ? 'L' : 'M'}${x(c.r).toFixed(1)},${y(c.n).toFixed(1)}`).join('')
  const edr = r.density?.edr_m
  // Whole-metre ticks on a round step, not the bin edges: bins are w split evenly, and 4.33 m reads as noise.
  const step = w <= 16 ? 2 : w <= 40 ? 5 : 10
  const ticks = Array.from({ length: Math.floor(w / step) + 1 }, (_, i) => i * step).filter((m) => w - m >= step * 0.75)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block' }} role="img"
         aria-label="Deer distances with the fitted detection curve">
      <line x1={pad.l} x2={W - pad.r} y1={H - pad.b} y2={H - pad.b} stroke="var(--line)" />
      {r.bins.map((b) => {
        const x0 = x(b.lo) + 1
        const x1 = x(b.hi) - 1
        return (
          <g key={b.lo}>
            <rect x={x0} width={Math.max(1, x1 - x0)} y={y(b.n)} height={Math.max(0, H - pad.b - y(b.n))}
                  rx={2} fill="var(--amber)" opacity={0.55} />
            {/* a hit area the height of the chart, so a short bar is as easy to point at as a tall one */}
            <rect x={x0} width={Math.max(1, x1 - x0)} y={pad.t} height={H - pad.t - pad.b} fill="transparent">
              <title>{`${b.lo}–${b.hi} m · ${b.n} deer`}</title>
            </rect>
          </g>
        )
      })}
      {edr !== undefined && (
        <g>
          <line x1={x(edr)} x2={x(edr)} y1={pad.t} y2={H - pad.b} stroke="var(--faint)" strokeDasharray="3 4" />
          <text x={x(edr) + 5} y={pad.t + 10} fontSize={12} fill="var(--dim)" fontFamily="var(--sans)">
            {`detection radius ${edr.toFixed(1)} m`}
          </text>
        </g>
      )}
      <path d={line} fill="none" stroke="var(--text)" strokeWidth={2} strokeLinejoin="round" />
      {ticks.map((m) => (
        <text key={m} x={x(m)} y={H - 6} fontSize={12} fill="var(--faint)" fontFamily="var(--sans)"
              textAnchor={m === 0 ? 'start' : 'middle'}>
          {m}
        </text>
      ))}
      <text x={W - pad.r} y={H - 6} fontSize={12} fill="var(--faint)" fontFamily="var(--sans)" textAnchor="end">
        {`${w} m`}
      </text>
    </svg>
  )
}

export default function Density({ site, sites, folder, onChooseFolder, onGoMeasure }: {
  site: string
  sites: string[]
  folder: string
  onChooseFolder: () => void
  onGoMeasure: () => void
}) {
  // A density is a survey-wide question, so this screen starts on everything measured, not the one folder.
  const [where, setWhere] = useState<'folder' | 'all'>('all')
  const onlyFolder = where === 'folder'
  const [pick, setPick] = useState<{ shell: string; value: string } | null>(null)
  const camera = pick && pick.shell === site ? pick.value : ''
  const chooseCamera = (value: string) => setPick({ shell: site, value })
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  // Which question the numbers on screen answer: while it is not the current one, a refit is on its way.
  const [answered, setAnswered] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  const params = new URLSearchParams()
  if (camera) params.set('site', camera)
  if (from) params.set('date_from', from)
  if (to) params.set('date_to', to)
  if (onlyFolder && folder) params.set('folder', folder)
  const query = params.toString()
  const asking = `${query}#${attempt}`
  const loading = answered !== asking

  useEffect(() => {
    let live = true
    fetch(`/api/density?${query}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`the engine answered ${r.status}`))))
      .then((d: Result) => {
        if (live) {
          setResult(d)
          setError(null)
        }
      })
      .catch((e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : 'the engine could not be reached')
      })
      .finally(() => {
        if (live) setAnswered(`${query}#${attempt}`)
      })
    return () => {
      live = false
    }
  }, [query, attempt])

  /** Save one change to the survey setup, then ask for the numbers again. */
  const save = (change: object) => {
    void post('/api/density/settings', change)
      .then(async (r) => {
        if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { detail?: string }).detail ?? `the engine answered ${r.status}`)
        setSaveError(null)
        setAttempt((n) => n + 1)
      })
      .catch((e: unknown) => setSaveError(e instanceof Error ? e.message : 'not saved'))
  }

  const cameraOptions = camera && !sites.includes(camera) ? [camera, ...sites] : sites

  const filters = (
    <div className="row" style={{ flex: 'none', gap: 6, padding: '9px 14px', borderBottom: '1px solid var(--line)', flexWrap: 'wrap', rowGap: 10 }}>
      <div className="field" style={{ width: 186, minWidth: 149 }}>
        <span className="cap">Photos</span>
        <div className="field-val">
          <select className="bare" value={where} onChange={(e) => setWhere(e.target.value === 'folder' ? 'folder' : 'all')}>
            <option value="all">Everything measured</option>
            <option value="folder">The chosen folder</option>
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
          <input className="bare" style={{ fontSize: 12 }} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
      </div>
      <div className="sep" />
      <div className="field" style={{ width: 132, minWidth: 106 }}>
        <span className="cap">To</span>
        <div className="field-val">
          <input className="bare" style={{ fontSize: 12 }} type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
      </div>
      <div className="sep" />
      <div className="field" style={{ width: 186, minWidth: 150 }}>
        <span className="cap">Species</span>
        <div className="field-val">
          <span className="dim">White-tailed deer</span>
        </div>
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
            title="The app is not answering"
            line={`Try again, or restart the app. (${error})`}
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
          <Message icon="density" title="No photo folder chosen"
                   line="Choose a folder, or set Photos to Everything measured."
                   action={<button className="btn btn-amber" onClick={onChooseFolder}>
                <Icon name="folder" size={13} width={2} />
                Choose a folder
              </button>} />
        </div>
      </>
    )
  if (result === null)
    return (
      <>
        {filters}
        <div className="sheet">
          <Message icon="density" title="Working out the density…" line="" />
        </div>
      </>
    )
  if (result.cameras.length === 0)
    return (
      <>
        {filters}
        <div className="sheet">
          <Message icon="density" title="Nothing measured in this selection"
                   line="Measure a folder in MEASURE, or widen the filters above."
                   action={<button className="btn" onClick={onGoMeasure}>
                <Icon name="measure" size={13} width={2} />
                Go to Measure
              </button>} />
        </div>
      </>
    )

  const r = result
  const exportName = `camtrap-measure_distance_${camera || 'all'}_${from || 'start'}_${to || 'end'}.csv`
  const autoW = r.truncation_default_m
  const out = [
    r.between_moments > 0 && `${r.between_moments} between snapshot moments`,
    r.beyond > 0 && `${r.beyond} beyond ${r.truncation_m} m`,
    r.suspicious > 0 && `${r.suspicious} need${r.suspicious === 1 ? 's' : ''} a look`,
    r.no_days_deer > 0 && `${r.no_days_deer} at cameras with no active days`,
  ].filter(Boolean)

  const setup = (
    <div className="card" style={{ width: 380, flex: 'none' }}>
      <div className="pane-head">
        <span className="cap">Survey setup</span>
      </div>
      <div className="scroll" style={{ padding: 16, display: 'grid', gap: 16, alignContent: 'start' }}>
        <div className="stack" style={{ gap: 6 }}>
          <div className="row" style={{ gap: 8 }}>
            <span className="small">Snapshot interval <Help topic="snapshot" /></span>
            <div className="spacer" />
            <span className="field-val" style={{ width: 'auto' }}>
              <NumberInput label="Snapshot interval in seconds" value={r.interval_s}
                           isDefault={r.interval_s === r.interval_default_s} onSave={(v) => save({ interval_s: v })} />
              <span className="small faint">s</span>
            </span>
          </div>
          <span className="tiny faint">
            {r.interval_gaps > 0
              ? `Blank uses ${r.interval_default_s} s, found from the photos.`
              : `Blank uses ${r.interval_default_s} s.`}
            {r.interval_s > 3 && ' Longer than the usual 0.25 to 3 s.'}
          </span>
        </div>

        <div className="stack" style={{ gap: 6 }}>
          <div className="row" style={{ gap: 8 }}>
            <span className="small">Truncation distance <Help topic="truncation" /></span>
            <div className="spacer" />
            <span className="field-val" style={{ width: 'auto' }}>
              <NumberInput label="Truncation distance in metres" value={r.truncation_m}
                           isDefault={r.truncation_m === autoW} onSave={(v) => save({ truncation_m: v })} />
              <span className="small faint">m</span>
            </span>
          </div>
          <span className="tiny faint">
            {autoW === null ? 'Set once deer are measured.' : `Blank uses ${autoW} m.`}
          </span>
        </div>

        <div className="stack" style={{ gap: 4 }}>
          <span className="cap">
            Cameras <Help topic="surveyCameras" />
          </span>
          <table>
            <thead>
              <tr>
                <th style={{ paddingLeft: 0 }}>Camera</th>
                <th className="num">Active days</th>
                <th className="num" style={{ paddingRight: 0 }}>Field of view °</th>
              </tr>
            </thead>
            <tbody>
              {r.cameras.map((c) => [
                <tr key={c.site}>
                  <td style={{ paddingLeft: 0, fontSize: 12 }} title={c.model ?? undefined}>
                    {c.site}
                  </td>
                  <td className="num">
                    <NumberInput label={`Active days for ${c.site}`} value={c.active_days}
                                 isDefault={c.active_days === c.active_days_default}
                                 onSave={(v) => save({ cameras: { [c.site]: { active_days: v } } })} />
                    {c.active_days === null && <span className="tiny warn"> needed</span>}
                  </td>
                  <td className="num" style={{ paddingRight: 0, whiteSpace: 'nowrap' }}>
                    {!c.fov_checked && (
                      <span className="tiny warn" title="No flag photo gives this camera's field of view, so 42 degrees is a guess">
                        check{' '}
                      </span>
                    )}
                    <NumberInput label={`Field of view for ${c.site} in degrees`} value={c.fov_deg} width={44}
                                 isDefault={c.fov_deg === c.fov_default}
                                 onSave={(v) => save({ cameras: { [c.site]: { fov_deg: v } } })} />
                  </td>
                </tr>,
                <tr key={`${c.site}-found`}>
                  <td colSpan={3} className="tiny faint" style={{ padding: '0 0 9px', borderTop: 0, lineHeight: 1.5 }}
                      title={c.fov_source ? `Field of view from the ${c.fov_source}` : undefined}>
                    {found(c)}
                  </td>
                </tr>,
              ])}
            </tbody>
          </table>
          <span className="tiny faint">Clear a box to go back to the found value.</span>
        </div>

        {saveError && <p className="notice notice-error">Not saved: {saveError}</p>}

        <div className="stack" style={{ gap: 4 }}>
          <b className="grot">
            Uses {thousands(r.used)} of {thousands(r.deer)} deer
          </b>
          {out.length > 0 && <span className="small dim">Left out: {out.join(', ')}</span>}
        </div>

        <div className="stack" style={{ gap: 6 }}>
            <a className="btn btn-amber btn-wide" style={{ height: 36, fontSize: 13 }}
               href={`/api/density.csv?${query}`} download={exportName}>
              <Icon name="download" size={15} width={2} />
              Export for R Distance
            </a>
            <span className="tiny faint" style={{ textAlign: 'center' }}>
              {exportName} <Help topic="rExport" align="right" />
            </span>
          </div>
      </div>
    </div>
  )

  if (r.used === 0)
    return (
      <>
        {filters}
        <div className="sheet">
          {setup}
          <Message
            icon="density"
            title="No deer measured"
            line={
              r.deer > 0
                ? 'Every deer here needs a look or is beyond the truncation distance.'
                : 'Measure a folder with deer, or widen the filters above.'
            }
          />
        </div>
      </>
    )

  const f = r.fit
  const d = r.density
  const model = f ? (MODEL_NAME[f.model] ?? f.model) : null
  // One sentence a student can put in a methods section; every number in it is on this screen.
  const howToReport = f && d
    ? `Deer density was estimated by camera-trap distance sampling (Howe et al. 2017) with a ${model?.toLowerCase()} ` +
      `detection function${f.other ? ' chosen by AIC' : ''}, a truncation distance of ${r.truncation_m} m and a ` +
      `${r.interval_s} s snapshot interval: ${perKm2(d.per_km2)} deer per km² (90% CI ${perKm2(d.lo)} to ` +
      `${perKm2(d.hi)}, by bootstrap), from ${thousands(r.used)} deer at ${plural(r.cameras.length, 'camera')}.`
    : null
  return (
    <>
      {filters}
      <div className="sheet">
        {setup}
        <div className="scroll" style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="card" style={{ flex: 'none' }}>
            <div className="pane-head">
              <span className="cap">Density</span>
              <Help topic="density" />
              <div className="spacer" />
              {loading && (
                <span className="tiny faint row" style={{ gap: 6 }}>
                  <span className="spin">
                    <Icon name="spinner" size={12} />
                  </span>
                  Updating
                </span>
              )}
            </div>
            <div style={{ padding: 16, display: 'grid', gap: 12 }}>
              {r.too_few && (
                <div className="notice notice-warn row" style={{ gap: 7 }}>
                  <Icon name="warn" />
                  Only {r.used} deer. A density needs about 60 to 80.
                </div>
              )}
              {d && (
                <>
                  <div className="row" style={{ gap: 18, alignItems: 'baseline', flexWrap: 'wrap' }}>
                    <b className="grot" style={{ fontSize: 34, fontWeight: 600, letterSpacing: '-0.02em' }}>
                      {perKm2(d.per_km2)}
                      <span className="dim" style={{ fontSize: 14 }}> deer per km²</span>
                    </b>
                    <span className="small dim">
                      90% confidence interval {perKm2(d.lo)} to {perKm2(d.hi)} <Help topic="densityRange" />
                    </span>
                  </div>
                  <span className="small dim">The estimated number of deer per square kilometre around these cameras.</span>
                  <div className="kv" style={{ maxWidth: 380 }}>
                    <span className="small dim">Detection probability <Help topic="detectionProb" /></span>
                    <span>{d.p.toFixed(3)}</span>
                    <span className="small dim">Effective detection radius <Help topic="edr" /></span>
                    <span>{d.edr_m.toFixed(1)} m</span>
                    <span className="small dim">Deer used</span>
                    <span>{thousands(r.used)}</span>
                    <span className="small dim">Cameras</span>
                    <span>{r.cameras.length}</span>
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="card" style={{ flex: 'none' }}>
            <div className="pane-head">
              <span className="cap">Detection function</span>
              <Help topic="detectionFunction" />
            </div>
            <div style={{ padding: '14px 16px 10px' }}>
              <DetectionChart r={r} />
              <span className="tiny faint">Bars: deer counted at each distance. Line: the fitted detection function.</span>
            </div>
          </div>

          {/* The model-selection numbers a thesis reports, folded away: nobody acts on them day to day. */}
          {f && (
            <details className="card" style={{ flex: 'none' }}>
              <summary className="pane-head" style={{ cursor: 'pointer' }}>
                <span className="cap">Details for your report</span>
                <Help topic="reportDetails" />
                <div className="spacer" />
                <span className="faint"><Icon name="down" size={12} width={2.4} /></span>
              </summary>
              <div style={{ padding: 16, display: 'grid', gap: 12 }}>
                <div className="kv" style={{ maxWidth: 380 }}>
                  <span className="small dim">Model</span>
                  <span>{model}</span>
                  <span className="small dim">σ (scale)</span>
                  <span>{f.sigma.toFixed(1)} m</span>
                  {f.b !== null && (
                    <>
                      <span className="small dim">b (shape)</span>
                      <span>{f.b.toFixed(1)}</span>
                    </>
                  )}
                  <span className="small dim">AIC</span>
                  <span>{f.aic.toFixed(1)}</span>
                  {f.other && (
                    <>
                      <span className="small dim">AIC, {MODEL_NAME[f.other.model] ?? f.other.model}</span>
                      <span>{f.other.aic.toFixed(1)}</span>
                    </>
                  )}
                  <span className="small dim">Photos at snapshot moments</span>
                  <span>
                    {thousands(r.photos.at_moments)} of {thousands(r.photos.photos)}
                    {r.photos.undated > 0 && `, ${r.photos.undated} without a time`}
                  </span>
                </div>
                {howToReport && (
                  <div className="stack" style={{ gap: 4 }}>
                    <span className="cap">How to report this</span>
                    <span className="small" style={{ lineHeight: 1.6, userSelect: 'text' }}>{howToReport}</span>
                  </div>
                )}
              </div>
            </details>
          )}
        </div>
      </div>
    </>
  )
}

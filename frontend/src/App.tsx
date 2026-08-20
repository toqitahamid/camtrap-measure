import { useCallback, useEffect, useState, type FormEvent } from 'react'

type Inference = {
  status: 'loading' | 'ready' | 'error'
  backend: 'fake' | 'real'
  device: string | null
  batch: number | null
  weights: string | null
  warning: string | null
  error: string | null
}
type Status = {
  signed_in: boolean
  email: string | null
  last_sync: string | null
  annotations: number
  sites: number
  inference: Inference
}
type SyncResult =
  | { ok: true; last_sync: string; annotations: number; sites: number; remeasure: number | null }
  | { ok: false; offline: true; last_sync: string | null }
type Calibration = {
  image_name: string
  captured_at: string | null
  window_end: string | null
  ok: boolean
  reason: string | null
}
type Camera = { site: string; verdict: 'green' | 'red'; reason: string | null; calibrations: Calibration[] }
type Summary = {
  photos: number
  held: number
  detections: number
  deer: number
  suspicious: number
  histogram: { lo: number; hi: number; n: number }[]
  cameras: { site: string; photos: number; held: number; detections: number; deer: number; median_m: number | null; suspicious: number }[]
}
type Suspect = {
  path: string
  photo: string
  site: string
  captured_at: string | null
  held: boolean
  reasons: string[]
  detections: { x1: number; y1: number; x2: number; y2: number; species: string; confidence: number; distance_m: number | null; method: string }[]
}
type Methods = { default: string; methods: Record<string, { label: string; hint: string }> }
type Run = {
  folder: string
  site: string
  method: string | null
  status: 'running' | 'done' | 'cancelled' | 'error'
  total: number
  done: number
  held: number
  skipped: number
  detections: number
  held_reasons: { reason: string; count: number }[]
  error: string | null
  elapsed_s: number
  eta_s: number | null
}

const post = (url: string, body?: unknown) =>
  fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'never')
const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : '—')
const duration = (s: number) => (s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`)

function ModelsLine({ inf }: { inf: Inference }) {
  if (inf.status === 'loading') return <p>Loading models…</p>
  if (inf.status === 'error') return <p style={{ color: 'crimson' }}>Models unavailable: {inf.error}</p>
  return (
    <p>
      Models:{' '}
      {inf.backend === 'real'
        ? `MegaDetector + SpeciesNet ${inf.weights} on ${inf.device} (batch ${inf.batch})`
        : 'none'}
      {inf.warning && <span style={{ color: 'darkorange' }}> · ⚠ {inf.warning}</span>}
    </p>
  )
}

function RunPanel({ methods, ready, pollKey, onDone }: { methods: Methods; ready: boolean; pollKey: number; onDone: (site: string) => void }) {
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [picked, setPicked] = useState<string | null>(null)
  const method = picked ?? methods.default
  const running = run?.status === 'running'

  const poll = () => fetch('/api/run').then((r) => r.json()).then(setRun).catch(() => {}) // engine down: App's refresh says so

  useEffect(() => void poll(), [pollKey]) // a sync may have started a catch-up run
  useEffect(() => {
    if (!running) return
    const id = setInterval(poll, 1000)
    return () => {
      clearInterval(id)
      if (run) onDone(run.site) // left the running state: show that camera's results
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running])

  async function start(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    setError(null)
    const r = await post('/api/run', { folder: form.get('folder'), method: form.get('method'), rerun: form.get('rerun') === 'on' })
    if (!r.ok) {
      setError((await r.json()).detail ?? `Could not start (${r.status})`)
      return
    }
    setRun(await r.json())
  }

  return (
    <section style={{ marginTop: '2rem' }}>
      <h2>Measure</h2>
      {/* ponytail: typed/pasted path; a native folder picker needs a pywebview dialog bridge — add when the dept trips over this. */}
      <form id="run-form" onSubmit={start} style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <input name="folder" placeholder="Photo folder named after the camera, e.g. D:\photos\TON_CAM02" required style={{ flex: 1, minWidth: 320 }} />
        <select name="method" value={method} onChange={(e) => setPicked(e.target.value)}>
          {Object.entries(methods.methods).map(([k, m]) => (
            <option key={k} value={k}>{m.label}</option>
          ))}
        </select>
        <button type="submit" disabled={running || !ready}>{running ? 'Running…' : 'Measure'}</button>
        {running && <button type="button" onClick={() => post('/api/run/cancel').then(poll)}>Cancel</button>}
      </form>
      {methods.methods[method] && <p style={{ color: '#555', margin: '0.3rem 0 0' }}>{methods.methods[method].hint}</p>}
      <label style={{ color: '#555', fontSize: 13 }}>
        <input type="checkbox" name="rerun" form="run-form" /> Re-measure photos that already have an answer (otherwise only new, held or
        interrupted ones are measured — so Measure again also resumes a cancelled run)
      </label>
      {error && <p style={{ color: 'crimson' }}>{error}</p>}
      {run && (
        <div style={{ marginTop: '1rem' }}>
          <progress value={run.done} max={run.total} style={{ width: '100%' }} />
          <p>
            {run.site || 'Held photos, all cameras'} · {run.method ? methods.methods[run.method]?.label ?? run.method : 'each under its own method'} · {run.done}/{run.total} photos · {run.detections} animals · {run.held} held
            {run.skipped > 0 && ` · ${run.skipped} already measured`}
            {running && run.eta_s !== null && ` · about ${duration(run.eta_s)} left`}
            {run.status === 'done' && ` · finished in ${duration(run.elapsed_s)}`}
            {run.status === 'cancelled' && ` · cancelled after ${duration(run.elapsed_s)} — Measure again continues where it stopped`}
          </p>
          {run.status === 'error' && <p style={{ color: 'crimson' }}>Run failed: {run.error}</p>}
          {run.held_reasons.length > 0 && (
            <div style={{ background: '#fff4e5', borderLeft: '4px solid darkorange', padding: '0.6rem 0.8rem' }}>
              <strong>{run.held} photo{run.held === 1 ? '' : 's'} held — not measured.</strong> After fixing, Sync and run this folder again:
              <ul style={{ margin: '0.4rem 0 0' }}>
                {run.held_reasons.map((h) => (
                  <li key={h.reason}>{h.reason} ({h.count} photo{h.count === 1 ? '' : 's'})</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  )
}


function ResultsPanel({ sites, focus }: { sites: string[]; focus: { site: string; n: number } }) {
  const [pick, setPick] = useState<{ site: string; n: number } | null>(null)
  const site = pick && pick.n === focus.n ? pick.site : focus.site // a finished run refocuses on its camera; the user can re-pick after
  const setSite = (s: string) => setPick({ site: s, n: focus.n })
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [allSpecies, setAllSpecies] = useState(false)
  const [includeSuspicious, setIncludeSuspicious] = useState(false)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [suspects, setSuspects] = useState<Suspect[]>([])

  const scope = new URLSearchParams()
  if (site) scope.set('site', site)
  if (from) scope.set('date_from', from)
  if (to) scope.set('date_to', to)
  const qs = scope.toString()

  useEffect(() => {
    fetch(`/api/summary?${qs}${allSpecies ? '&all_species=true' : ''}`).then((r) => r.json()).then(setSummary).catch(() => {})
    fetch(`/api/suspicious?${qs}`).then((r) => r.json()).then(setSuspects).catch(() => {})
  }, [qs, allSpecies, focus])

  const exportQs = new URLSearchParams(scope)
  if (allSpecies) exportQs.set('all_species', 'true')
  if (includeSuspicious) exportQs.set('include_suspicious', 'true')
  const peak = Math.max(1, ...(summary?.histogram.map((b) => b.n) ?? [1]))

  return (
    <section style={{ marginTop: '2rem' }}>
      <h2>Results</h2>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={site} onChange={(e) => setSite(e.target.value)}>
          <option value="">All cameras</option>
          {sites.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <label>from <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>to <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
      </div>
      {!summary || summary.photos === 0 ? (
        <p>No measured photos in this range yet.</p>
      ) : (
        <>
          <p>
            {summary.photos} photos ({summary.held} held) · {summary.detections} animals · {summary.deer} deer ·{' '}
            {summary.suspicious} suspicious{allSpecies ? '' : ' deer'} rows
          </p>
          {summary.histogram.length > 0 && (
            <div>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 80 }}>
                {summary.histogram.map((b) => (
                  <div key={b.lo} title={`${b.lo}–${b.hi} m: ${b.n}`} style={{ flex: 1, textAlign: 'center', fontSize: 11 }}>
                    <div style={{ background: 'seagreen', height: (70 * b.n) / peak }} />
                    {b.lo}
                  </div>
                ))}
              </div>
              <div style={{ fontSize: 12, color: '#555' }}>Deer distances, metres ({summary.histogram[0].hi - summary.histogram[0].lo} m bins)</div>
            </div>
          )}
          <table style={{ borderCollapse: 'collapse', width: '100%', marginTop: '0.8rem' }}>
            <thead>
              <tr style={{ textAlign: 'left' }}>
                <th>Camera</th><th>Photos</th><th>Held</th><th>Animals</th><th>Deer</th><th>Median m</th><th>Suspicious</th>
              </tr>
            </thead>
            <tbody>
              {summary.cameras.map((c) => (
                <tr key={c.site} style={{ borderTop: '1px solid #ddd' }}>
                  <td>{c.site}</td><td>{c.photos}</td><td>{c.held}</td><td>{c.detections}</td><td>{c.deer}</td>
                  <td>{c.median_m ?? '—'}</td><td>{c.suspicious}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 style={{ marginTop: '1.5rem' }}>Needs a look ({suspects.length})</h3>
          {suspects.length === 0 ? (
            <p>Nothing suspicious — no review needed.</p>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1rem' }}>
              {suspects.map((s) => (
                <figure key={s.path} style={{ margin: 0 }}>
                  <div style={{ position: 'relative' }}>
                    <img src={`/api/photo?path=${encodeURIComponent(s.path)}`} alt={s.photo} style={{ width: '100%', display: 'block' }} />
                    {s.detections.map((d, i) => (
                      <div
                        key={i}
                        title={`${d.species} ${d.confidence.toFixed(2)}${d.distance_m !== null ? ` · ${d.distance_m.toFixed(1)} m` : ''}`}
                        style={{ position: 'absolute', border: '2px solid darkorange', left: `${d.x1 * 100}%`, top: `${d.y1 * 100}%`,
                                 width: `${(d.x2 - d.x1) * 100}%`, height: `${(d.y2 - d.y1) * 100}%` }}
                      />
                    ))}
                  </div>
                  <figcaption style={{ fontSize: 13 }}>
                    <strong>{s.site} · {s.photo}</strong> · {s.captured_at ? new Date(s.captured_at).toLocaleString() : 'no date'}
                    <ul style={{ margin: '0.2rem 0 0', paddingLeft: '1.2rem', color: s.held ? 'crimson' : 'darkorange' }}>
                      {s.reasons.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                  </figcaption>
                </figure>
              ))}
            </div>
          )}

          <h3 style={{ marginTop: '1.5rem' }}>Export</h3>
          <div style={{ display: 'grid', gap: '0.4rem' }}>
            <label>
              <input type="checkbox" checked={allSpecies} onChange={(e) => setAllSpecies(e.target.checked)} /> All species (default: white-tailed deer and unsure only)
            </label>
            <label>
              <input type="checkbox" checked={includeSuspicious} onChange={(e) => setIncludeSuspicious(e.target.checked)} />{' '}
              Include the {summary.suspicious} suspicious row{summary.suspicious === 1 ? '' : 's'} (they carry their reason in the flag column)
            </label>
            <p style={{ margin: 0 }}>
              <a href={`/api/export.csv?${exportQs}`} download>Download CSV</a>
              {!includeSuspicious && summary.suspicious > 0 && ` — ${summary.suspicious} suspicious row${summary.suspicious === 1 ? '' : 's'} will be left out`}
              <span style={{ color: '#555' }}> · columns and units are documented in the file's header lines</span>
            </p>
          </div>
        </>
      )}
    </section>
  )
}

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [cameras, setCameras] = useState<Camera[]>([])
  const [methods, setMethods] = useState<Methods>({ default: '', methods: {} })
  const [notice, setNotice] = useState<{ text: string; kind: 'info' | 'warn' | 'error' } | null>(null)
  const [busy, setBusy] = useState(false)
  const [focus, setFocus] = useState({ site: '', n: 0 })
  const [pollKey, setPollKey] = useState(0)
  const [build, setBuild] = useState<{ version: string; commit: string | null } | null>(null)

  const refresh = useCallback(
    () =>
      Promise.all([fetch('/api/status').then((r) => r.json()), fetch('/api/cameras').then((r) => r.json())])
        .then(([s, c]) => {
          setStatus(s)
          setCameras(c)
        })
        .catch((e) => setNotice({ text: `Engine unreachable: ${e}`, kind: 'error' })),
    [],
  )
  useEffect(() => {
    void refresh()
    fetch('/api/methods').then((r) => r.json()).then(setMethods)
    fetch('/api/health').then((r) => r.json()).then(setBuild).catch(() => {})
  }, [refresh])
  const loading = status?.inference.status === 'loading'
  useEffect(() => {
    if (!loading) return
    const id = setInterval(refresh, 1000) // model load / weights download in progress
    return () => clearInterval(id)
  }, [loading, refresh])

  async function login(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    setBusy(true)
    setNotice(null)
    const r = await post('/api/login', { email: form.get('email'), password: form.get('password') })
    setBusy(false)
    if (!r.ok) {
      setNotice({ text: (await r.json()).detail ?? 'Sign-in failed', kind: 'error' })
      return
    }
    await refresh()
  }

  async function sync() {
    setBusy(true)
    setNotice(null)
    const r = await post('/api/sync')
    setBusy(false)
    if (!r.ok) {
      setNotice({ text: (await r.json()).detail ?? `Sync failed (${r.status})`, kind: 'error' })
      await refresh() // 401 means the session was cleared
      return
    }
    const body: SyncResult = await r.json()
    if (body.ok) {
      const catchUp = body.remeasure ? ` Re-checking ${body.remeasure} held photo${body.remeasure === 1 ? '' : 's'} now.` : ''
      setNotice({ text: `Synced ${body.annotations} annotations, ${body.sites} cameras.${catchUp}`, kind: 'info' })
      setPollKey((k) => k + 1)
    } else {
      setNotice({ text: `Offline — using calibrations from last sync ${when(body.last_sync)}.`, kind: 'warn' })
    }
    await refresh()
  }

  async function logout() {
    await post('/api/logout')
    setNotice(null)
    await refresh()
  }

  const color = { info: 'seagreen', warn: 'darkorange', error: 'crimson' }
  const ready = cameras.filter((c) => c.verdict === 'green').length

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: '2rem', maxWidth: 900 }}>
      <h1>
        CamTrap Measure{' '}
        {build && (
          <small style={{ fontSize: '0.45em', color: '#777', fontWeight: 'normal' }} title="The version this computer runs; the launcher updates it at every start">
            v{build.version}{build.commit && ` (${build.commit})`}
          </small>
        )}
      </h1>
      {notice && <p style={{ color: color[notice.kind] }}>{notice.text}</p>}
      {!status ? (
        !notice && <p>Connecting to engine…</p>
      ) : !status.signed_in ? (
        <form onSubmit={login} style={{ display: 'grid', gap: '0.5rem', maxWidth: 360 }}>
          <p>Sign in with your FlagLabel account.</p>
          <input name="email" type="email" placeholder="Email" required autoFocus />
          <input name="password" type="password" placeholder="Password" required />
          <button type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      ) : (
        <>
          <p>
            Signed in as {status.email} · <button onClick={logout}>Sign out</button>
          </p>
          <button onClick={sync} disabled={busy}>
            {busy ? 'Syncing…' : 'Sync'}
          </button>
          <p>
            Last sync: {when(status.last_sync)} · {status.annotations} annotations · {ready}/{cameras.length}{' '}
            cameras ready
          </p>
          {cameras.length > 0 && (
            <table style={{ borderCollapse: 'collapse', width: '100%' }}>
              <thead>
                <tr style={{ textAlign: 'left' }}>
                  <th>Camera</th>
                  <th>Status</th>
                  <th>Calibrations (flag photo · valid from → until)</th>
                </tr>
              </thead>
              <tbody>
                {cameras.map((c) => (
                  <tr key={c.site} style={{ borderTop: '1px solid #ddd', verticalAlign: 'top' }}>
                    <td style={{ padding: '0.4rem 0.6rem 0.4rem 0', whiteSpace: 'nowrap' }}>{c.site}</td>
                    <td style={{ padding: '0.4rem 0.6rem 0.4rem 0', whiteSpace: 'nowrap' }}>
                      <span style={{ color: c.verdict === 'green' ? 'seagreen' : 'crimson' }}>
                        ● {c.verdict === 'green' ? 'Ready' : 'Needs attention'}
                      </span>
                    </td>
                    <td style={{ padding: '0.4rem 0' }}>
                      {c.calibrations.map((cal) => (
                        <div key={cal.image_name} style={{ color: cal.ok ? undefined : 'crimson' }}>
                          {cal.image_name} · {day(cal.captured_at)} → {cal.window_end ? day(cal.window_end) : 'now'}
                        </div>
                      ))}
                      {c.reason && <div style={{ color: 'crimson' }}>{c.reason}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <ModelsLine inf={status.inference} />
          <RunPanel methods={methods} ready={status.inference.status === 'ready'} pollKey={pollKey} onDone={(site) => setFocus((f) => ({ site, n: f.n + 1 }))} />
          <ResultsPanel sites={cameras.map((c) => c.site)} focus={focus} />
        </>
      )}
    </main>
  )
}

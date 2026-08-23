import { useCallback, useEffect, useState, type FormEvent } from 'react'

type Inference = {
  status: 'loading' | 'ready' | 'error'
  backend: 'fake' | 'real'
  device: string | null
  batch: number | null
  weights: string | null
  warning: string | null
  error: string | null
  download: { done_gb: number; total_gb: number } | null
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
  | { ok: true; last_sync: string; annotations: number; sites: number }
  | { ok: false; offline: true; last_sync: string | null }
type Flag = { image_name: string; captured_at: string | null; ok: boolean; reason: string | null }
type Camera = { site: string; flags: Flag[] }
type Summary = {
  photos: number
  detections: number
  deer: number
  suspicious: number
  histogram: { lo: number; hi: number; n: number }[]
  cameras: { site: string; photos: number; detections: number; deer: number; median_m: number | null; suspicious: number }[]
}
type Suspect = {
  path: string
  photo: string
  site: string
  captured_at: string | null
  reasons: string[]
  detections: { x1: number; y1: number; x2: number; y2: number; species: string; confidence: number; distance_m: number | null; method: string }[]
}
type Methods = { default: string; methods: Record<string, { label: string; hint: string }> }
type Run = {
  folder: string
  site: string
  flag: string
  method: string
  status: 'running' | 'done' | 'cancelled' | 'error'
  total: number
  done: number
  skipped: number
  unreadable: number
  detections: number
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
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

function Stat({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="stat">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  )
}

function ModelsLine({ inf }: { inf: Inference }) {
  if (inf.status === 'loading')
    return (
      <div className="stack">
        <p className="muted small">
          {inf.download ? `Downloading model weights: ${inf.download.done_gb.toFixed(1)} / ${inf.download.total_gb.toFixed(1)} GB` : 'Loading models…'}
        </p>
        {inf.download && <progress value={inf.download.done_gb} max={inf.download.total_gb || 1} />}
      </div>
    )
  if (inf.status === 'error') return <p className="notice notice-error">Models unavailable: {inf.error}</p>
  return (
    <p className="muted small">
      Models:{' '}
      {inf.backend === 'real'
        ? `MegaDetector + SpeciesNet ${inf.weights} on ${inf.device} (batch ${inf.batch})`
        : 'none'}
      {inf.warning && <span className="warn"> · ⚠ {inf.warning}</span>}
    </p>
  )
}

function RunPanel({ cameras, methods, ready, pollKey, onDone }: { cameras: Camera[]; methods: Methods; ready: boolean; pollKey: number; onDone: (site: string) => void }) {
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [picked, setPicked] = useState<string | null>(null)
  const [site, setSite] = useState('')
  const [flag, setFlag] = useState('')
  const method = picked ?? methods.default
  const running = run?.status === 'running'
  const usable = cameras.filter((c) => c.flags.some((f) => f.ok)) // a camera is offered once one of its flag photos fits
  const flags = usable.find((c) => c.site === site)?.flags ?? []
  useEffect(() => {
    // keep the selects valid as the list changes (a sync, the first load): first camera, its newest usable flag photo
    const cam = usable.find((c) => c.site === site) ?? usable[0]
    const s = cam?.site ?? ''
    if (s !== site) setSite(s)
    if (!cam?.flags.some((f) => f.ok && f.image_name === flag)) setFlag(cam?.flags.find((f) => f.ok)?.image_name ?? '')
  }, [cameras, site, flag, usable])

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
    const r = await post('/api/run', { folder: form.get('folder'), site, flag, method: form.get('method'), rerun: form.get('rerun') === 'on' })
    if (!r.ok) {
      setError((await r.json()).detail ?? `Could not start (${r.status})`)
      return
    }
    setRun(await r.json())
  }

  return (
    <section className="card">
      <h2>Measure</h2>
      {/* ponytail: typed/pasted path; a native folder picker needs a pywebview dialog bridge — add when the dept trips over this. */}
      {usable.length === 0 && <p className="muted small">No camera has a labeled flag photo yet — label one in FlagLabel, then Sync.</p>}
      <form id="run-form" onSubmit={start} className="row">
        <select value={site} onChange={(e) => setSite(e.target.value)} title="Camera">
          {usable.map((c) => (
            <option key={c.site} value={c.site}>{c.site}</option>
          ))}
        </select>
        <select value={flag} onChange={(e) => setFlag(e.target.value)} title="Flag photo to measure against">
          {flags.map((f) => (
            <option key={f.image_name} value={f.image_name} disabled={!f.ok} title={f.reason ?? undefined}>
              {f.image_name} · {f.captured_at ? day(f.captured_at) : 'no date'}{f.ok ? '' : ' — not usable'}
            </option>
          ))}
        </select>
        <input name="folder" placeholder="Folder with this camera's photos, e.g. D:\photos\TON_CAM02" required className="grow" style={{ minWidth: 320 }} />
        <select name="method" value={method} onChange={(e) => setPicked(e.target.value)}>
          {Object.entries(methods.methods).map(([k, m]) => (
            <option key={k} value={k}>{m.label}</option>
          ))}
        </select>
        <button type="submit" className="btn btn-primary" disabled={running || !ready || !flag}>{running ? 'Running…' : 'Measure'}</button>
        {running && <button type="button" className="btn" onClick={() => post('/api/run/cancel').then(poll)}>Cancel</button>}
      </form>
      {methods.methods[method] && <p className="muted small">{methods.methods[method].hint}</p>}
      <label className="check">
        <input type="checkbox" name="rerun" form="run-form" />
        <span>
          Re-measure photos that already have an answer (otherwise only new or interrupted ones are measured — so Measure again
          also resumes a cancelled run)
        </span>
      </label>
      {error && <p className="notice notice-error">{error}</p>}
      {run && (
        <div className="stack">
          <progress value={run.done} max={run.total} />
          <p className="small">
            <strong>{run.site}</strong> · flag photo {run.flag} · {methods.methods[run.method]?.label ?? run.method} · {run.done}/{run.total} photos · {run.detections} animals
            {run.skipped > 0 && ` · ${run.skipped} already measured`}
            {run.unreadable > 0 && ` · ${plural(run.unreadable, 'unreadable file')} skipped`}
            {running && run.eta_s !== null && ` · about ${duration(run.eta_s)} left`}
            {run.status === 'done' && ` · finished in ${duration(run.elapsed_s)}`}
            {run.status === 'cancelled' && ` · cancelled after ${duration(run.elapsed_s)} — Measure again continues where it stopped`}
          </p>
          {run.status === 'error' && <p className="notice notice-error">Run failed: {run.error}</p>}
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
    <>
      <section className="card">
        <div className="card-head">
          <h2>Results</h2>
          <div className="spacer" />
          <select value={site} onChange={(e) => setSite(e.target.value)}>
            <option value="">All cameras</option>
            {sites.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <label className="row small muted">from <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
          <label className="row small muted">to <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        </div>
        {!summary || summary.photos === 0 ? (
          <p className="muted">No measured photos in this range yet.</p>
        ) : (
          <>
            <div className="stats">
              <Stat value={summary.photos} label="photos" />
              <Stat value={summary.detections} label="animals" />
              <Stat value={summary.deer} label="deer" />
              <Stat value={summary.suspicious} label={`suspicious${allSpecies ? '' : ' deer'} rows`} />
            </div>
            {summary.histogram.length > 0 && (
              <div className="stack">
                <div className="hist">
                  {summary.histogram.map((b) => (
                    <div key={b.lo} title={`${b.lo}–${b.hi} m: ${b.n}`}>
                      <div style={{ height: (80 * b.n) / peak }} />
                      {b.lo}
                    </div>
                  ))}
                </div>
                <div className="small muted">Deer distances, metres ({summary.histogram[0].hi - summary.histogram[0].lo} m bins)</div>
              </div>
            )}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Camera</th><th className="num">Photos</th><th className="num">Animals</th><th className="num">Deer</th><th className="num">Median m</th><th className="num">Suspicious</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.cameras.map((c) => (
                    <tr key={c.site}>
                      <td>{c.site}</td><td className="num">{c.photos}</td><td className="num">{c.detections}</td><td className="num">{c.deer}</td>
                      <td className="num">{c.median_m ?? '—'}</td><td className="num">{c.suspicious}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      {summary && summary.photos > 0 && (
        <>
          <section className="card">
            <h2>Needs a look <span className="muted">({suspects.length})</span></h2>
            {suspects.length === 0 ? (
              <p className="muted">Nothing suspicious — no review needed.</p>
            ) : (
              <div className="gallery">
                {suspects.map((s) => (
                  <figure key={s.path}>
                    <div className="thumb">
                      <img src={`/api/photo?path=${encodeURIComponent(s.path)}`} alt={s.photo} />
                      {s.detections.map((d, i) => (
                        <div
                          key={i}
                          className="bbox"
                          title={`${d.species} ${d.confidence.toFixed(2)}${d.distance_m !== null ? ` · ${d.distance_m.toFixed(1)} m` : ''}`}
                          style={{ left: `${d.x1 * 100}%`, top: `${d.y1 * 100}%`, width: `${(d.x2 - d.x1) * 100}%`, height: `${(d.y2 - d.y1) * 100}%` }}
                        />
                      ))}
                    </div>
                    <figcaption>
                      <strong>{s.site} · {s.photo}</strong> <span className="muted">· {s.captured_at ? new Date(s.captured_at).toLocaleString() : 'no date'}</span>
                      <ul className="warn">
                        {s.reasons.map((r) => (
                          <li key={r}>{r}</li>
                        ))}
                      </ul>
                    </figcaption>
                  </figure>
                ))}
              </div>
            )}
          </section>

          <section className="card">
            <h2>Export</h2>
            <label className="check">
              <input type="checkbox" checked={allSpecies} onChange={(e) => setAllSpecies(e.target.checked)} />
              <span>All species (default: white-tailed deer and unsure only)</span>
            </label>
            <label className="check">
              <input type="checkbox" checked={includeSuspicious} onChange={(e) => setIncludeSuspicious(e.target.checked)} />
              <span>Include the {plural(summary.suspicious, 'suspicious row')} (they carry their reason in the flag column)</span>
            </label>
            <p className="row">
              <a className="btn btn-primary" href={`/api/export.csv?${exportQs}`} download>Download CSV</a>
              <span className="small muted">
                {!includeSuspicious && summary.suspicious > 0 && `${plural(summary.suspicious, 'suspicious row')} will be left out · `}
                columns and units are documented in the file's header lines
              </span>
            </p>
          </section>
        </>
      )}
    </>
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
  const [codeSentTo, setCodeSentTo] = useState<string | null>(null) // sign-in step two: a code is on its way to this address

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

  async function sendCode(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const email = String(new FormData(e.currentTarget).get('email'))
    setBusy(true)
    setNotice(null)
    const r = await post('/api/login/code', { email })
    setBusy(false)
    if (!r.ok) {
      setNotice({ text: (await r.json()).detail ?? 'Could not send a code', kind: 'error' })
      return
    }
    setCodeSentTo(email)
  }

  async function login(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    setBusy(true)
    setNotice(null)
    const r = await post('/api/login', { email: codeSentTo, code: form.get('code') })
    setBusy(false)
    if (!r.ok) {
      setNotice({ text: (await r.json()).detail ?? 'Sign-in failed', kind: 'error' })
      return
    }
    setCodeSentTo(null)
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
      setNotice({ text: `Synced ${body.annotations} annotations, ${body.sites} cameras.`, kind: 'info' })
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

  const labeled = cameras.filter((c) => c.flags.some((f) => f.ok)).length

  return (
    <>
      <header className="topbar">
        <h1>CamTrap Measure</h1>
        {build && (
          <span className="version" title="The version this computer runs; the launcher updates it at every start">
            v{build.version}{build.commit && ` (${build.commit})`}
          </span>
        )}
        <div className="spacer" />
        {status?.signed_in && (
          <>
            <span className="small muted">{status.email}</span>
            <button className="btn" onClick={logout}>Sign out</button>
          </>
        )}
      </header>
      <main className="page">
        {notice && <p className={`notice notice-${notice.kind}`}>{notice.text}</p>}
        {!status ? (
          !notice && <p className="muted">Connecting to engine…</p>
        ) : !status.signed_in ? (
          <>
            {loading && (
              <section className="card">
                <ModelsLine inf={status.inference} />
              </section>
            )}
            {codeSentTo === null ? (
              <form key="email" onSubmit={sendCode} className="card center">
                <h2>Sign in</h2>
                <p className="muted small">Use your FlagLabel account: a one-time code is emailed to you.</p>
                <input name="email" type="email" placeholder="Email" required autoFocus />
                <button type="submit" className="btn btn-primary" disabled={busy}>
                  {busy ? 'Sending…' : 'Email me a code'}
                </button>
              </form>
            ) : (
              <form key="code" onSubmit={login} className="card center">
                <h2>Enter the code</h2>
                <p className="muted small">Sent to {codeSentTo} — check the spam folder if it takes a minute.</p>
                <input name="code" inputMode="numeric" autoComplete="one-time-code" placeholder="Code from the email" required autoFocus />
                <button type="submit" className="btn btn-primary" disabled={busy}>
                  {busy ? 'Signing in…' : 'Sign in'}
                </button>
                <button type="button" className="btn" onClick={() => setCodeSentTo(null)} disabled={busy}>
                  Use a different email
                </button>
              </form>
            )}
          </>
        ) : (
          <>
            <section className="card">
              <div className="card-head">
                <h2>Cameras</h2>
                <span className="small muted">
                  Last sync: {when(status.last_sync)} · {status.annotations} flag photos · {labeled}/{cameras.length} cameras with a labeled flag photo
                </span>
                <div className="spacer" />
                <button className="btn btn-primary" onClick={sync} disabled={busy}>
                  {busy ? 'Syncing…' : 'Sync'}
                </button>
              </div>
              <ModelsLine inf={status.inference} />
            </section>
            <RunPanel cameras={cameras} methods={methods} ready={status.inference.status === 'ready'} pollKey={pollKey} onDone={(site) => setFocus((f) => ({ site, n: f.n + 1 }))} />
            <ResultsPanel sites={cameras.map((c) => c.site)} focus={focus} />
          </>
        )}
      </main>
    </>
  )
}

import { useCallback, useEffect, useState, type FormEvent } from 'react'

type Status = {
  signed_in: boolean
  email: string | null
  last_sync: string | null
  annotations: number
  sites: number
}
type SyncResult =
  | { ok: true; last_sync: string; annotations: number; sites: number }
  | { ok: false; offline: true; last_sync: string | null }
type Calibration = {
  image_name: string
  captured_at: string | null
  window_end: string | null
  ok: boolean
  reason: string | null
}
type Camera = { site: string; verdict: 'green' | 'red'; reason: string | null; calibrations: Calibration[] }
type Run = {
  folder: string
  site: string
  method: string
  status: 'running' | 'done' | 'error'
  total: number
  done: number
  held: number
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

function RunPanel({ methods }: { methods: Record<string, string> }) {
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)
  const running = run?.status === 'running'

  const poll = () => fetch('/api/run').then((r) => r.json()).then(setRun).catch(() => {}) // engine down: App's refresh says so

  useEffect(() => void poll(), [])
  useEffect(() => {
    if (!running) return
    const id = setInterval(poll, 1000)
    return () => clearInterval(id)
  }, [running])

  async function start(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    setError(null)
    const r = await post('/api/run', { folder: form.get('folder'), method: form.get('method') })
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
      <form onSubmit={start} style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <input name="folder" placeholder="Photo folder named after the camera, e.g. D:\photos\TON_CAM02" required style={{ flex: 1, minWidth: 320 }} />
        <select name="method" defaultValue="md">
          {Object.entries(methods).map(([k, label]) => (
            <option key={k} value={k}>{label}</option>
          ))}
        </select>
        <button type="submit" disabled={running}>{running ? 'Running…' : 'Measure'}</button>
      </form>
      {error && <p style={{ color: 'crimson' }}>{error}</p>}
      {run && (
        <div style={{ marginTop: '1rem' }}>
          <progress value={run.done} max={run.total} style={{ width: '100%' }} />
          <p>
            {run.site} · {run.done}/{run.total} photos · {run.detections} animals · {run.held} held
            {running && run.eta_s !== null && ` · about ${duration(run.eta_s)} left`}
            {run.status === 'done' && ` · finished in ${duration(run.elapsed_s)}`}
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

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [cameras, setCameras] = useState<Camera[]>([])
  const [methods, setMethods] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState<{ text: string; kind: 'info' | 'warn' | 'error' } | null>(null)
  const [busy, setBusy] = useState(false)

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
  }, [refresh])

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
      setNotice({ text: `Synced ${body.annotations} annotations, ${body.sites} cameras.`, kind: 'info' })
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
      <h1>CamTrap Measure</h1>
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
          <RunPanel methods={methods} />
        </>
      )}
    </main>
  )
}

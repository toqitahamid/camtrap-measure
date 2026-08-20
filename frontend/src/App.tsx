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

const post = (url: string, body?: unknown) =>
  fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'never')

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [notice, setNotice] = useState<{ text: string; kind: 'info' | 'warn' | 'error' } | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(
    () =>
      fetch('/api/status')
        .then((r) => r.json())
        .then(setStatus)
        .catch((e) => setNotice({ text: `Engine unreachable: ${e}`, kind: 'error' })),
    [],
  )
  useEffect(() => void refresh(), [refresh])

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
      setNotice({ text: `Offline — using data from last sync ${when(body.last_sync)}.`, kind: 'warn' })
    }
    await refresh()
  }

  async function logout() {
    await post('/api/logout')
    setNotice(null)
    await refresh()
  }

  const color = { info: 'seagreen', warn: 'darkorange', error: 'crimson' }

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: '2rem', maxWidth: 520 }}>
      <h1>CamTrap Measure</h1>
      {notice && <p style={{ color: color[notice.kind] }}>{notice.text}</p>}
      {!status ? (
        !notice && <p>Connecting to engine…</p>
      ) : !status.signed_in ? (
        <form onSubmit={login} style={{ display: 'grid', gap: '0.5rem' }}>
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
            Last sync: {when(status.last_sync)} · {status.annotations} annotations · {status.sites}{' '}
            cameras
          </p>
        </>
      )}
    </main>
  )
}

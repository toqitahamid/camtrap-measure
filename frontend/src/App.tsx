/* The shell: the rail, the three bars, and the one piece of state every section shares — which camera,
   which flag photo, which folder, which method. The sections render what the engine returns; the shell
   owns nothing but the scope, the folder listing and the run. */

import Help, { About } from './Help'
import Icon from './Icon'
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'

import Measure from './Measure'
import RangeScene from './RangeScene'
import Density from './Density'
import Results from './Results'
import TableView from './TableView'
import {
  duration,
  plural,
  post,
  when,
  type Camera,
  type Folder,
  type Methods,
  type Run,
  type Inference,
  type Scope,
  type Status,
} from './ui'

/* The two bottom bars say one thing: what the app is doing right now, or what went wrong. The version,
   the models, the graphics card and what is loaded live in the header's About panel (2026-09-29): a
   technician reads this bar to know the run is alive, not to debug it. */

/** The plain sentence for a run's current stage. */
const doing = (phase: string): string => {
  if (phase === 'loading the models') return 'Loading models…'
  if (phase === 'finding animals') return 'Finding animals'
  if (phase === 'measuring distances') return 'Measuring distances'
  if (phase === 'finished') return 'Finishing up…'
  return 'Measuring'
}

/** The card's own name, the answer to "is it really using the GPU". '' when the engine named neither. */
const card = (inf: Inference): string => inf.gpu ?? inf.device ?? ''

/** What a camera with no labelled flag photo says when hovered. */
const NOT_LABELLED = 'Label its flag photo in FlagLabel, then press Sync.'

type Section = 'measure' | 'table' | 'results' | 'density'
const SECTIONS: { id: Section; label: string; icon: 'measure' | 'table' | 'results' | 'density' }[] = [
  { id: 'measure', label: 'MEASURE', icon: 'measure' },
  { id: 'table', label: 'TABLE', icon: 'table' },
  { id: 'results', label: 'RESULTS', icon: 'results' },
  { id: 'density', label: 'DENSITY', icon: 'density' },
]

const initials = (email: string | null) =>
  (email ?? '?')
    .split('@')[0]
    .split(/[._-]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('') || '?'

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [cameras, setCameras] = useState<Camera[]>([])
  const [methods, setMethods] = useState<Methods>({ default: '', methods: {} })
  const [build, setBuild] = useState<{ version: string; commit: string | null } | null>(null)
  // 'done' is a notification: something finished, here is what it did, and it takes itself away again.
  // 'warn' and 'error' stay until something replaces them - they are things to read and act on.
  const [notice, setNotice] = useState<{ text: string; kind: 'warn' | 'error' | 'done' } | null>(null)
  const [busy, setBusy] = useState(false)
  const [codeSentTo, setCodeSentTo] = useState<string | null>(null)
  const copyRef = useRef<HTMLDivElement>(null) // the sign-in text; the scene's horizon sits under it

  const [section, setSection] = useState<Section>('measure')
  // RESULTS and DENSITY add up what was measured: they bring their own filters, not the measuring bar
  const summing = section === 'results' || section === 'density'
  const [picked, setPicked] = useState<Scope>({ site: '', flag: '', folder: '', method: '' })
  const [typedPath, setTypedPath] = useState('') // only reachable where there is no native folder dialog
  const [pickable, setPickable] = useState(true) // until a pick says this window has no native dialog
  const [listing, setListing] = useState<{ of: string; data: Folder } | null>(null)
  const [folderError, setFolderError] = useState<string | null>(null)
  const [stale, setStale] = useState(0) // bumped when a run or a sync makes the listing out of date
  const [rerun, setRerun] = useState(false)
  const [run, setRun] = useState<Run | null>(null)
  const [focus, setFocus] = useState<string | null>(null) // a row the table handed to the measure section

  const usable = cameras.filter((c) => c.flags.some((f) => f.ok))
  const cam = usable.find((c) => c.site === picked.site) ?? usable[0]
  const flags = cam?.flags ?? []
  // What the window actually acts on: what was picked, corrected to something that exists as the lists
  // load. Derived rather than stored — storing it would mean writing state back from an effect on every sync.
  const scope: Scope = {
    site: cam?.site ?? '',
    flag: flags.some((f) => f.ok && f.image_name === picked.flag)
      ? picked.flag
      : (flags.find((f) => f.ok)?.image_name ?? ''),
    folder: picked.folder,
    method: methods.methods[picked.method] ? picked.method : methods.default,
  }
  const of = [scope.folder, scope.site, scope.flag, scope.method].join('\u0000')
  // only ever show a listing that was fetched for the scope now on screen, never the previous camera's
  const folder = listing && listing.of === of ? listing.data : null

  const refresh = useCallback(
    () =>
      Promise.all([fetch('/api/status').then((r) => r.json()), fetch('/api/cameras').then((r) => r.json())])
        .then(([s, c]: [Status, Camera[]]) => {
          setStatus(s)
          setCameras(c)
        })
        .catch((e) => setNotice({ text: `The app is not answering. Restart it. (${e})`, kind: 'error' })),
    [],
  )
  useEffect(() => {
    void refresh()
    fetch('/api/methods').then((r) => r.json()).then(setMethods).catch(() => {})
    fetch('/api/health').then((r) => r.json()).then(setBuild).catch(() => {})
  }, [refresh])

  const loading = status?.inference.status === 'loading'
  useEffect(() => {
    if (!loading) return
    const id = setInterval(refresh, 1000) // the weights download reports through /api/status
    return () => clearInterval(id)
  }, [loading, refresh])

  // listing a folder is a full scan of it plus a read of every unmeasured file, so a typed path waits
  // until the typing stops; Browse… arrives whole and settles on the next tick anyway
  useEffect(() => {
    const id = setTimeout(() => setPicked((s) => ({ ...s, folder: typedPath.trim() })), 400)
    return () => clearTimeout(id)
  }, [typedPath])

  const { site, flag, folder: path, method } = scope
  useEffect(() => {
    if (!path || !site || !flag || !method) return
    let live = true // a slower answer for a folder the user has already left must not land
    const q = new URLSearchParams({ path, site, flag, method })
    fetch(`/api/folder?${q}`)
      .then(async (r) => {
        if (!live) return
        if (!r.ok) {
          setFolderError((await r.json()).detail ?? `Could not read that folder (${r.status})`)
          return
        }
        setFolderError(null)
        setListing({ of: [path, site, flag, method].join('\u0000'), data: await r.json() })
      })
      .catch((e) => live && setFolderError(`The app is not answering. Restart it. (${e})`))
    return () => {
      live = false
    }
  }, [path, site, flag, method, stale])

  // A report of something already finished should not sit on screen until the next click clears it
  // (reported 2026-08-25). Anything still worth reading - a warning, an error - stays.
  useEffect(() => {
    if (notice?.kind !== 'done') return
    const id = setTimeout(() => setNotice(null), 6000)
    return () => clearTimeout(id)
  }, [notice])

  const running = run?.status === 'running'
  useEffect(() => {
    if (!running) return
    const poll = () => fetch('/api/run').then((r) => r.json()).then(setRun).catch(() => {})
    const id = setInterval(poll, 1000)
    return () => {
      clearInterval(id)
      setStale((n) => n + 1) // the run left the running state: what is on screen is now out of date
    }
  }, [running])

  /** Measure exactly these photos; an empty list means the whole folder under the re-measure rule. */
  async function measure(paths: string[]) {
    setNotice(null)
    const r = await post('/api/run', {
      folder: scope.folder,
      site: scope.site,
      flag: scope.flag,
      method: scope.method,
      rerun,
      photos: paths.length ? paths : undefined,
    })
    if (!r.ok) {
      setNotice({ text: (await r.json()).detail ?? `Could not start (${r.status})`, kind: 'error' })
      return
    }
    setRun(await r.json())
  }

  /** Forget measurements: one photo, or every photo of one camera. Nothing on disk is touched. */
  async function clearResults(what: { path?: string; site?: string; everything?: boolean }) {
    setNotice(null)
    const q = new URLSearchParams(
      Object.entries(what).map(([k, v]) => [k, String(v)]) as [string, string][],
    )
    const r = await post(`/api/results/clear?${q}`)
    if (!r.ok) {
      setNotice({ text: (await r.json()).detail ?? `Could not clear (${r.status})`, kind: 'error' })
      return
    }
    const done: { photos: number; detections: number } = await r.json()
    setNotice({ text: `Cleared ${plural(done.photos, 'photo')} \u00b7 ${plural(done.detections, 'measurement')}`, kind: 'done' })
    setStale((n) => n + 1) // the listing and the results on screen are now out of date
  }

  async function browse() {
    setNotice(null)
    const r = await post('/api/folder/pick')
    const body: { folder: string | null; reason: string | null } = await r.json()
    if (body.folder) {
      setTypedPath(body.folder)
      return
    }
    if (body.reason?.includes('cannot open')) setPickable(false) // no native dialog here: fall back to typing
    if (body.reason) setNotice({ text: body.reason, kind: 'warn' })
  }

  async function sync() {
    setBusy(true)
    setNotice(null)
    const r = await post('/api/sync')
    setBusy(false)
    if (!r.ok) {
      setNotice({ text: (await r.json()).detail ?? `Sync failed (${r.status})`, kind: 'error' })
      await refresh()
      return
    }
    const body = await r.json()
    if (!body.ok) setNotice({ text: `Offline. Using the flag photos from ${when(body.last_sync)}.`, kind: 'warn' })
    setStale((n) => n + 1)
    await refresh()
  }

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
    const code = String(new FormData(e.currentTarget).get('code'))
    setBusy(true)
    setNotice(null)
    const r = await post('/api/login', { email: codeSentTo, code })
    setBusy(false)
    if (!r.ok) {
      setNotice({ text: (await r.json()).detail ?? 'Sign-in failed', kind: 'error' })
      return
    }
    setCodeSentTo(null)
    await refresh()
  }

  if (!status) return <p className="empty dim">{notice ? notice.text : 'Starting…'}</p>

  if (!status.signed_in) {
    return (
      <div className="signin">
        <div className="brand">
          <RangeScene below={copyRef} />
          <div className="row" style={{ gap: 11 }}>
            <span style={{ color: 'var(--amber)', display: 'flex' }}>
              <Icon name="mark" size={26} width={1.6} />
            </span>
            <span className="wordmark" style={{ fontSize: 15 }}>CAMTRAP MEASURE</span>
          </div>
          <div className="brand-copy" ref={copyRef}>
            <h1>How far away<br />was that deer?</h1>
            <p className="dim" style={{ marginTop: 20, fontSize: 15, lineHeight: 1.65 }}>
              Choose a folder of camera-trap photos. The app finds each deer and tells you how far away it was,
              using the flag photo you labelled in FlagLabel.
            </p>
          </div>
          <div className="tiny brand-foot">
            <span>BASE Lab · Center for Wildlife Sustainability Research</span>
            <span className="foot-sep"> · </span>
            <span>Southern Illinois University Carbondale</span>
          </div>
        </div>

        <div className="form">
          <div className="signin-card">
            {/* two bars: which step of the two this is */}
            <div className="steps" aria-hidden="true">
              <span className="on" />
              <span className={codeSentTo === null ? '' : 'on'} />
            </div>
            {codeSentTo === null ? (
              <form key="email" onSubmit={sendCode}>
                <div className="cap">Step 1 of 2</div>
                <h2 className="grot" style={{ margin: '9px 0 0', fontSize: 26, letterSpacing: '-0.02em' }}>Sign in</h2>
                <p className="dim small" style={{ margin: '10px 0 0', lineHeight: 1.6 }}>
                  Use your FlagLabel email. We send you a code, no password needed.
                </p>
                {notice && <p className={`notice notice-${notice.kind}`} style={{ marginTop: 18 }}>{notice.text}</p>}
                <label className="cap" style={{ display: 'block', margin: '24px 0 7px' }}>Email</label>
                <input className="input" name="email" type="email" placeholder="you@siu.edu" required autoFocus />
                <button type="submit" className="btn btn-amber btn-wide" style={{ height: 40, marginTop: 14, fontSize: 14 }} disabled={busy}>
                  {busy ? 'Sending…' : 'Email me a code'}
                </button>
              </form>
            ) : (
              <form key="code" onSubmit={login}>
                <div className="cap">Step 2 of 2</div>
                <h2 className="grot" style={{ margin: '9px 0 0', fontSize: 26, letterSpacing: '-0.02em' }}>Enter the code</h2>
                <p className="dim small" style={{ margin: '10px 0 0', lineHeight: 1.6 }}>
                  Sent to {codeSentTo}. Check the spam folder if it takes a minute.
                </p>
                {notice && <p className={`notice notice-${notice.kind}`} style={{ marginTop: 18 }}>{notice.text}</p>}
                <label className="cap" style={{ display: 'block', margin: '24px 0 7px' }}>Code from the email</label>
                <input className="input mono" name="code" inputMode="numeric" autoComplete="one-time-code" required autoFocus
                       style={{ letterSpacing: '0.4em', fontSize: 17 }} />
                <button type="submit" className="btn btn-amber btn-wide" style={{ height: 40, marginTop: 14, fontSize: 14 }} disabled={busy}>
                  {busy ? 'Signing in…' : 'Sign in'}
                </button>
                <button type="button" className="btn btn-wide" style={{ marginTop: 8 }} onClick={() => setCodeSentTo(null)} disabled={busy}>
                  Use a different email
                </button>
              </form>
            )}
            </div>
        </div>
      </div>
    )
  }

  const shownError = path && site && flag && method ? folderError : null
  const inf = status.inference
  const measured = folder ? folder.rows.filter((r) => r.measured).length : 0
  const flagged = folder ? folder.rows.filter((r) => r.reasons.length > 0).length : 0
  const ready = inf.status === 'ready'
  // Just when: that is what decides whether to press Sync. The counts are in About.
  const syncNote = status.last_sync
    ? `Synced ${new Date(status.last_sync).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })}`
    : 'Not synced yet'
  const about: [string, ReactNode][] = [
    ['Version', build ? `v${build.version}${build.commit ? ` (${build.commit})` : ''}` : 'unknown'],
    ['Models', inf.backend === 'real' ? (inf.weights ?? 'unknown') : 'none installed, numbers are made up'],
    ['Graphics card', card(inf) || 'unknown'],
    ['Loaded now', inf.status === 'loading' ? 'loading…' : inf.loaded?.length ? inf.loaded.join(', ') : 'nothing, they load when you press Measure'],
    ['Settings', inf.fidelity === 'fast' ? 'quick, not the published settings' : 'published settings'],
    ['Last sync', when(status.last_sync)],
    ['Flag photos', String(status.annotations)],
    ['Cameras labelled', `${usable.length} of ${cameras.length}`],
  ]

  return (
    <div className="app">
      <div className="body">
        <header className="topbar">
          <span style={{ color: 'var(--amber)', display: 'flex' }}><Icon name="mark" size={19} width={1.7} /></span>
          <span className="wordmark">CAMTRAP MEASURE</span>

          <div className="tabs">
            {SECTIONS.map((t) => (
              <button key={t.id} className="tab" aria-current={section === t.id}
                      onClick={() => {
                        setFocus(null) // coming back by the tab resumes where you were, not the row the table opened
                        setSection(t.id)
                      }}
                      disabled={t.id !== section && t.id === 'table' && folder === null}>
                <Icon name={t.icon} size={13} width={2} />
                {t.label}
              </button>
            ))}
          </div>

          <div className="spacer" />
          <span className="tiny sync ellipsis" style={{ color: 'var(--faint)' }} title={syncNote}>
            {syncNote}
          </span>
          <button className="btn" onClick={sync} disabled={busy}>
            <Icon name="sync" size={13} />
            {busy ? 'Syncing…' : 'Sync'}
          </button>
          <Help topic="sync" align="right" />
          <About rows={about} />
          <div className="sep" style={{ margin: '12px 2px' }} />
          <button className="rail-foot" title={`${status.email}. Sign out`}
                  onClick={() => post('/api/logout').then(refresh)}>
            {initials(status.email)}
          </button>
        </header>

        {!summing && (
          <div className="ctxbar">
            {/* width is what each field would like; minWidth is what it must keep to stay readable —
                the bar wraps to a second row before anything is squeezed past it */}
            <label className="field" style={{ width: 152, minWidth: 116 }}>
              <span className="cap">Camera <Help topic="camera" /></span>
              <span className="field-val">
                <select className="bare" value={scope.site} onChange={(e) => setPicked((s) => ({ ...s, site: e.target.value }))}
                        disabled={cameras.length === 0}>
                  {cameras.length === 0 && <option value="">Sync first</option>}
                  {cameras.length > 0 && usable.length === 0 && <option value="">No camera labelled yet</option>}
                  {usable.map((c) => <option key={c.site} value={c.site}>{c.site}</option>)}
                  {/* Listed, not hidden: someone looking for a camera must learn why it cannot be picked. Its flag
                      photo is labelled in FlagLabel, never here, because this app only reads the cloud. */}
                  {usable.length < cameras.length && (
                    <optgroup label="Not labelled yet. Label in FlagLabel, then press Sync">
                      {cameras.filter((c) => !usable.includes(c)).map((c) => (
                        <option key={c.site} value={c.site} disabled title={NOT_LABELLED}>
                          {c.site}, not labelled yet
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
                <span className="chev"><Icon name="down" size={12} width={2.4} /></span>
              </span>
            </label>
            <div className="sep" />

            <label className="field" style={{ width: 216, minWidth: 150 }}>
              <span className="cap">Flag photo <Help topic="flag" /></span>
              <span className="field-val">
                <span style={{ color: 'var(--amber)', display: 'flex' }}><Icon name="flag" size={13} width={1.8} /></span>
                <select className="bare" style={{ fontSize: 12 }} value={scope.flag}
                        onChange={(e) => setPicked((s) => ({ ...s, flag: e.target.value }))} disabled={flags.length === 0}>
                  {flags.length === 0 && <option value="">None</option>}
                  {flags.map((f) => (
                    <option key={f.image_name} value={f.image_name} disabled={!f.ok} title={f.reason ?? undefined}>
                      {f.image_name}{f.captured_at ? ` · ${new Date(f.captured_at).toLocaleDateString()}` : ''}
                      {f.ok ? '' : ', not usable'}
                    </option>
                  ))}
                </select>
                <span className="chev"><Icon name="down" size={12} width={2.4} /></span>
              </span>
            </label>
            <div className="sep" />

            <div className="field" style={{ flex: 1, minWidth: 210, maxWidth: 380 }}>
              <span className="cap">Photo folder <Help topic="folder" /></span>
              <span className="field-val">
                {/* picked, never typed — except where there is no native dialog to pick with, which is
                    the browser and `--no-window`; `pickable` only goes false once a pick has said so. */}
                {pickable ? (
                  <span className={`path ellipsis${scope.folder ? '' : ' faint'}`} title={scope.folder || undefined}>
                    {scope.folder || 'No folder chosen'}
                  </span>
                ) : (
                  <input className="path" value={typedPath} placeholder="Type or paste the folder" spellCheck={false}
                         onChange={(e) => setTypedPath(e.target.value)} />
                )}
                <button className="btn btn-sm" onClick={browse} title="Choose the folder that holds this camera's photos">
                  <Icon name="folder" size={12} width={1.8} />
                  {scope.folder ? 'Change…' : 'Browse…'}
                </button>
              </span>
            </div>
            <div className="sep" />

            <label className="field" style={{ width: 200, minWidth: 176 }}>
              <span className="cap">Distance read at <Help topic="method" /></span>
              <span className="field-val">
                <select className="bare" value={scope.method} title={methods.methods[scope.method]?.hint}
                        onChange={(e) => setPicked((s) => ({ ...s, method: e.target.value }))}>
                  {Object.entries(methods.methods).map(([k, m]) => <option key={k} value={k}>{m.label}</option>)}
                </select>
                <span className="chev"><Icon name="down" size={12} width={2.4} /></span>
              </span>
            </label>

            <div className="spacer" />
            <label className="check tiny" style={{ alignItems: 'center' }}>
              <input type="checkbox" checked={rerun} onChange={(e) => setRerun(e.target.checked)} />
              Redo measured photos
              <Help topic="rerun" align="right" />
            </label>
            {running ? (
              <button className="btn btn-danger" onClick={() => post('/api/run/cancel')}>
                <Icon name="stop" size={14} width={2.1} />
                Stop
              </button>
            ) : (
              <button className="btn btn-amber" onClick={() => measure([])} disabled={!ready || !folder || folder.total === 0}>
                <Icon name="measure" size={14} width={2.1} />
                Measure all{folder ? ` ${folder.total}` : ''}
              </button>
            )}
          </div>
        )}

        {notice && notice.kind !== 'done' && !summing && (
          <p className={`notice notice-${notice.kind}`} style={{ margin: '10px 14px 0' }}>{notice.text}</p>
        )}

        <div className={summing ? 'body' : 'work'}>
          {section === 'measure' && (
            <Measure scope={scope} folder={folder} methods={methods} busy={running || !ready} running={running}
              onClear={clearResults}
                     onMeasure={measure} focus={focus} error={shownError} />
          )}
          {section === 'table' && (
            <TableView scope={scope} folder={folder} methods={methods} busy={running || !ready} onMeasure={measure}
                       error={shownError} onOpen={(p) => { setFocus(p); setSection('measure') }} />
          )}
          {section === 'results' && (
            <Results site={scope.site} cameras={cameras} folder={scope.folder}
              onClear={clearResults} />
          )}
          {section === 'density' && (
            <Density site={scope.site} sites={cameras.map((c) => c.site)} folder={scope.folder} />
          )}
        </div>

        {notice?.kind === 'done' && (
          <div className="toast" role="status" onClick={() => setNotice(null)} title="Dismiss">
            <Icon name="check" size={13} width={2.4} />
            {notice.text}
          </div>
        )}

        {running && run ? (
          <div className="runbar">
            <div className="track">
              <div style={{ width: `${(100 * (run.phase_total ? run.phase_done / run.phase_total : run.done / Math.max(1, run.total)))}%` }} />
            </div>
            <div className="line">
              <span className="spin" style={{ color: 'var(--amber)', display: 'flex' }}>
                <Icon name="spinner" size={14} width={2.2} />
              </span>
              {/* the stage, not just "measuring": the detector looks at every photo before a single
                  distance is read, and on a full card that first pass is most of the wait */}
              <span style={{ fontWeight: 500 }}>{doing(run.phase)}</span>
              <span style={{ color: 'var(--text-2)' }}>
                {run.phase_total ? `${run.phase_done} / ${run.phase_total}` : `${run.done} / ${run.total}`} photos
              </span>
              <span style={{ color: 'var(--line)' }}>·</span>
              <span className="dim">{plural(run.detections, 'animal')}</span>
              {run.eta_s !== null && (
                <>
                  <span style={{ color: 'var(--line)' }}>·</span>
                  <span className="dim">about {duration(run.eta_s)} left</span>
                </>
              )}
              <div className="spacer" />
              {inf.backend !== 'real' && <span className="warn tiny">Test mode: made-up numbers</span>}
              {inf.fidelity === 'fast' && <span className="warn tiny">⚠ Quick settings are on. See About.</span>}
            </div>
          </div>
        ) : (
          <footer className="statusbar">
            {inf.status === 'loading' ? (
              <>
                <span className="spin" style={{ color: 'var(--amber)', display: 'flex' }}>
                  <Icon name="spinner" size={12} width={2.2} />
                </span>
                <span>
                  {inf.download
                    ? `Downloading models, ${inf.download.done_gb.toFixed(1)} of ${inf.download.total_gb.toFixed(1)} GB. One time only.`
                    : 'Loading models…'}
                </span>
              </>
            ) : inf.status === 'error' ? (
              <>
                <span className="warn" style={{ display: 'flex' }}><Icon name="warn" size={12} /></span>
                <span className="warn">The models could not load: {inf.error}</span>
              </>
            ) : (
              <>
                <span className="dot" style={{ color: 'var(--ok)' }} />
                <span>Ready</span>
                <Help topic="models" />
                {/* the published settings are the default; when they are not in use it must be on screen */}
                {inf.fidelity === 'fast' && <span className="warn">⚠ Quick settings are on. See About.</span>}
                {inf.warning && <span className="warn">⚠ {inf.warning}</span>}
              </>
            )}
            <div className="spacer" />
            {run?.status === 'error' && <span className="warn">Measuring failed: {run.error}</span>}
            {folder && (
              <>
                <span>{measured} of {folder.total} measured</span>
                {flagged > 0 && (
                  <>
                    <span style={{ color: 'var(--line)' }}>·</span>
                    <span style={{ color: 'var(--bad)' }}>{plural(flagged, 'photo')} need a look</span>
                  </>
                )}
                {folder.unreadable > 0 && (
                  <>
                    <span style={{ color: 'var(--line)' }}>·</span>
                    <span>{plural(folder.unreadable, 'unreadable file')}</span>
                  </>
                )}
              </>
            )}
          </footer>
        )}
      </div>
    </div>
  )
}

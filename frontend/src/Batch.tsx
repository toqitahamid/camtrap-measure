/* MEASURE for a site folder (ticket 27): every camera folder in it, checked before anything is measured, then
   measured in one go, then what each camera added up to. The engine matches the names, reads the stamps, picks
   each photo's flag photo by date and holds every choice; this section renders its JSON and posts the clicks. */

import Help from './Help'
import Icon from './Icon'
import { useEffect, useState, type ReactNode } from 'react'
import {
  NONE,
  flagSrc,
  about,
  photoSrc,
  plural,
  post,
  thousands,
  visitDay,
  type Comparison,
  type Run,
  type RunCamera,
  type Site,
  type SiteChange,
  type SiteRow,
  type SiteState,
} from './ui'

/** What TABLE opens on: the needs-a-look filter, or one camera folder's photos. */
export type TablePreset = { filter?: 'all' | 'new' | 'flagged'; find?: string }

type Props = {
  site: SiteState
  run: Run | null
  running: boolean
  ready: boolean // the models can be asked for: not still loading, no error
  cameras: string[] // every camera with a usable flag photo, for the camera menu
  rerun: boolean
  onRerun: (on: boolean) => void
  onChoose: (folder: string, change: SiteChange) => void
  onTickAll: (on: boolean) => void
  onMeasure: () => void
  onCancel: () => void
  onStop: () => void
  onFlagLabel: () => void
  onResults: () => void
  onTable: (preset: TablePreset) => void
}

export default function Batch(props: Props) {
  const { site, run } = props
  // The done screen is for a run this window watched, and stays until it is put away. The id tells this run's
  // from the next one's; a run that ended before the window opened goes straight to the table.
  const [watched, setWatched] = useState<number | null>(null)
  const [closed, setClosed] = useState<number | null>(null)
  const live = run?.kind === 'site' && site.status === 'ready' && run.folder === site.folder && props.running ? run.id : null
  if (live !== null && watched !== live) setWatched(live) // state adjusted while rendering, as React documents it
  if (site.status === 'reading') {
    return (
      <div className="sheet">
        <div className="card" style={{ flex: 1 }}>
          <div className="empty">
            <span className="spin" style={{ color: 'var(--amber)' }}><Icon name="spinner" size={26} width={1.8} /></span>
            <b className="grot">Reading photo dates: {thousands(site.done)} of {thousands(site.total)}</b>
            <span className="small dim">Only the first time you open this folder.</span>
          </div>
        </div>
      </div>
    )
  }
  if (site.status !== 'ready') {
    return (
      <div className="sheet">
        <div className="card" style={{ flex: 1 }}>
          <div className="empty"><p className="notice notice-error">{site.status === 'error' ? site.error : 'Not a site folder.'}</p></div>
        </div>
      </div>
    )
  }
  const mine = run?.kind === 'site' && run.folder === site.folder && run.cameras ? run : null
  if (mine && props.running) return <Running run={mine} cameras={mine.cameras ?? []} onStop={props.onStop} />
  if (mine && watched === mine.id && closed !== mine.id) {
    return <Done run={mine} cameras={mine.cameras ?? []} onBack={() => setClosed(mine.id)}
                 onResults={props.onResults} onTable={props.onTable} />
  }
  return <Check {...props} site={site} />
}

/* ── 1. Check the cameras ─────────────────────────────────────────────────── */

function Check({ site, ready, cameras, rerun, onRerun, onChoose, onTickAll, onMeasure, onCancel, onFlagLabel }: Props & { site: Site }) {
  const [comparing, setComparing] = useState<SiteRow | null>(null)
  const attention = site.rows.filter((r) => r.group === 'attention')
  const fine = site.rows.filter((r) => r.group === 'ready')
  const { cameras: n, photos, measured } = site.ticked
  const toMeasure = rerun ? photos : photos - measured
  const c = site.counts
  return (
    <div className="sheet" style={{ overflow: 'auto' }}>
      <div className="card batch" style={{ flex: 1, minHeight: 'auto' }}>
        <div className="batch-head">
          <h2>Site folder: {plural(site.rows.length, 'camera folder')} found</h2>
          <Help topic="site" />
          <div className="spacer" />
          {c.check > 0 && <span className="badge badge-warn">{c.check} to check</span>}
          {c.cannot > 0 && <span className="badge badge-bad">{c.cannot} cannot be measured</span>}
          {c.ready > 0 && <span className="badge badge-ok">{c.ready} ready</span>}
          {c.skipped > 0 && <span className="badge">{c.skipped} skipped</span>}
        </div>

        {attention.length > 0 && (
          <>
            <div className="group"><b>Needs your attention</b></div>
            <Rows rows={attention} cameras={cameras} onChoose={onChoose} onCompare={setComparing} onFlagLabel={onFlagLabel} head />
          </>
        )}
        {fine.length > 0 && (
          <>
            <div className="group">
              <b>Ready</b><span>{plural(fine.length, 'camera')}</span>
              <div className="spacer" />
              <button className="link" onClick={() => onTickAll(true)}>Tick all</button>
              <button className="link" onClick={() => onTickAll(false)}>Tick none</button>
            </div>
            <Rows rows={fine} cameras={cameras} onChoose={onChoose} onCompare={setComparing} onFlagLabel={onFlagLabel}
                  head={attention.length === 0} />
          </>
        )}
        {site.skipped.length > 0 && (
          <div className="group">
            <b>Skipped</b>
            <span>{site.skipped.map((s) => `${s.name} (${s.why})`).join(', ')}</span>
          </div>
        )}

        <div className="batch-foot">
          <div>
            <div className="big">Measure {plural(n, 'camera')} · {thousands(photos)} {photos === 1 ? 'photo' : 'photos'}</div>
            <div className="small dim">
              {n === 0
                ? 'Tick the cameras to measure.'
                : `${about(toMeasure * site.pace_s)}.${!rerun && measured ? ` ${plural(measured, 'photo')} already measured ${measured === 1 ? 'is' : 'are'} skipped.` : ''} You can stop at any time and carry on later.`}
            </div>
          </div>
          <div className="spacer" />
          <label className="check" style={{ alignItems: 'center' }}>
            <input type="checkbox" checked={rerun} onChange={(e) => onRerun(e.target.checked)} />
            Redo measured photos too
          </label>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn btn-amber" disabled={!ready || n === 0} onClick={onMeasure}>
            <Icon name="measure" size={14} width={2.1} />
            Measure ticked
          </button>
        </div>
      </div>
      {comparing && (
        <CompareDialog site={site} row={comparing} onClose={() => setComparing(null)}
                       onChoose={(change) => {
                         onChoose(comparing.folder, change)
                         setComparing(null)
                       }} />
      )}
    </div>
  )
}

function Rows({ rows, cameras, onChoose, onCompare, onFlagLabel, head }: {
  rows: SiteRow[]
  cameras: string[]
  onChoose: Props['onChoose']
  onCompare: (r: SiteRow) => void
  onFlagLabel: () => void
  head: boolean
}) {
  return (
    <table className="btable">
      <colgroup>
        <col style={{ width: 40 }} /><col style={{ width: '15%' }} /><col style={{ width: '15%' }} />
        <col /><col style={{ width: '8%' }} /><col style={{ width: '30%' }} />
      </colgroup>
      {head && (
        <thead>
          <tr><th /><th>Folder</th><th>Camera</th><th>Flag photo, chosen by date <Help topic="byDate" /></th>
            <th className="num">Photos</th><th>Check</th></tr>
        </thead>
      )}
      <tbody>
        {rows.map((r) => (
          <tr key={r.folder} className={r.warnings.length ? 'warnrow' : r.tickable ? undefined : 'off'}>
            <td>
              <input type="checkbox" checked={r.ticked} disabled={!r.tickable} aria-label={`Measure ${r.name}`}
                     onChange={(e) => onChoose(r.folder, { tick: e.target.checked })} />
            </td>
            <td className="path ellipsis" title={r.folder}>{r.name}</td>
            <td><CameraCell r={r} cameras={cameras} onChoose={onChoose} /></td>
            <td><FlagCell r={r} onChoose={onChoose} /></td>
            <td className="num">{thousands(r.photos)}</td>
            <td><CheckCell r={r} onChoose={onChoose} onCompare={onCompare} onFlagLabel={onFlagLabel} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function CameraCell({ r, cameras, onChoose }: { r: SiteRow; cameras: string[]; onChoose: Props['onChoose'] }) {
  if (r.state === 'unknown') return <span className="small">No camera with this name</span>
  if (r.state === 'unlabelled') return <span className="small">{r.camera}, not labelled yet</span>
  const others = cameras.filter((c) => !r.candidates.includes(c))
  return (
    <span className="field-val sel">
      <select className="bare" value={r.camera ?? ''} aria-label={`Camera for ${r.name}`}
              onChange={(e) => onChoose(r.folder, { camera: e.target.value })}>
        {r.camera === null && <option value="" disabled>Choose…</option>}
        {r.candidates.length > 0 && (
          <optgroup label="Fits the folder name">
            {r.candidates.map((c) => <option key={c} value={c}>{c}</option>)}
          </optgroup>
        )}
        <optgroup label={r.candidates.length ? 'Other cameras' : 'Cameras'}>
          {others.map((c) => <option key={c} value={c}>{c}</option>)}
        </optgroup>
      </select>
      <span className="chev"><Icon name="down" size={12} width={2.4} /></span>
    </span>
  )
}

function FlagCell({ r, onChoose }: { r: SiteRow; onChoose: Props['onChoose'] }) {
  if (r.state === 'unknown') return <span className="small dim">Not in FlagLabel yet. Add and label its flag photo there, then press Sync.</span>
  if (r.state === 'unlabelled') return <span className="small dim">Label its flag photo in FlagLabel, then press Sync.</span>
  if (r.state === 'ambiguous') return <span className="small dim">Choose the camera first.</span>
  return (
    <div className="flags">
      {r.flags.map((f) => (
        <span key={f.image_name}>
          <b>{visitDay(f.captured_at)}</b>
          {f.visit ? ` ${f.visit} visit` : ` ${f.image_name}`}, {r.flags.length === 1 ? `all ${thousands(f.photos)}` : thousands(f.photos)} {f.photos === 1 ? 'photo' : 'photos'}
        </span>
      ))}
      {r.options.length > 1 && (
        <span className="field-val sel sel-sm">
          <select className="bare" value={r.flag_choice} aria-label={`Flag photo for ${r.name}`}
                  onChange={(e) => onChoose(r.folder, { flag: e.target.value })}>
            <option value="">Chosen by date</option>
            {r.options.map((o) => (
              <option key={o.image_name} value={o.image_name}>
                Only {o.image_name}{o.captured_at ? `, ${visitDay(o.captured_at)}` : ''}
              </option>
            ))}
          </select>
          <span className="chev"><Icon name="down" size={11} width={2.4} /></span>
        </span>
      )}
    </div>
  )
}

function CheckCell({ r, onChoose, onCompare, onFlagLabel }: {
  r: SiteRow
  onChoose: Props['onChoose']
  onCompare: (r: SiteRow) => void
  onFlagLabel: () => void
}) {
  const says = r.stamp?.camera
  return (
    <div className="stack" style={{ gap: 4 }}>
      {r.warnings.map((w) => (
        <span key={w} className="status warn"><Icon name="warn" size={12} /> {w}</span>
      ))}
      {!r.tickable && r.state !== 'ambiguous' && <span className="status bad"><Icon name="close" size={12} width={2.4} /> Cannot be measured</span>}
      {r.tickable && r.warnings.length === 0 && <span className="status ok"><Icon name="check" size={12} width={2.4} /> Ready</span>}
      {r.measured > 0 && <span className="small dim">{thousands(r.measured)} already measured</span>}
      {r.note && <span className="small dim">{r.note}</span>}
      {r.actions.length > 0 && (
        <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 2 }}>
          {r.actions.includes('compare') && <button className="btn btn-sm" onClick={() => onCompare(r)}>Compare</button>}
          {r.actions.includes('use') && says && <button className="btn btn-sm" onClick={() => onChoose(r.folder, { camera: says })}>Use {says}</button>}
          {r.actions.includes('keep') && r.camera && <button className="btn btn-sm" onClick={() => onChoose(r.folder, { keep: r.camera ?? '' })}>Keep {r.camera}</button>}
          {r.actions.includes('flaglabel') && <button className="btn btn-sm" onClick={onFlagLabel}>Open FlagLabel</button>}
        </div>
      )}
    </div>
  )
}

/* ── The Compare dialog ───────────────────────────────────────────────────── */

function CompareDialog({ site, row, onClose, onChoose }: {
  site: Site
  row: SiteRow
  onClose: () => void
  onChoose: (change: SiteChange) => void
}) {
  // Two asks: which three photos (at once), then how well they line up (seconds: the model may have to load)
  const [what, setWhat] = useState<Comparison | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true // a closed dialog must not be filled in later
    const ask = (score: boolean) =>
      post('/api/site/compare', { path: site.folder, folder: row.folder, score }).then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail ?? `The app answered ${r.status}`)
        return (await r.json()) as Comparison
      })
    ask(false)
      .then((c) => {
        if (live) setWhat(c)
        return ask(true)
      })
      .then((c) => live && setWhat(c))
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      live = false
    }
  }, [site.folder, row.folder])
  const says = row.stamp?.camera ?? ''
  const mine = row.camera ?? ''
  const [own, other] = what?.flags ?? []
  const scored = !!what && what.flags.every((f) => f.score !== null)
  const verdict = !scored
    ? null
    : other.lines_up && !own.lines_up
      ? `The photos and the ${says} flag photo show the same view.`
      : own.lines_up && !other.lines_up
        ? `The photos and the ${mine} flag photo show the same view.`
        : own.lines_up
          ? 'Both flag photos line up. Check the stamp in the camera settings.'
          : 'Neither flag photo lines up well. Check where these photos came from.'
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-label={`Which camera took the photos in ${row.name}?`}>
        <div className="batch-head">
          <h2>Which camera took the photos in {row.name}?</h2>
          <div className="spacer" />
          <button className="btn btn-sm" onClick={onClose}>Close</button>
        </div>
        <div className="trio">
          <figure>
            {what ? <img src={photoSrc(what.photo, 'full')} alt="" /> : <div className="ph" />}
            <figcaption>
              <b>A photo from this folder</b>
              <span className="sub">{what ? `${what.name} · stamped "${what.stamp}"` : 'Choosing one…'}</span>
            </figcaption>
          </figure>
          {[own, other].map((f, i) => (
            <figure key={i} className={f?.score == null ? undefined : f.lines_up ? 'match' : 'nomatch'}>
              {f?.image_name ? <img src={flagSrc(f.site, f.image_name)} alt="" /> : <div className="ph" />}
              <figcaption>
                <b>{f?.site ?? (i ? says : mine)} flag photo</b>
                <Verdict f={f} error={error} />
              </figcaption>
            </figure>
          ))}
        </div>
        <div className="batch-foot">
          <span className="small dim">{error ?? verdict ?? 'Checking how well each flag photo lines up. The first check can take two minutes while the models load.'}</span>
          <div className="spacer" />
          <button className={`btn${scored && own.lines_up && !other.lines_up ? ' btn-amber' : ''}`} onClick={() => onChoose({ keep: mine })}>
            Keep {mine}
          </button>
          <button className={`btn${scored && own.lines_up && !other.lines_up ? '' : ' btn-amber'}`} onClick={() => onChoose({ camera: says })}>
            Use {says}
          </button>
        </div>
      </div>
    </div>
  )
}

function Verdict({ f, error }: { f: Comparison['flags'][number] | undefined; error: string | null }) {
  if (f && !f.image_name) return <span className="sub dim">Not labelled yet</span>
  if (!f || f.score === null) {
    return error ? <span className="sub dim">{NONE}</span> : <span className="sub dim"><span className="spin inline"><Icon name="spinner" size={11} /></span> Checking…</span>
  }
  return f.lines_up ? (
    <span className="sub status ok"><Icon name="check" size={12} width={2.4} /> Lines up well <span className="mono">({thousands(f.score)} points)</span></span>
  ) : (
    <span className="sub status bad"><Icon name="close" size={12} width={2.4} /> Does not line up <span className="mono">({thousands(f.score)} points)</span></span>
  )
}

/* ── 2. Measuring ─────────────────────────────────────────────────────────── */

const sum = (cams: RunCamera[], k: 'deer' | 'needs_look') => cams.reduce((n, c) => n + c[k], 0)

function Running({ run, cameras, onStop }: { run: Run; cameras: RunCamera[]; onStop: () => void }) {
  const [show, setShow] = useState(false)
  const i = run.camera_i ?? 0
  const now = cameras[i]
  const done = cameras.filter((c) => c.status === 'done')
  const waiting = cameras.filter((c) => c.status === 'waiting' && c !== now)
  return (
    <div className="sheet" style={{ overflow: 'auto' }}>
      <div className="card batch" style={{ flex: 1, minHeight: 'auto' }}>
        <div className="batch-head">
          <h2>Measuring {plural(cameras.length, 'camera')}</h2>
          <div className="spacer" />
          <button className="btn btn-danger" onClick={onStop}><Icon name="stop" size={14} width={2.1} /> Stop</button>
        </div>
        <div className="overall">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span><b>{thousands(run.done)}</b> of {thousands(run.total)} photos · camera {i + 1} of {cameras.length}</span>
            <span className="dim">{run.eta_s === null ? 'Working out the time left…' : `${about(run.eta_s)} left`}</span>
          </div>
          <div className="prog"><i style={{ width: `${(100 * run.done) / Math.max(1, run.total)}%` }} /></div>
        </div>
        {done.length > 0 && (
          <>
            <div className="group">
              <b>Done</b>
              <span>{plural(done.length, 'camera')} · {sum(done, 'deer')} deer · {sum(done, 'needs_look')} need a look</span>
              <div className="spacer" />
              <button className="link" onClick={() => setShow((s) => !s)}>{show ? 'Hide' : 'Show'}</button>
            </div>
            {show && <Summary cameras={done} />}
          </>
        )}
        {now && (
          <table className="btable">
            <thead>
              <tr><th>Now measuring</th><th>Flag photo</th><th style={{ width: '36%' }}>Progress</th>
                <th className="num">Photos</th><th className="num">Deer</th><th className="num">Needs a look</th></tr>
            </thead>
            <tbody>
              <tr>
                <td><span className="val">{now.site}</span>{now.name !== now.site && <span className="sub path">{now.name}</span>}</td>
                <td className="dim">{now.flags.map((f) => visitDay(f.captured_at)).join(', ')}</td>
                <td><div className="prog"><i style={{ width: `${(100 * now.done) / Math.max(1, now.total)}%` }} /></div></td>
                <td className="num">{thousands(now.done)} / {thousands(now.total)}</td>
                <td className="num">{now.deer}</td>
                <td className="num">{now.needs_look}</td>
              </tr>
            </tbody>
          </table>
        )}
        {waiting.length > 0 && (
          <div className="group"><b>Waiting</b><span>{plural(waiting.length, 'camera')}, starting with {waiting[0].site}</span></div>
        )}
      </div>
    </div>
  )
}

/* ── 3. Done ──────────────────────────────────────────────────────────────── */

function Summary({ cameras, onTable }: { cameras: RunCamera[]; onTable?: Props['onTable'] }) {
  return (
    <table className="btable">
      <thead>
        <tr><th>Camera</th><th className="num">Photos</th><th className="num">Deer</th><th className="num">Median distance</th>
          <th className="num">Needs a look</th>{onTable && <th />}</tr>
      </thead>
      <tbody>
        {cameras.map((c) => (
          <tr key={c.folder}>
            <td><span className="val">{c.site}</span>{c.name !== c.site && <span className="sub path">{c.name}</span>}</td>
            <td className="num">{thousands(c.photos ?? c.done)}</td>
            <td className="num">{c.deer}</td>
            <td className="num">{c.median_m === null ? NONE : `${c.median_m.toFixed(1)} m`}</td>
            <td className="num">{c.needs_look}</td>
            {onTable && (
              <td style={{ textAlign: 'right' }}>
                <button className="btn btn-sm" onClick={() => onTable({ find: c.prefix })}>Open in Table</button>
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Done({ run, cameras, onBack, onResults, onTable }: {
  run: Run
  cameras: RunCamera[]
  onBack: () => void
  onResults: () => void
  onTable: Props['onTable']
}) {
  const measured = cameras.filter((c) => c.status === 'done')
  const look = sum(measured, 'needs_look')
  const notYet = cameras.filter((c) => c.status !== 'done')
  const title = run.status === 'error'
    ? 'Measuring stopped with a problem'
    : run.status === 'cancelled'
      ? `Stopped: ${measured.length} of ${plural(cameras.length, 'camera')} measured`
      : `Done: ${plural(measured.length, 'camera')} measured`
  const notes: ReactNode[] = []
  if (run.error) notes.push(<p key="e" className="notice notice-error">{run.error}</p>)
  if (notYet.length > 0) {
    notes.push(<p key="s" className="notice notice-warn">
      Not finished: {notYet.map((c) => c.name).join(', ')}. To carry on, press Back to the cameras, then Measure ticked.
      Photos already measured are skipped.
    </p>)
  }
  if (run.left_out?.length) {
    notes.push(<p key="l" className="notice notice-warn">
      Not measured: {run.left_out.map((x) => `${x.name} (${x.why})`).join(', ')}.
    </p>)
  }
  return (
    <div className="sheet" style={{ overflow: 'auto' }}>
      <div className="card batch" style={{ flex: 1, minHeight: 'auto' }}>
        <div className="batch-head">
          <h2>{title}</h2>
          <div className="spacer" />
          <button className="btn" onClick={onBack}>Back to the cameras</button>
          <button className="btn" onClick={onResults}>Go to Results</button>
          {look > 0 && (
            <button className="btn btn-amber" onClick={() => onTable({ filter: 'flagged' })}>
              Review {plural(look, 'photo')} that need a look
            </button>
          )}
        </div>
        {measured.length > 0 && <Summary cameras={measured} onTable={onTable} />}
        {notes.length > 0 && <div className="batch-foot stack" style={{ alignItems: 'stretch' }}>{notes}</div>}
      </div>
    </div>
  )
}

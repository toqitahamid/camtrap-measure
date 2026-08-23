/* What every part of the window shares: the engine's JSON as types, the few formatters that must agree
   across the three sections, and the icon set. No state, no fetching — those live where they are used. */

export type Inference = {
  status: 'loading' | 'ready' | 'error'
  backend: 'fake' | 'real'
  device: string | null
  batch: number | null
  weights: string | null
  warning: string | null
  error: string | null
  download: { done_gb: number; total_gb: number } | null
}
export type Status = {
  signed_in: boolean
  email: string | null
  last_sync: string | null
  annotations: number
  sites: number
  inference: Inference
}
export type Flag = { image_name: string; captured_at: string | null; ok: boolean; reason: string | null }
export type Camera = { site: string; flags: Flag[] }
export type Methods = { default: string; methods: Record<string, { label: string; hint: string }> }

export type Det = {
  idx: number
  x1: number
  y1: number
  x2: number
  y2: number
  species: string
  confidence: number
  distance_m: number | null
  q05_m: number | null
  q95_m: number | null
  method: string
  match_score: number | null
  reasons: string[]
}
/** One JPEG in the chosen folder, with the answer held for this flag photo and method (if any). */
export type Row = {
  name: string
  path: string
  captured_at: string | null
  measured: boolean
  stale: boolean
  match_score: number | null
  method: string | null
  flag_image: string | null
  reasons: string[]
  detections: Det[]
}
export type Folder = { folder: string; total: number; unreadable: number; rows: Row[] }

export type Run = {
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
export type Summary = {
  photos: number
  detections: number
  deer: number
  suspicious: number
  histogram: { lo: number; hi: number; n: number }[]
  cameras: { site: string; photos: number; detections: number; deer: number; median_m: number | null; suspicious: number }[]
}

/** What every section is pointed at: one camera, one of its flag photos, one folder, one method. */
export type Scope = { site: string; flag: string; folder: string; method: string }

export const post = (url: string, body?: unknown) =>
  fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

export const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'never')
export const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : '—')
export const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString(undefined, { hour12: false }) : '—'
export const stamp = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'no capture date')
export const duration = (s: number) => (s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`)
export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
export const thousands = (n: number) => n.toLocaleString()

/** The one distance a row shows: the nearest animal's, since that is the one a reviewer checks first. */
export const lead = (r: Row): Det | null =>
  r.detections.reduce<Det | null>(
    (best, d) => (d.distance_m === null ? best : best === null || d.distance_m < (best.distance_m ?? Infinity) ? d : best),
    null,
  )
export const metres = (d: Det | null) => (d && d.distance_m !== null ? `${d.distance_m.toFixed(1)} m` : '—')
export const band = (d: Det | null) =>
  d && d.q05_m !== null && d.q95_m !== null ? `${d.q05_m.toFixed(1)}–${d.q95_m.toFixed(1)}` : '—'

/** measured and clean · measured and worth a look · never measured · measured against another flag photo */
export type State = 'clean' | 'flagged' | 'empty' | 'new' | 'stale'
export function state(r: Row): State {
  if (r.reasons.length > 0 && !r.measured) return 'flagged' // an unreadable file: never measured, still needs a look
  if (!r.measured) return 'new'
  if (r.stale) return 'stale'
  if (r.reasons.length > 0) return 'flagged'
  return r.detections.length === 0 ? 'empty' : 'clean'
}
export const STATE_LABEL: Record<State, string> = {
  clean: 'Clean',
  flagged: 'Needs a look',
  empty: 'Empty frame',
  new: 'Not measured',
  stale: 'Answer out of date',
}

export const photoSrc = (path: string, size: 'thumb' | 'full') =>
  `/api/photo?size=${size}&path=${encodeURIComponent(path)}`
export const flagSrc = (site: string, image: string) =>
  `/api/flag?size=full&site=${encodeURIComponent(site)}&image=${encodeURIComponent(image)}`

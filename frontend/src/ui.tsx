/* What every part of the window shares: the engine's JSON as types, the few formatters that must agree
   across the sections. No state, no fetching: those live where they are used. */

export type Inference = {
  status: 'loading' | 'ready' | 'error'
  backend: 'fake' | 'real'
  device: string | null
  gpu: string | null        // the card's own name, so "is it really using the GPU" is answered on screen
  precision: string | null  // float16 / bfloat16: what the distance net actually runs in
  fidelity: 'research' | 'fast' | null  // which settings made the numbers; research = the published pipeline
  loaded: string[]          // which model stages hold VRAM right now; empty when the app is idle
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
// `site` is the camera's name (MAS_CAM01); `survey_site` the site it belongs to (MAS), as the engine reads it
export type Camera = { site: string; survey_site: string; flags: Flag[] }
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
  flag_site: string | null   // the camera it was measured under - travels with flag_image or the pair is a 404
  detections: Det[]
}
export type Folder = { folder: string; total: number; unreadable: number; rows: Row[] }

/** One camera of a site run: how far it has got, then (once done) what it adds up to. */
export type RunCamera = {
  folder: string
  name: string            // the folder's path inside the site folder, as the table shows it
  site: string            // the camera
  prefix: string          // how TABLE names this folder's photos, to filter on
  flags: { image_name: string; captured_at: string | null }[]
  total: number
  done: number
  deer: number
  status: 'waiting' | 'running' | 'done' | 'stopped'
  photos: number | null
  median_m: number | null
}

export type Run = {
  id: number
  kind: 'folder' | 'site'
  folder: string
  site: string | null
  flag: string | null
  cameras?: RunCamera[]   // a site run only
  camera_i?: number
  left_out?: { name: string; why: string }[]
  method: string
  status: 'running' | 'done' | 'cancelled' | 'error'
  phase: string           // which stage the run is in: loading, finding animals, measuring distances
  phase_done: number      // progress inside that stage - the detector sees every photo, the distance
  phase_total: number     // models only the ones it found an animal in, so the two counts differ
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


/* A site folder (a folder of camera folders), as the engine reads it: one row per camera folder. */
export type SiteFlag = { image_name: string; captured_at: string | null; photos: number; visit: 'setup' | 'service' | null }
export type SiteAction = 'compare' | 'use' | 'keep' | 'flaglabel'
export type SiteRow = {
  folder: string
  name: string
  photos: number
  camera: string | null
  candidates: string[]
  state: 'ok' | 'ambiguous' | 'unknown' | 'unlabelled'
  note: string | null
  stamp: { text: string; camera: string | null; mismatch: boolean; kept: boolean } | null
  flags: SiteFlag[]
  flag_choice: string     // '' = each photo's flag photo is chosen by date
  options: { image_name: string; captured_at: string | null }[]
  measured: number
  warnings: string[]
  actions: SiteAction[]
  tickable: boolean
  ticked: boolean
  group: 'attention' | 'ready'
}
export type Site = {
  status: 'ready'
  folder: string
  rows: SiteRow[]
  skipped: { name: string; why: string }[]
  counts: { check: number; cannot: number; ready: number; skipped: number }
  ticked: { cameras: number; photos: number; measured: number }
  pace_s: number
}
export type SiteState =
  | Site
  | { status: 'reading'; done: number; total: number }
  // one camera's folder; `camera` is the camera its name names (null: none, or two), and the Camera menu starts on it
  | { status: 'single'; camera?: string | null }
  | { status: 'error'; error: string }
export type Comparison = {
  folder: string
  photo: string
  name: string
  stamp: string
  flags: { site: string; image_name: string | null; score: number | null; lines_up: boolean }[]
}
/** A row change the confirmation table posts: one menu or one button. */
export type SiteChange = { camera?: string; keep?: string; flag?: string; tick?: boolean }

/** What every section is pointed at: one camera, one of its flag photos, one folder, one method. */
export type Scope = { site: string; flag: string; folder: string; method: string }

export const post = (url: string, body?: unknown) =>
  fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

/** What an empty cell shows. Not an em dash: the researcher asked for none on screen (2026-09-29). */
export const NONE = '–'

export const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'never')
export const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : NONE)
export const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString(undefined, { hour12: false }) : NONE
export const stamp = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'no capture date')
export const duration = (s: number) => (s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`)
export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
/** A long wait in words, ready to start a sentence: "About 4 hours 40 minutes", "Less than a minute". */
export function about(s: number): string {
  const min = Math.round(s / 60)
  if (min < 1) return 'Less than a minute'
  const h = Math.floor(min / 60)
  const m = min % 60
  return `About ${[h ? plural(h, 'hour') : '', m ? plural(m, 'minute') : ''].filter(Boolean).join(' ')}`
}
/** A visit date the way the field notes write it: "19 Dec 2025". */
export const visitDay = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : 'undated'
export const thousands = (n: number) => n.toLocaleString()

/** The one distance a row shows: the nearest animal's, since that is the one a reviewer checks first. */
export const lead = (r: Row): Det | null =>
  r.detections.reduce<Det | null>(
    (best, d) => (d.distance_m === null ? best : best === null || d.distance_m < (best.distance_m ?? Infinity) ? d : best),
    null,
  )
export const metres = (d: Det | null) => (d && d.distance_m !== null ? `${d.distance_m.toFixed(1)} m` : NONE)
export const band = (d: Det | null) =>
  d && d.q05_m !== null && d.q95_m !== null ? `${d.q05_m.toFixed(1)}–${d.q95_m.toFixed(1)}` : NONE

/** measured · measured, no animal · never measured · measured against another flag photo. The "Needs a look"
    state was removed 2026-10-11 to simplify the window; no screen shows the engine's reasons now. */
export type State = 'clean' | 'empty' | 'new' | 'stale'
export function state(r: Row): State {
  if (!r.measured) return 'new'
  if (r.stale) return 'stale'
  return r.detections.length === 0 ? 'empty' : 'clean'
}
export const STATE_LABEL: Record<State, string> = {
  clean: 'Measured', // was "Looks fine": nothing is checked any more, so it promised too much (2026-10-11)
  empty: 'No animal',
  new: 'Not measured',
  stale: 'Out of date',
}

/** How sure the detector is that a box holds an animal, as a percentage. */
export const sure = (d: Det) => `${Math.round(d.confidence * 100)}%`

export const photoSrc = (path: string, size: 'thumb' | 'full') =>
  `/api/photo?size=${size}&path=${encodeURIComponent(path)}`
export const flagSrc = (site: string, image: string) =>
  `/api/flag?size=full&site=${encodeURIComponent(site)}&image=${encodeURIComponent(image)}`

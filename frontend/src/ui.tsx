/* What every part of the window shares: the engine's JSON as types, the few formatters that must agree
   across the three sections, and the icon set. No state, no fetching — those live where they are used. */

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
  flag_site: string | null   // the camera it was measured under - travels with flag_image or the pair is a 404
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

/** One camera in the density's survey setup: saved value over default, and whether the lens angle is known. */
export type SurveyCamera = {
  site: string
  model: string | null
  active_days: number | null
  active_days_default: number | null
  // how the days were found: from the flag photo of the setup visit (or the first photo) to the last photo
  days_source: { days: number | null; from: string; from_kind: 'flag' | 'photo' | 'filter'; flag: string | null; to: string; to_kind: 'photo' | 'filter' } | null
  fov_deg: number
  fov_default: number
  fov_source: string | null  // "flag calibration IMG_0004.JPG", "camera model", or null for the 42 degree guess
  fov_checked: boolean
}
export type Density = {
  deer: number
  suspicious: number
  between_moments: number
  beyond: number
  no_days: number
  no_days_deer: number
  used: number
  interval_s: number
  interval_default_s: number
  interval_gaps: number  // the gaps between photos the suggested interval came from; 0 when none
  photos: { photos: number; at_moments: number; undated: number }
  truncation_m: number | null
  truncation_default_m: number | null
  cameras: SurveyCamera[]
  effort: number
  min_deer: number
  too_few: boolean
  fit: { model: string; sigma: number; b: number | null; aic: number; other: { model: string; aic: number } | null } | null
  bins: { lo: number; hi: number; n: number }[]
  curve: { r: number; n: number }[]  // the fitted curve as expected deer per bin, so it sits on the bars
  density: { per_km2: number; lo: number; hi: number; p: number; edr_m: number } | null
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

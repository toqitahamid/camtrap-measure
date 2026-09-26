/* A white-tailed deer buck in profile, for the sign-in scene (RangeScene.tsx).

   Everything is built in metres in the deer's own frame: x forward (the deer faces +x), y up, the hooves on
   y = 0 and the body centred on x = 0. The caller places and scales it; `drawDeer` flips it to face left.

   The silhouette is one flat grey shape (torso, neck and head, tail, the near legs, near ear and antler)
   with a thin dark rim round the outside, and a darker copy of the far legs, ear and antler behind it for
   depth. Legs are jointed chains (elbow, knee, fetlock for the forelegs; stifle, hock, fetlock for the hind
   legs) posed by two-bone inverse kinematics from where each hoof is.

   The walk is the four-beat lateral sequence a deer uses: near hind, near fore, far hind, far fore, a
   quarter stride apart. A hoof on the ground moves back under the body by exactly the distance the body
   travels (the stride the caller passes), so it does not slide over the ground. The head nods twice a
   stride, the body rises and falls a little, and the tail swings. Without a gait it stands still. */

type V = { x: number; y: number }

/** Where the deer is in its walk: `phase` 0..1 through one stride (near hind hoof lands at 0), and
    `stride` the distance, metres, the body moves over the ground in one stride. */
export type Gait = { phase: number; stride: number }

const NEAR = '#aeb5bd' // the scene's deer grey
const FAR = '#7e868e' // the far legs, ear and antler: the same grey in shade
const HOOF = '#5d646b'
const WHITE = '#e2e5e8' // the tail's white underside
const RIM = 'rgba(8, 10, 12, 0.7)'
const MARK = 'rgba(11, 13, 15, 0.75)' // eye and nose

const SHIFT = -0.15 // moves the body back so the rack and the tail sit evenly inside the reticle
const STANCE = 0.62 // fraction of a stride each hoof is on the ground (a walk: more than half)
const FETLOCK_Y = 0.075 // fetlock height with the hoof flat on the ground

type Leg = {
  fore: boolean
  near: boolean
  lands: number // phase at which this hoof touches down
  x: number // hoof position under the body, standing square
  stand: number // offset from `x` in the standing pose, so the four legs do not stack
}

const LEGS: Leg[] = [
  { fore: false, near: false, lands: 0.5, x: -0.35, stand: 0.05 },
  { fore: true, near: false, lands: 0.75, x: 0.36, stand: -0.04 },
  { fore: false, near: true, lands: 0, x: -0.35, stand: -0.04 },
  { fore: true, near: true, lands: 0.25, x: 0.36, stand: 0.06 },
]

/** The deer with its hooves at (x, y) on screen, `scale` px per metre, facing right when dir is 1 and
    left when it is -1. With no gait, the standing pose. */
export function drawDeer(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  scale: number,
  dir: number,
  gait: Gait | null,
) {
  ctx.save()
  ctx.translate(x, y)
  ctx.scale(scale * dir, -scale) // metres, y up

  // A soft shadow on the ground under the body.
  ctx.save()
  ctx.scale(1, 0.13)
  const shade = ctx.createRadialGradient(0, 0, 0, 0, 0, 0.85)
  shade.addColorStop(0, 'rgba(0, 0, 0, 0.55)')
  shade.addColorStop(1, 'rgba(0, 0, 0, 0)')
  ctx.fillStyle = shade
  ctx.fillRect(-0.9, -0.9, 1.8, 1.8)
  ctx.restore()

  ctx.translate(SHIFT, 0)

  // Body rise and fall and the head nod: twice a stride, once per forefoot landing.
  const p = gait ? gait.phase : 0
  const rise = gait ? 0.007 * Math.cos(4 * Math.PI * (p - 0.3)) : 0
  const nod = gait ? 0.035 * Math.sin(4 * Math.PI * (p - 0.2)) : 0
  const head = headBend(nod, rise)

  // Each group is a list of separate shapes: filled one by one, so overlaps never cancel out.
  const far: Path2D[] = []
  const farHooves: Path2D[] = []
  const near: Path2D[] = []
  const nearHooves: Path2D[] = []
  for (const leg of LEGS) {
    const { limb, hoof } = legShape(leg, gait, rise)
    ;(leg.near ? near : far).push(limb)
    ;(leg.near ? nearHooves : farHooves).push(hoof)
  }
  far.push(ear(head, 0.025, 0.012), ...antler(head, -0.035, 0.014, FAR_TINES))

  const tl = tail(gait, rise)
  near.push(body(head), tl.shape, ear(head, 0, 0), ...antler(head, 0, 0, TINES))

  const rim = 2.2 / scale // px -> metres
  silhouette(ctx, far, farHooves, FAR, rim)
  silhouette(ctx, near, nearHooves, NEAR, rim)

  // the white underside of the tail, along its back edge
  ctx.fillStyle = WHITE
  ctx.fill(tl.white)

  // an eye and a dark nose: only visible when the deer is close
  if (scale > 45) {
    ctx.fillStyle = MARK
    const eye = head(0.83, 1.2)
    const nose = head(0.985, 1.1)
    ctx.beginPath()
    ctx.ellipse(eye.x, eye.y, 0.014, 0.011, 0, 0, Math.PI * 2)
    ctx.ellipse(nose.x, nose.y, 0.016, 0.014, 0, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

/** Fill a group of shapes as one silhouette with a rim round its outside only: stroke every shape, then
    fill them all over the strokes, so the strokes survive only where they face out. */
function silhouette(ctx: CanvasRenderingContext2D, shapes: Path2D[], hooves: Path2D[], fill: string, rim: number) {
  ctx.lineJoin = 'round'
  ctx.strokeStyle = RIM
  ctx.lineWidth = rim
  for (const s of [...shapes, ...hooves]) ctx.stroke(s)
  ctx.fillStyle = fill
  for (const s of shapes) ctx.fill(s)
  ctx.fillStyle = HOOF
  for (const s of hooves) ctx.fill(s)
}

/** Maps a point of the neck or head through the nod: the head turns about the base of the neck, the
    neck bends between. Points behind the withers only rise and fall with the body. */
function headBend(angle: number, rise: number) {
  const px = 0.34
  const py = 0.95
  const cos = Math.cos(angle)
  const sin = Math.sin(angle)
  return (x: number, y: number): V => {
    const k = Math.min(1, Math.max(0, (x - px) / 0.26)) // 0 at the withers, 1 from the jaw forward
    const c = 1 + (cos - 1) * k
    const s = sin * k
    const dx = x - px
    const dy = y - py
    return { x: px + dx * c - dy * s, y: py + dx * s + dy * c + rise }
  }
}

/** Torso, neck and head as one outline, clockwise from the withers. */
function body(head: (x: number, y: number) => V) {
  const path = new Path2D()
  const at = head // behind the withers it only adds the body's rise
  const move = (a: V) => path.moveTo(a.x, a.y)
  const curve = (c1: V, c2: V, e: V) => path.bezierCurveTo(c1.x, c1.y, c2.x, c2.y, e.x, e.y)

  move(at(0.3, 1.01)) // withers
  curve(at(0.13, 0.99), at(-0.09, 0.945), at(-0.22, 0.955)) // back, dipping a little behind the withers
  curve(at(-0.33, 0.965), at(-0.415, 0.995), at(-0.47, 0.985)) // loin to croup
  curve(at(-0.53, 0.975), at(-0.565, 0.95), at(-0.58, 0.915)) // croup rounding to the tail head
  curve(at(-0.61, 0.84), at(-0.607, 0.72), at(-0.52, 0.62)) // buttock, the back of the ham
  curve(at(-0.445, 0.585), at(-0.37, 0.59), at(-0.295, 0.6)) // under the ham to the stifle fold
  curve(at(-0.165, 0.555), at(0.07, 0.495), at(0.244, 0.49)) // flank and belly, tucked up at the back
  curve(at(0.4, 0.485), at(0.5, 0.56), at(0.52, 0.7)) // deep brisket to the point of the chest
  curve(at(0.54, 0.84), at(0.64, 0.99), at(0.73, 1.075)) // front of the neck, the throat
  curve(at(0.79, 1.06), at(0.88, 1.05), at(0.94, 1.052)) // jaw to chin
  curve(at(0.98, 1.055), at(1.005, 1.08), at(1.0, 1.11)) // muzzle and nose
  curve(at(0.96, 1.15), at(0.88, 1.21), at(0.8, 1.25)) // bridge of the nose to the brow
  curve(at(0.77, 1.275), at(0.73, 1.3), at(0.69, 1.29)) // forehead to the poll
  curve(at(0.6, 1.24), at(0.45, 1.09), at(0.3, 1.01)) // crest of the neck down to the withers
  path.closePath()
  return path
}

/** One ear, a long leaf held up and back behind the antler; (dx, dy) shifts the far one. */
function ear(head: (x: number, y: number) => V, dx: number, dy: number) {
  const at = (x: number, y: number) => head(x + dx, y + dy)
  const path = new Path2D()
  const a = at(0.72, 1.285)
  const c1 = at(0.715, 1.38)
  const c2 = at(0.66, 1.44)
  const tip = at(0.575, 1.47)
  const c3 = at(0.585, 1.4)
  const c4 = at(0.63, 1.31)
  const b = at(0.665, 1.27)
  path.moveTo(a.x, a.y)
  path.bezierCurveTo(c1.x, c1.y, c2.x, c2.y, tip.x, tip.y)
  path.bezierCurveTo(c3.x, c3.y, c4.x, c4.y, b.x, b.y)
  path.closePath()
  return path
}

/** The rack, seen from the side: the main beam rises from the brow, curves forward over the face and
    turns in at the tip; a short brow tine and three tines stand up off the top of the beam. */
function antler(head: (x: number, y: number) => V, dx: number, dy: number, tines: number[][]) {
  const at = (x: number, y: number) => head(x + dx, y + dy)
  const beam: [V, V, V, V] = [
    { x: 0.755, y: 1.29 },
    { x: 0.7, y: 1.42 },
    { x: 0.84, y: 1.6 },
    { x: 1.0, y: 1.5 },
  ]
  const parts = [horn(at, beam, 0.036, 0.008)]
  for (const [t, len] of tines) {
    // a tine stands up off the top of the beam, leaning a little forward
    const b = bezier(beam, t)
    const tip = { x: b.x + 0.15 * len, y: b.y + len }
    const tine: [V, V, V, V] = [
      { x: b.x - 0.008, y: b.y - 0.012 },
      { x: b.x - 0.008, y: b.y + 0.45 * len },
      { x: tip.x - 0.04 * len, y: tip.y - 0.3 * len },
      tip,
    ]
    parts.push(horn(at, tine, 0.026, 0.004))
  }
  return parts
}

// tines, as (where on the beam 0..1, how tall in metres): a brow tine and three points, a typical 8-pointer
const TINES = [
  [0.1, 0.07],
  [0.36, 0.19],
  [0.6, 0.16],
  [0.8, 0.08],
]
// of the far antler only the two tall tines show clear of the near one
const FAR_TINES = [
  [0.36, 0.18],
  [0.6, 0.15],
]

/** A tapered ribbon along a cubic curve, w0 wide at its start and w1 at its end (metres). */
function horn(map: (x: number, y: number) => V, c: [V, V, V, V], w0: number, w1: number) {
  const N = 14
  const left: V[] = []
  const right: V[] = []
  for (let i = 0; i <= N; i++) {
    const t = i / N
    const p = bezier(c, t)
    const d = bezier(c, Math.min(1, t + 0.01))
    const e = bezier(c, Math.max(0, t - 0.01))
    const len = Math.hypot(d.x - e.x, d.y - e.y) || 1
    const nx = -(d.y - e.y) / len
    const ny = (d.x - e.x) / len
    const w = (w0 + (w1 - w0) * t) / 2
    left.push(map(p.x + nx * w, p.y + ny * w))
    right.push(map(p.x - nx * w, p.y - ny * w))
  }
  const path = new Path2D()
  const pts = [...left, ...right.reverse()]
  path.moveTo(pts[0].x, pts[0].y)
  for (const q of pts.slice(1)) path.lineTo(q.x, q.y)
  path.closePath()
  return path
}

function bezier([a, b, c, d]: [V, V, V, V], t: number): V {
  const u = 1 - t
  return {
    x: u * u * u * a.x + 3 * u * u * t * b.x + 3 * u * t * t * c.x + t * t * t * d.x,
    y: u * u * u * a.y + 3 * u * u * t * b.y + 3 * u * t * t * c.y + t * t * t * d.y,
  }
}

/** The tail hanging from the rump, relaxed, swinging a little with the walk: the whole tail as part of
    the silhouette, and the white fringe along its back edge drawn over it. */
function tail(gait: Gait | null, rise: number) {
  const swing = gait ? 0.08 * Math.sin(2 * Math.PI * gait.phase) : 0.03
  const bx = -0.57
  const by = 0.925 + rise
  const cos = Math.cos(swing)
  const sin = Math.sin(swing)
  // tail points relative to its root, turned about the root by the swing
  const at = (x: number, y: number): V => ({ x: bx + x * cos - y * sin, y: by + x * sin + y * cos })
  const trace = (parts: V[][]) => {
    const path = new Path2D()
    path.moveTo(parts[0][0].x, parts[0][0].y)
    for (const [c1, c2, e] of parts.slice(1)) path.bezierCurveTo(c1.x, c1.y, c2.x, c2.y, e.x, e.y)
    path.closePath()
    return path
  }
  const shape = trace([
    [at(0.01, 0.01)],
    [at(-0.05, 0.02), at(-0.1, -0.03), at(-0.105, -0.1)], // back edge, out from the rump and down
    [at(-0.11, -0.16), at(-0.09, -0.215), at(-0.065, -0.22)], // rounded tip
    [at(-0.045, -0.17), at(-0.03, -0.06), at(0.01, -0.03)], // front edge, against the buttock
  ])
  const white = trace([
    [at(-0.085, -0.02)],
    [at(-0.1, -0.04), at(-0.106, -0.07), at(-0.105, -0.1)],
    [at(-0.11, -0.16), at(-0.09, -0.212), at(-0.068, -0.218)],
    [at(-0.078, -0.16), at(-0.082, -0.08), at(-0.085, -0.02)],
  ])
  return { shape, white }
}
/** Where this leg's fetlock is and how far its hoof is curled back (0 flat, 1 fully tucked). */
function fetlock(leg: Leg, gait: Gait | null) {
  const y0 = leg.near ? 0 : 0.012 // the far legs land a little higher: they are farther away
  if (!gait) return { f: { x: leg.x + leg.stand, y: FETLOCK_Y + y0 }, curl: 0 }
  const L = gait.stride
  const p = (((gait.phase - leg.lands) % 1) + 1) % 1
  if (p < STANCE) {
    // on the ground: moves back under the body exactly as fast as the body moves forward
    return { f: { x: leg.x + L * (STANCE / 2 - p), y: FETLOCK_Y + y0 }, curl: 0 }
  }
  // in the air: lifts early, swings forward, and reaches for the ground again
  const s = (p - STANCE) / (1 - STANCE)
  const up = Math.sin(Math.PI * Math.pow(s, 0.8))
  const lift = (leg.fore ? 0.12 : 0.09) * (0.4 + 0.6 * Math.min(1, L / 0.8))
  const reach = 0.5 - 0.5 * Math.cos(Math.PI * s)
  return { f: { x: leg.x + L * (-STANCE / 2 + STANCE * reach), y: FETLOCK_Y + y0 + lift * up }, curl: up }
}

/** One leg as an outline (upper leg to pastern) and a hoof. */
function legShape(leg: Leg, gait: Gait | null, rise: number) {
  const { f: target, curl } = fetlock(leg, gait)
  const swing = target.x - leg.x // the upper leg follows the hoof a little
  const y0 = leg.near ? 0 : 0.012

  // top of the leg (inside the body), the joint below it, then two bones posed to reach the fetlock
  const top = leg.fore ? { x: 0.37, y: 0.8 + rise + y0 } : { x: -0.41, y: 0.8 + rise + y0 }
  const mid = leg.fore
    ? { x: 0.32 + 0.25 * swing, y: 0.56 + rise + y0 } // elbow
    : { x: -0.27 + 0.3 * swing, y: 0.6 + rise + y0 } // stifle
  const [l1, l2] = leg.fore ? [0.255, 0.235] : [0.27, 0.32]
  // the knee (carpus) bends forward, the hock backward
  const { joint, end } = reach(mid, target, l1, l2, leg.fore ? 1 : -1)

  // the pastern slopes down and forward to the hoof; in the air the hoof curls back
  const turn = (leg.fore ? -1.0 : -0.7) * curl
  const rot = (x: number, y: number): V => ({
    x: end.x + x * Math.cos(turn) - y * Math.sin(turn),
    y: end.y + x * Math.sin(turn) + y * Math.cos(turn),
  })
  const coronet = rot(0.03, -0.058)

  const pts = [top, mid, lerp(mid, joint, 0.5), joint, lerp(joint, end, 0.5), end, coronet]
  // half-widths in front of and behind each point: muscle above, bone below, visible joints
  const front = leg.fore
    ? [0.11, 0.058, 0.04, 0.029, 0.019, 0.023, 0.015]
    : [0.13, 0.07, 0.05, 0.03, 0.019, 0.022, 0.015]
  const back = leg.fore
    ? [0.09, 0.07, 0.036, 0.028, 0.018, 0.025, 0.016]
    : [0.2, 0.19, 0.1, 0.045, 0.02, 0.025, 0.016]
  const limb = new Path2D()
  smoothClosed(limb, outline(pts, front, back))

  // the hoof: a small wedge, pointed at the toe
  const hoof = new Path2D()
  const h = [rot(0.047, -0.058), rot(0.078, -0.075), rot(0.004, -0.075), rot(0.005, -0.052)]
  hoof.moveTo(h[0].x, h[0].y)
  for (const q of h.slice(1)) hoof.lineTo(q.x, q.y)
  hoof.closePath()
  return { limb, hoof }
}

/** Two-bone reach from `a` toward `target`: the middle joint, and the end (the target, or as near as the
    bones allow). `bend` 1 puts the joint in front of the line a-target, -1 behind it. */
function reach(a: V, target: V, l1: number, l2: number, bend: number) {
  const dx = target.x - a.x
  const dy = target.y - a.y
  const full = Math.hypot(dx, dy) || 1e-6
  const d = Math.min(l1 + l2 - 1e-4, Math.max(Math.abs(l1 - l2) + 1e-4, full))
  const ux = dx / full
  const uy = dy / full
  const along = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
  const off = Math.sqrt(Math.max(0, l1 * l1 - along * along))
  // (-uy, ux) is the line turned a quarter left: forward (+x) for a leg pointing down
  const joint = { x: a.x + ux * along - uy * off * bend, y: a.y + uy * along + ux * off * bend }
  return { joint, end: { x: a.x + ux * d, y: a.y + uy * d } }
}

/** The outline of a chain of points with half-widths in front of (+) and behind (-) it: down the front,
    back up the rear. */
function outline(pts: V[], front: number[], back: number[]) {
  const fwd: V[] = []
  const rear: V[] = []
  pts.forEach((p, i) => {
    const a = pts[Math.max(0, i - 1)]
    const b = pts[Math.min(pts.length - 1, i + 1)]
    const len = Math.hypot(b.x - a.x, b.y - a.y) || 1
    const nx = -(b.y - a.y) / len // the chain turned a quarter left: forward for a leg pointing down
    const ny = (b.x - a.x) / len
    fwd.push({ x: p.x + nx * front[i], y: p.y + ny * front[i] })
    rear.push({ x: p.x - nx * back[i], y: p.y - ny * back[i] })
  })
  return [...fwd, ...rear.reverse()]
}

/** A closed shape through the midpoints of a polygon's edges, with its corners as control points:
    round joints, no kinks. */
function smoothClosed(path: Path2D, pts: V[]) {
  const n = pts.length
  const mid = (a: V, b: V) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })
  const start = mid(pts[n - 1], pts[0])
  path.moveTo(start.x, start.y)
  for (let i = 0; i < n; i++) {
    const m = mid(pts[i], pts[(i + 1) % n])
    path.quadraticCurveTo(pts[i].x, pts[i].y, m.x, m.y)
  }
  path.closePath()
}

const lerp = (a: V, b: V, k: number): V => ({ x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k })

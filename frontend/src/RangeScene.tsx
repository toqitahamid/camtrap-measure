/* The sign-in screen's backdrop: what the app does, drawn as a camera trap sees it. A ground plane runs
   to the horizon with range rings at 5, 10, 20 and 40 m around the camera; a deer walks a slow loop
   through them, and a dashed line and a readout give its distance as it goes.

   A plain 2D canvas and a pinhole projection written here, no 3D library. The camera sways and dollies
   a little on a 24 s loop; the deer's loop has the same period, so the whole scene repeats seamlessly.
   It draws at most 30 frames a second, stops while the window is hidden, and draws one still frame
   when the system asks for reduced motion. Decoration only: hidden from screen readers.

   The horizon sits a fixed gap under the element passed as `below` (the headline and paragraph), so the
   text always reads on the plain sky and the ground fills the rest of the panel at any window size. */

import { useEffect, useRef, type RefObject } from 'react'

const LOOP_S = 24 // one full loop of the scene, seconds
const STILL_T = 14 // the moment drawn when motion is reduced: deer mid-field, about 16 m away
const FRAME_MS = 1000 / 30
const GAP_PX = 96 // from the bottom of `below` to the horizon

const EYE_M = 1.4 // camera height above the ground
const NEAR_M = 3.2 // the ground distance that meets the bottom edge of the canvas
const RINGS = [5, 10, 20, 40]

// Colours from the design system (index.css); the canvas cannot read CSS variables cheaply every frame.
const BG = '#0b0d0f'
const AMBER = '232, 161, 60' // --amber as rgb, for rgba() with an alpha
const GRID = '138, 146, 156' // --dim as rgb
const DEER = '#aeb5bd'
const GROT = "'Space Grotesk', 'Inter', system-ui, sans-serif"
const MONO = "ui-monospace, 'Cascadia Mono', Consolas, monospace"

type Pt = { x: number; y: number; z: number } // camera space: x right, y up, z forward (metres)

/** Where the camera is at time t: a slow sideways sway, a small dolly, a slight pan. */
function cameraAt(t: number) {
  const w = (2 * Math.PI * t) / LOOP_S
  return { x: 0.9 * Math.sin(w), z: -0.8 + 0.6 * Math.sin(2 * w + 1), yaw: 0.07 * Math.sin(w + 0.6) }
}

/** Where the deer is at time t, on the ground (x across, z away from the camera trap at the origin).
    `spread` is the widest bearing either side, radians, so a narrow panel keeps the deer in frame. */
function deerAt(t: number, spread: number) {
  const w = (2 * Math.PI * t) / LOOP_S
  const r = 20 + 7 * Math.sin(w) // 13 to 27 m
  const bearing = spread * Math.cos(w)
  return { x: r * Math.sin(bearing), z: r * Math.cos(bearing), r, heading: Math.sign(-Math.sin(w)) || 1 }
}

export default function RangeScene({ below }: { below?: RefObject<HTMLElement | null> }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)')
    let w = 0
    let h = 0
    let hy = 0 // horizon, px from the top
    let t = STILL_T
    let last = 0
    let raf = 0
    let shown = { r: 0, at: -1 } // the readout changes a few times a second, like an instrument

    const frame = () => draw(ctx, w, h, hy, t, shown)

    const resize = () => {
      const dpr = window.devicePixelRatio || 1
      w = canvas.clientWidth
      h = canvas.clientHeight
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const el = below?.current
      const textBottom = el ? el.getBoundingClientRect().bottom - canvas.getBoundingClientRect().top : 0
      hy = Math.round(Math.min(h * 0.72, Math.max(h * 0.45, textBottom + GAP_PX)))
      frame()
    }

    const tick = (now: number) => {
      raf = requestAnimationFrame(tick)
      if (now - last < FRAME_MS) return
      t = (t + Math.min(now - last, 100) / 1000) % LOOP_S // capped, so a long pause does not jump
      last = now
      frame()
    }

    const start = () => {
      cancelAnimationFrame(raf)
      raf = 0
      if (reduce.matches || document.hidden) {
        if (reduce.matches) t = STILL_T
        shown = { r: 0, at: -1 }
        frame()
        return
      }
      last = performance.now()
      raf = requestAnimationFrame(tick)
    }

    const observer = new ResizeObserver(resize)
    observer.observe(canvas)
    if (below?.current) observer.observe(below.current) // the text reflows when the panel narrows
    resize()
    start()
    document.addEventListener('visibilitychange', start)
    reduce.addEventListener('change', start)
    // the readout is drawn in Space Grotesk, and the text block's height depends on the fonts
    document.fonts?.ready.then(resize)

    return () => {
      cancelAnimationFrame(raf)
      observer.disconnect()
      document.removeEventListener('visibilitychange', start)
      reduce.removeEventListener('change', start)
    }
  }, [below])

  return <canvas ref={ref} className="range-scene" aria-hidden="true" />
}

/** One frame. Pure drawing: everything it shows follows from t, the canvas size and the horizon. */
function draw(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  hy: number,
  t: number,
  shown: { r: number; at: number },
) {
  if (w === 0 || h === 0) return
  const f = ((h - hy) * NEAR_M) / EYE_M // focal length, px: the NEAR_M ground line sits on the bottom edge
  const cx = w * 0.56 // vanishing point a little right of centre, away from the text column
  const cam = cameraAt(t)
  const cos = Math.cos(cam.yaw)
  const sin = Math.sin(cam.yaw)

  // world (x across, y up, z away; metres) -> camera space
  const toCam = (x: number, y: number, z: number): Pt => {
    const dx = x - cam.x
    const dz = z - cam.z
    return { x: dx * cos - dz * sin, y: y - EYE_M, z: dx * sin + dz * cos }
  }
  const toScreen = (p: Pt) => ({ x: cx + (f * p.x) / p.z, y: hy - (f * p.y) / p.z })
  const near = 0.6

  /** A straight ground segment, clipped to the near plane. */
  const segment = (a: Pt, b: Pt) => {
    if (a.z < near && b.z < near) return
    if (a.z < near) a = lerp(a, b, (near - a.z) / (b.z - a.z))
    if (b.z < near) b = lerp(b, a, (near - b.z) / (a.z - b.z))
    const p = toScreen(a)
    const q = toScreen(b)
    ctx.moveTo(p.x, p.y)
    ctx.lineTo(q.x, q.y)
  }

  // Sky: near black at the top, a touch lighter and warmer at the horizon.
  ctx.fillStyle = BG
  ctx.fillRect(0, 0, w, h)
  const sky = ctx.createLinearGradient(0, hy - h * 0.35, 0, hy)
  sky.addColorStop(0, 'rgba(20, 23, 27, 0)')
  sky.addColorStop(1, 'rgba(34, 30, 24, 0.9)')
  ctx.fillStyle = sky
  ctx.fillRect(0, hy - h * 0.35, w, h * 0.35)

  // Ground grid: 2 m squares. Lines along z converge on the vanishing point.
  ctx.lineWidth = 1
  ctx.strokeStyle = `rgba(${GRID}, 0.22)`
  ctx.beginPath()
  const gx0 = Math.floor(cam.x / 2) * 2
  for (let x = gx0 - 60; x <= gx0 + 60; x += 2) segment(toCam(x, 0, 0), toCam(x, 0, 160))
  for (let z = 2; z <= 160; z += 2) segment(toCam(gx0 - 80, 0, z), toCam(gx0 + 80, 0, z))
  ctx.stroke()

  // Distance haze: the far ground fades into the horizon, so the grid does not turn to noise there.
  const haze = ctx.createLinearGradient(0, hy, 0, hy + (h - hy) * 0.16)
  haze.addColorStop(0, 'rgba(17, 17, 17, 1)')
  haze.addColorStop(1, 'rgba(11, 13, 15, 0)')
  ctx.fillStyle = haze
  ctx.fillRect(0, hy, w, (h - hy) * 0.16)

  // Where the deer and its readout land on screen, worked out first so the ring labels keep clear of them.
  const deer = deerAt(t, Math.min(0.2, Math.atan((w * 0.3) / f))) // at most +-11 degrees, and in frame
  const foot = toCam(deer.x, 0, deer.z)
  const seen = foot.z > near
  const fs = toScreen(foot)
  const scale = f / foot.z // px per metre at the deer
  const bw = 1.0 * scale // reticle half-width
  const top = fs.y - 1.85 * scale
  const bot = fs.y + 0.12 * scale
  const right = fs.x + bw + 150 < w // readout to the right of the reticle, or left near the edge
  const keepOut = {
    x0: right ? fs.x - bw - 8 : fs.x - bw - 170,
    x1: right ? fs.x + bw + 170 : fs.x + bw + 8,
    y0: top - 8,
    y1: Math.max(bot, top + 48) + 8,
  }

  // Range rings around the camera trap (the origin), with their distances.
  const labelX = w * 0.84 // labels sit near this column, right of the deer's path
  for (const r of RINGS) {
    ctx.beginPath()
    let started = false
    let label: { x: number; y: number } | null = null
    for (let a = -Math.PI / 2; a <= Math.PI / 2 + 1e-6; a += Math.PI / 180) {
      const p = toCam(r * Math.sin(a), 0, r * Math.cos(a))
      if (p.z < near) {
        started = false
        continue
      }
      const s = toScreen(p)
      if (started) ctx.lineTo(s.x, s.y)
      else ctx.moveTo(s.x, s.y)
      started = true
      const fits = s.x < w - 40 && s.y < h - 16
      if (fits && (!label || Math.abs(s.x - labelX) < Math.abs(label.x - labelX))) label = s
    }
    ctx.strokeStyle = `rgba(${AMBER}, ${r >= 40 ? 0.35 : 0.5})`
    ctx.lineWidth = 1.2
    ctx.stroke()

    // the label's box is about 40 x 14 px, up and to the right of its point
    const hidden =
      !label ||
      (seen && label.x + 46 > keepOut.x0 && label.x + 6 < keepOut.x1 && label.y - 3 > keepOut.y0 && label.y - 17 < keepOut.y1)
    if (label && !hidden) {
      ctx.font = `500 ${r >= 40 ? 11 : 12}px ${MONO}`
      ctx.fillStyle = `rgba(${AMBER}, 0.8)`
      ctx.textAlign = 'left'
      ctx.fillText(`${r} m`, label.x + 6, label.y - 5)
    }
  }

  // a thin warm horizon
  const line = ctx.createLinearGradient(0, 0, w, 0)
  line.addColorStop(0, `rgba(${AMBER}, 0)`)
  line.addColorStop(0.55, `rgba(${AMBER}, 0.35)`)
  line.addColorStop(1, `rgba(${AMBER}, 0.05)`)
  ctx.fillStyle = line
  ctx.fillRect(0, hy, w, 1)

  // The deer, the dashed line to it, and its distance.
  if (seen) {
    // dashed measuring line along the ground, from the bottom edge to the deer's feet
    const from = toCam(deer.x * (NEAR_M / deer.r) * 0.7, 0, deer.z * (NEAR_M / deer.r) * 0.7)
    ctx.beginPath()
    segment(from, foot)
    ctx.setLineDash([7, 6])
    ctx.lineDashOffset = -t * 14 // the dashes creep toward the deer
    ctx.strokeStyle = `rgba(${AMBER}, 0.9)`
    ctx.lineWidth = 1.5
    ctx.stroke()
    ctx.setLineDash([])

    // ground contact: a small ellipse under the feet
    ctx.beginPath()
    ctx.ellipse(fs.x, fs.y, 0.55 * scale, 0.12 * scale, 0, 0, Math.PI * 2)
    ctx.strokeStyle = `rgba(${AMBER}, 0.7)`
    ctx.lineWidth = 1.2
    ctx.stroke()

    drawDeer(ctx, fs.x, fs.y, scale, deer.heading)

    // reticle: the app's corner brackets around the animal
    const arm = Math.max(6, 0.28 * scale)
    ctx.strokeStyle = `rgb(${AMBER})`
    ctx.lineWidth = 1.6
    ctx.beginPath()
    for (const [x, y, sx, sy] of [
      [fs.x - bw, top, 1, 1],
      [fs.x + bw, top, -1, 1],
      [fs.x - bw, bot, 1, -1],
      [fs.x + bw, bot, -1, -1],
    ]) {
      ctx.moveTo(x, y + sy * arm)
      ctx.lineTo(x, y)
      ctx.lineTo(x + sx * arm, y)
    }
    ctx.stroke()

    // readout, refreshed four times a second
    const tick = Math.floor(t * 4)
    if (tick !== shown.at) {
      shown.at = tick
      shown.r = deer.r
    }
    const lo = shown.r * 0.92
    const hi = shown.r * 1.09
    const lx = right ? fs.x + bw + 12 : fs.x - bw - 12
    const ly = top + 4
    ctx.textAlign = right ? 'left' : 'right'
    ctx.textBaseline = 'top'
    ctx.fillStyle = `rgb(${AMBER})`
    ctx.font = `600 22px ${GROT}`
    ctx.fillText(`${shown.r.toFixed(1)} m`, lx, ly)
    ctx.fillStyle = `rgba(${GRID}, 0.95)`
    ctx.font = `500 11px ${MONO}`
    ctx.fillText(`90%  ${lo.toFixed(1)}–${hi.toFixed(1)} m`, lx, ly + 28)
    ctx.textBaseline = 'alphabetic'
  }

  // Bottom fade to the panel colour, so the footer text sits on plain ground.
  const fade = ctx.createLinearGradient(0, h - 200, 0, h - 90)
  fade.addColorStop(0, 'rgba(11, 13, 15, 0)')
  fade.addColorStop(1, BG)
  ctx.fillStyle = fade
  ctx.fillRect(0, h - 200, w, 200)
}

const lerp = (a: Pt, b: Pt, k: number): Pt => ({ x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k, z: a.z + (b.z - a.z) * k })

/** A white-tailed deer buck in profile, feet at (x, y), `scale` px per metre, facing right when dir is 1. */
function drawDeer(ctx: CanvasRenderingContext2D, x: number, y: number, scale: number, dir: number) {
  ctx.save()
  ctx.translate(x, y)
  ctx.scale(scale * dir, -scale) // metres, y up
  ctx.fillStyle = DEER
  ctx.strokeStyle = DEER
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  // body, neck and head as one outline, starting at the rump and going round clockwise
  ctx.beginPath()
  ctx.moveTo(-0.6, 0.86)
  ctx.quadraticCurveTo(-0.5, 0.99, -0.2, 0.96) // rump to back
  ctx.lineTo(0.28, 0.99) // withers
  ctx.quadraticCurveTo(0.42, 1.12, 0.55, 1.36) // top of the neck
  ctx.lineTo(0.63, 1.4) // poll
  ctx.quadraticCurveTo(0.74, 1.35, 0.88, 1.22) // forehead to nose
  ctx.lineTo(0.85, 1.18)
  ctx.quadraticCurveTo(0.72, 1.18, 0.64, 1.17) // jaw
  ctx.quadraticCurveTo(0.5, 1.0, 0.44, 0.82) // throat to chest
  ctx.quadraticCurveTo(0.42, 0.66, 0.3, 0.63) // brisket
  ctx.quadraticCurveTo(0, 0.6, -0.36, 0.64) // belly
  ctx.quadraticCurveTo(-0.58, 0.66, -0.6, 0.86) // haunch
  ctx.fill()

  // ear, then a small rack sweeping forward
  ctx.beginPath()
  ctx.moveTo(0.56, 1.36)
  ctx.lineTo(0.45, 1.48)
  ctx.lineTo(0.6, 1.41)
  ctx.fill()
  ctx.lineWidth = 0.03
  ctx.beginPath()
  ctx.moveTo(0.63, 1.4)
  ctx.quadraticCurveTo(0.56, 1.62, 0.8, 1.66)
  ctx.moveTo(0.64, 1.58)
  ctx.lineTo(0.66, 1.7)
  ctx.moveTo(0.73, 1.64)
  ctx.lineTo(0.76, 1.75)
  ctx.stroke()

  // legs: forelegs straight, hind legs bent at the hock
  ctx.lineWidth = 0.055
  ctx.beginPath()
  ctx.moveTo(0.34, 0.68)
  ctx.lineTo(0.37, 0.01)
  ctx.moveTo(0.24, 0.66)
  ctx.lineTo(0.2, 0.01)
  ctx.moveTo(-0.44, 0.7)
  ctx.lineTo(-0.52, 0.34)
  ctx.lineTo(-0.46, 0.01)
  ctx.moveTo(-0.32, 0.66)
  ctx.lineTo(-0.38, 0.34)
  ctx.lineTo(-0.32, 0.01)
  ctx.stroke()

  // the white tail, raised
  ctx.fillStyle = '#f3f4f5'
  ctx.beginPath()
  ctx.ellipse(-0.64, 0.95, 0.1, 0.045, 0.9, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()
}

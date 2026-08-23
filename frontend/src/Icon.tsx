/* The window's icon set: one stroked 24-grid glyph per name, recoloured by `currentColor`.
   Its own module because a file that exports a component and helpers together breaks fast refresh. */

const PATHS = {
  mark: 'M3 8V4h4M21 8V4h-4M3 16v4h4M21 16v4h-4M12 5.5v2M12 16.5v2M5.5 12h2M16.5 12h2',
  measure: 'M4 12h4l2.5-7 3.5 14 2.5-7h4',
  table: 'M3 6a1.5 1.5 0 0 1 1.5-1.5h15A1.5 1.5 0 0 1 21 6v12a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18zM3 9.5h18M3 14.5h18M9.5 9.5V19.5',
  results: 'M4 20V10M10 20V5M16 20v-8M21 20H3',
  sync: 'M21 12a9 9 0 1 1-2.6-6.4M21 4v5h-5',
  folder: 'M3 7.5A1.5 1.5 0 0 1 4.5 6h4L11 8.5h8.5A1.5 1.5 0 0 1 21 10v7.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z',
  flag: 'M6 21V4M6 5h11l-2.6 3.6L17 13H6',
  down: 'M6 9l6 6 6-6',
  left: 'M14 6l-6 6 6 6',
  right: 'M10 6l6 6-6 6',
  check: 'M5 12.5l4.5 4.5L19 7',
  search: 'M16 16l4 4',
  stop: 'M6.5 6.5h11v11h-11z',
  download: 'M12 4v11M8 12l4 4 4-4M5 19h14',
  help: 'M9.5 9.5a2.5 2.5 0 1 1 3 2.45V14M12 17h.01',
  warn: 'M12 4l9 16H3zM12 10v4M12 17h.01',
  spinner: 'M12 3a9 9 0 1 0 9 9',
  up: 'M6 15l6-6 6 6',
} as const // as const, so a name that is not an icon is a type error rather than an empty <path>
/** Circles some icons need on top of their path, since a path alone cannot draw one. */
const CIRCLES: Record<string, [number, number, number]> = {
  mark: [12, 12, 3.2],
  search: [11, 11, 6.5],
  help: [12, 12, 9],
}

export default function Icon({ name, size = 14, width }: { name: keyof typeof PATHS; size?: number; width?: number }) {
  const c = CIRCLES[name]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={width ?? 1.9}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {c && <circle cx={c[0]} cy={c[1]} r={c[2]} />}
      <path d={PATHS[name]} />
    </svg>
  )
}

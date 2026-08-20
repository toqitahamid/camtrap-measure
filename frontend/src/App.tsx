import { useEffect, useState } from 'react'

type Health = { status: string; version: string }

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then(setHealth)
      .catch((e) => setError(String(e)))
  }, [])

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: '2rem' }}>
      <h1>CamTrap Measure</h1>
      {error && <p style={{ color: 'crimson' }}>Engine unreachable: {error}</p>}
      {health ? (
        <p>
          Engine {health.status} — version {health.version}
        </p>
      ) : (
        !error && <p>Connecting to engine…</p>
      )}
    </main>
  )
}

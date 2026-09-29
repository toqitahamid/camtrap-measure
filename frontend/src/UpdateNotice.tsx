/* A new version is waiting (the launcher fetched it behind the window). The bar stays until the user acts:
   Restart now, or Later, which hides it until the next start or until an even newer version turns up. */
import { useEffect, useState } from 'react'
import Icon from './Icon'
import { post } from './ui'

type Update = { ready: boolean; commit: string | null; describe: string | null; can_restart: boolean }

const EVERY_MS = 30_000 // the launcher writes the file a few seconds after the window opens

export default function UpdateNotice() {
  const [update, setUpdate] = useState<Update | null>(null)
  const [later, setLater] = useState<string | null>(null) // the commit "Later" was pressed for
  const [restarting, setRestarting] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    const check = () =>
      fetch('/api/update')
        .then((r) => r.json())
        .then(setUpdate)
        .catch(() => {}) // the engine not answering is said elsewhere; this bar only ever adds news
    void check()
    const id = setInterval(check, EVERY_MS)
    return () => clearInterval(id)
  }, [])

  if (!update?.ready || update.commit === later) return null

  async function restartNow() {
    setProblem(null)
    setRestarting(true)
    const r = await post('/api/update/restart').catch(() => null)
    if (!r || !r.ok) {
      setRestarting(false)
      setProblem(r ? ((await r.json()).detail ?? `Could not restart (${r.status})`) : 'Could not restart.')
    }
    // on success the app closes itself in a moment and the launcher opens the new version
  }

  return (
    <div className="updatebar" role="status">
      <Icon name="sync" size={13} width={2} />
      <span>{restarting ? 'Restarting. The app opens again in a moment.' : 'A new version is ready. Restart to update.'}</span>
      {problem && <span className="updatebar-problem">{problem}</span>}
      <div className="spacer" />
      <button className="btn btn-amber btn-sm" onClick={restartNow} disabled={restarting}>
        Restart now
      </button>
      <button className="btn btn-sm" onClick={() => setLater(update.commit)} disabled={restarting}
              title="Hide this until the app starts again">
        <Icon name="close" size={11} width={2.2} />
        Later
      </button>
    </div>
  )
}

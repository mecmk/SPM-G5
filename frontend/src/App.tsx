import { useEffect, useState } from 'react'
import { getHealth } from './api/health'
import './App.css'

function App() {
  const [status, setStatus] = useState<string>('checking...')

  useEffect(() => {
    getHealth()
      .then((data) => setStatus(data.status))
      .catch(() => setStatus('unreachable'))
  }, [])

  return (
    <main>
      <h1>ConnectSphere</h1>
      <p>Event-planning &amp; venue-booking system — SMU IS212</p>
      <p>
        Backend status: <strong>{status}</strong>
      </p>
    </main>
  )
}

export default App

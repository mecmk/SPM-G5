import { useEffect, useState } from 'react'
import { getHealth } from './api/health'
import { ComponentGalleryPage } from './pages/ComponentGalleryPage'
import './App.css'

function App() {
  const [status, setStatus] = useState<string>('checking...')

  useEffect(() => {
    getHealth()
      .then((data) => setStatus(data.status))
      .catch(() => setStatus('unreachable'))
  }, [])

  // Story c3 - the shared-component gallery is the whole app until real pages replace it.
  return <ComponentGalleryPage backendStatus={status} />
}

export default App

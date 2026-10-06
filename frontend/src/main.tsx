import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

const root = document.getElementById('root')
if (!root) throw new Error('index.html has no #root element: the interface has nowhere to start')  // not React's minified "error #299"

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

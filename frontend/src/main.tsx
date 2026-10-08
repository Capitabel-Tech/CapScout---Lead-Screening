import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

// On a computer the app is shown as a phone-sized frame (390 x 844). When the browser window is
// shorter than that, shrink the whole frame evenly (text and spacing together) so nothing is
// squeezed or cut off. On a real phone the frame is the whole screen and is not scaled.
function fitFrame() {
  const scale = Math.min(1, (window.innerHeight - 24) / 844)
  document.documentElement.style.setProperty('--fit', String(Math.max(0.5, scale)))
}
fitFrame()
window.addEventListener('resize', fitFrame)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

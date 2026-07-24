import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Three self-hosted type roles (see DESIGN.md): Space Grotesk for titles,
// JetBrains Mono for figures and data, Albert Sans for body. Bundled by Vite so
// the static GitHub Pages build needs no font CDN at runtime.
import '@fontsource-variable/space-grotesk'
import '@fontsource-variable/jetbrains-mono'
import '@fontsource/albert-sans/400.css'
import '@fontsource/albert-sans/500.css'
import '@fontsource/albert-sans/600.css'

import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

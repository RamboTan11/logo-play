import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { ClientLanguageProvider } from './i18n/clientLanguage'
import { router } from './router'
import './styles/global.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ClientLanguageProvider><RouterProvider router={router} /></ClientLanguageProvider>
  </StrictMode>,
)

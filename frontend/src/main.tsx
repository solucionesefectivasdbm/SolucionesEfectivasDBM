import React from 'react'
import ReactDOM from 'react-dom/client'
import { Toaster } from 'react-hot-toast'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
    <Toaster
      position="top-right"
      toastOptions={{
        duration: 4000,
        style: {
          background: '#1A3A6B',
          color: '#fff',
          fontFamily: 'Plus Jakarta Sans, sans-serif',
          fontSize: '14px',
        },
        success: { iconTheme: { primary: '#F5C518', secondary: '#1A3A6B' } },
        error: { style: { background: '#C0392B' } },
      }}
    />
  </React.StrictMode>
)

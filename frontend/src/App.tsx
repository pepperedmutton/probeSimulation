import './App.css'
import { LangmuirIVSimulator } from './pages/LangmuirIVSimulator'

function App() {
  return (
    <div className="app-shell">
      <header className="site-header">
        <div className="brand">
          <span>Langmuir Toolkit</span>
        </div>
        <div className="subtitle">Dynamic RF Langmuir I-V simulation</div>
      </header>
      <main className="app">
        <LangmuirIVSimulator />
      </main>
    </div>
  )
}

export default App

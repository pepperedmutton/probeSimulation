import './App.css'
import { LangmuirIVSimulator } from './pages/LangmuirIVSimulator'
import { TestChart } from './pages/TestChart'

function App() {
  // Set to true to show test chart
  const showTestChart = false
  
  return (
    <div className="app-shell">
      <header className="site-header">
        <div className="brand">
          <span>Langmuir Toolkit</span>
        </div>
        <div className="subtitle">Dynamic RF Langmuir I-V simulation</div>
      </header>
      <main className="app">
        {showTestChart ? <TestChart /> : <LangmuirIVSimulator />}
      </main>
    </div>
  )
}

export default App

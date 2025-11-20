import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

// Minimal test data
const testData = [
  { x: -30, y: -0.001 },
  { x: -25, y: -0.0005 },
  { x: -20, y: -0.0002 },
  { x: -15, y: 0 },
  { x: -10, y: 0.0001 },
  { x: -5, y: 0.0003 },
  { x: 0, y: 0.0005 },
  { x: 5, y: 0.0008 },
  { x: 10, y: 0.0012 },
  { x: 15, y: 0.0015 },
  { x: 20, y: 0.002 },
]

export function TestChart() {
  console.log('TestChart rendering with data:', testData)
  
  return (
    <div style={{ width: '100%', height: 400, background: 'white', padding: 20 }}>
      <h3>Test Chart - Should show a simple line</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={testData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="x" />
          <YAxis />
          <Tooltip />
          <Line type="monotone" dataKey="y" stroke="#8884d8" strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

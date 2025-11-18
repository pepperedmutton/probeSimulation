const backendUrl = process.argv[2] ?? 'http://localhost:8000'

const payload = {
  plasma: {
    ne: 5e15,
    te_eV: 3,
    vs: 0,
    gas_type: 'Ar',
  },
  probe: {
    area: 1e-6,
    radius: 1e-3,
    length: 5e-3,
    capacitance: 1e-12,
  },
  rf: {
    frequency_hz: 13.56e6,
    te_amplitude_ev: 0.5,
    ne_amplitude: 1e14,
    vs_amplitude_v: 2.0,
  },
  time_range: {
    total_time_s: 1e-6,
    dt_s: 1e-9,
  },
  vp_initial: -10,
  model: 'ABR',
  integrator: 'rk4',
}

async function checkCors() {
  const response = await fetch(`${backendUrl}/api/iv/dynamic`, {
    method: 'OPTIONS',
    headers: {
      Origin: 'http://localhost:5173',
      'Access-Control-Request-Method': 'POST',
      'Access-Control-Request-Headers': 'content-type',
    },
  })

  return {
    status: response.status,
    allowOrigin: response.headers.get('access-control-allow-origin'),
    allowMethods: response.headers.get('access-control-allow-methods'),
    allowHeaders: response.headers.get('access-control-allow-headers'),
  }
}

async function runPost() {
  const response = await fetch(`${backendUrl}/api/iv/dynamic`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Origin: 'http://localhost:5173',
    },
    body: JSON.stringify(payload),
  })

  const text = await response.text()
  return { status: response.status, body: text }
}

;(async () => {
  try {
    const corsResult = await checkCors()
    console.log('Preflight response:', corsResult)

    const result = await runPost()
    console.log('POST response status:', result.status)
    console.log('POST response body:', result.body)
  } catch (error) {
    console.error('Connectivity test failed:', error)
    process.exit(1)
  }
})()

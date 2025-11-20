// Test script to paste in browser console
(async () => {
    console.log('Testing streaming API...');
    
    const payload = {
        plasma: {ne: 5e15, te_eV: 3.0, vs: 0.0, gas_type: "Ar"},
        probe: {area: 1e-6, radius: 1e-3, length: 5e-3, capacitance: 1e-12},
        rf: {frequency_hz: 13560000, te_amplitude_ev: 0.5, ne_amplitude: 1e14, vs_amplitude_v: 2.0},
        time_range: {total_time_s: 0.01, dt_s: 1e-8},
        vp_initial: -30.0,
        vp_final: 20.0,
        model: "ABR",
        integrator: "rk4"
    };
    
    try {
        const response = await fetch('http://localhost:8000/api/iv/dynamic/stream', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        
        console.log('Response status:', response.status);
        console.log('Response headers:', [...response.headers.entries()]);
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let chunkCount = 0;
        
        while (true) {
            const {done, value} = await reader.read();
            if (done) {
                console.log('Stream done!');
                break;
            }
            
            buffer += decoder.decode(value, {stream: true});
            const lines = buffer.split('\n\n');
            buffer = lines.pop() || '';
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    chunkCount++;
                    const data = JSON.parse(line.slice(6));
                    console.log(`Chunk ${chunkCount}:`, {
                        points: data.time?.length || 0,
                        progress: data.progress ? (data.progress * 100).toFixed(1) + '%' : 'metadata'
                    });
                }
            }
        }
        
        console.log(`Total chunks received: ${chunkCount}`);
        
    } catch (err) {
        console.error('Error:', err);
    }
})();

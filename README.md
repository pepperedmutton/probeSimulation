# Langmuir Probe RF Response Simulator

Browser-delivered toolkit for planning Langmuir-probe measurements in RF plasmas. The system now focuses entirely on the dynamic Langmuir I‑V solver: a Python/FastAPI backend integrates the time-domain physics kernel and a React front-end lets researchers explore how RF frequency modulates probe traces.

## Project layout

- `backend/`: FastAPI application containing the Langmuir I‑V modules under `app/iv_simulation/`.
- `frontend/`: React + Vite SPA that hosts the Langmuir I‑V simulator UI.
- `docs/langmuir_iv.md`: Notes on the implemented I‑V physics and the JSON contract for `/api/iv/dynamic`.

## Getting started

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# Generate text reports (writes backend/iv_results.txt)
python -m app.iv_simulation.report_cases
```

The API exposes:

- `/health` for readiness checks.
- `/api/iv/dynamic` for the Langmuir time-domain responses (see `docs/langmuir_iv.md` for schema details).

### Frontend

```powershell
cd frontend
copy .env.example .env   # optional, overrides the API base URL
npm install
npm run dev -- --open
```

By default, the UI targets `http://localhost:8000`. Adjust `VITE_API_BASE_URL` if the backend runs elsewhere. The default route renders the Langmuir I‑V module, which drives the dynamic backend endpoint.

## Next steps

1. Refine the ABR/BRL/Child-Langmuir implementations to use tabulated Poisson solutions instead of heuristic factors.
2. Extend the API to serve additional diagnostics (e.g., phase-space snapshots) and add automated tests (Pytest + React Testing Library) once the physics kernel stabilizes.
3. Add presets and persistence so frequency sweeps can be replayed quickly from the UI.

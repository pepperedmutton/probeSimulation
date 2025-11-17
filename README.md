# Langmuir Probe Toolkit

This repository bundles **two complementary plasma models** behind a single FastAPI backend and a React-based Web UI:

1. **0D sheath solver** – a classical collisionless sheath calculation that turns bulk plasma knobs into Langmuir-probe characteristic parameters (Debye length, floating potential, ion saturation current, etc.). It assumes a uniform, quasi-neutral plasma, thin sheath, cold ions, and Maxwellian electrons. No spatial grids or particle tracking are involved.
2. **Custom 2D electrostatic PIC** – a minimal particle-in-cell implementation that resolves a rectangular domain containing an embedded cylindrical probe. It performs bias sweeps, streams snapshots/IV points over WebSocket, and is the only source of time-resolved probe currents in this project.

The README previously implied a single model. This document separates the two solvers, explains when they are used, and walks through the APIs and UI.

---

## Repository Layout

```
probeSimulation/
├── backend/
│   ├── app/
│   │   ├── main.py        # FastAPI routes orchestrating both models
│   │   ├── pic.py         # 1D vertical PIC slice helper
│   │   ├── pic2d.py       # Full 2D electrostatic PIC implementation
│   │   └── sim_manager.py # Async job runner + WebSocket broadcast
│   ├── requirements.txt
│   └── start.ps1          # One-click dependency install + dev servers
└── frontend/
    ├── src/
    │   ├── App.tsx        # UI logic (forms, live plots, streaming view)
    │   └── lib/api.ts     # Typed API client
    └── package.json
```

The backend exposes REST + WebSocket endpoints; the frontend calls them via `fetch` or WS and renders derived metrics, IV curves, and PIC visualizations.

---

## Model Overview

### 1. Zero-Dimensional Collisionless Sheath

*Location:* `backend/app/main.py::run_sheath_model`  
*Endpoint:* `POST /simulate` and indirectly `/iv-curve`

Inputs (`PlasmaInput`):

- Neutral gas pressure, ionization fraction, ion species (`Ar`/`Xe`), optional manual densities
- Electron/ion energies (in eV) and plasma potential

Outputs (`SheathResult`):

- Debye length, sheath thickness, ion sound speed
- Floating potential, plasma frequencies, quasi-neutrality ratio
- Ion saturation current estimate and probe temperature

Usage:

1. `/simulate` returns the values above for quick diagnostics.
2. `/iv-curve` first runs the sheath solver, then builds a synthetic IV curve by combining Bohm ion flux and Maxwellian electron collection. This is still a 0D analytic curve – useful for intuition or UI previews.

Limitations: assumes collisionless, thin sheath, single charge state, no magnetic field, and cold ions (`Ti << Te`). It never resolves spatial variation.

### 2. Two-Dimensional Electrostatic PIC

*Location:* `backend/app/pic2d.py` (+ `sim_manager.py`)  
*Endpoints:* `/pic/jobs`, `/pic/jobs/{id}`, `/pic/jobs/{id}/iv`, `WS /ws/pic/{id}`

Features:

- Structured Cartesian grid, Gauss-Seidel Poisson solve, bilinear field interpolation
- Independent electron/ion species with macroparticle weights
- Bias-scan controller (ramp → measure) producing averaged IV points
- Streaming snapshots (potential, charge density, sampled particles) over WebSocket

Workflow:

1. Frontend gathers plasma/domain/probe/bias configuration (`PICJobRequest` in `src/lib/api.ts`).
2. `POST /pic/jobs` creates an async simulation job; response returns `job_id`.
3. Frontend opens `ws://.../ws/pic/{job_id}` to receive:
   - `status` updates (pending/running/completed + progress)
   - `snapshot` payloads for visualization
   - `iv_point` data (averaged total/electron/ion currents per bias)
   - `error` notifications
4. Completed IV data can be pulled via `GET /pic/jobs/{job_id}/iv`.

An auxiliary `/pic-slice` endpoint wraps `app/pic.py`, which is a 1D vertical PIC slice meant for quick experimentation; it is separate from the full 2D solver but uses similar physics.

---

## Running the Project

Use the provided PowerShell script for the smoothest experience (it bootstraps dependencies and launches both dev servers). From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

This performs the following steps:

1. Creates/updates `backend/.venv` (Python 3.11) and installs `backend/requirements.txt`.
2. Installs frontend dependencies if `frontend/node_modules` is missing.
3. Opens two terminals:
   - Backend: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
   - Frontend: `npm run dev` (Vite, default http://localhost:5173)

Use `-InstallOnly` if you just want dependencies prepared without starting the servers.

Manual alternative (already executed by `start.ps1`):

```powershell
# Backend
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd ../frontend
npm install
npm run dev
```

---

## API Summary

| Endpoint | Purpose | Model |
| --- | --- | --- |
| `GET /health` | Service probe | – |
| `POST /simulate` | Return sheath parameters | 0D |
| `POST /iv-curve` | Generate analytic IV curve | 0D (uses `/simulate`) |
| `POST /pic-slice` | Quick 1D slice PIC | 1D PIC helper |
| `POST /pic/jobs` | Start full 2D PIC bias scan | 2D PIC |
| `GET /pic/jobs` | List running jobs | 2D PIC |
| `GET /pic/jobs/{id}` | Job status | 2D PIC |
| `GET /pic/jobs/{id}/iv` | Collected IV points | 2D PIC |
| `WS /ws/pic/{id}` | Stream status/snapshots/IV points | 2D PIC |

Frontend Types (`frontend/src/lib/api.ts`) mirror the Pydantic models for type-safe calls.

---

## Frontend Highlights

- **Parameter panel** – set neutral pressure, ionization fraction, temperatures, potential, and whether density is derived or specified manually. Derived metrics (Debye length, Bohm velocity, plasma frequencies) update instantly using 0D formulas.
- **Scan settings** – choose bias range, number of samples, and an approximate scan duration. These feed into PIC job creation.
- **PIC controls** – when “Run PIC” is pressed, the UI computes grid size/particle counts from the current Debye length, sends a `PICJobRequest`, and starts listening for WebSocket updates.
- **Visuals** – snapshots are rendered as color maps with particle markers; IV curves are updated in real time as `iv_point` events arrive.

The UI is meant to help compare 0D estimates against the richer behavior of the PIC solver.

---

## Extending the Models

- **Add ion species** – update `ION_MASS_MAP` in `backend/app/main.py` (and optionally front-end presets) with new mass values.
- **Change probe geometry** – tweak `frontend/src/App.tsx` defaults or pass explicit dimensions via the PIC request.
- **Physics upgrades** – potential next steps include collisions, external magnetic fields, or alternative probe shapes. `pic2d.py` is organized so you can replace the field solve, push, or boundary logic incrementally.

When modifying the PIC solver, remember to keep the WebSocket payload schema stable or adjust the TypeScript definitions accordingly.

---

## License & Usage

The project is distributed for research/educational purposes. Please verify the assumptions of each model before using the outputs to interpret experimental data, especially outside the collisionless, low-pressure regime.

Happy probing! :satellite:

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

### Text-Based Runs & Diagnostics

For scripted sweeps or offline debugging you can run the PIC solver directly from YAML/JSON. The CLI reuses the same `ProbePICSimulation` core as the Web UI while enabling deterministic input files and on-disk diagnostics.

```
cd backend
python -m app.run_config configs/xe_benchmark.yaml
```

Config sections:

- `plasma`: gas (`Ar`/`Xe`), neutral pressure/temperature, ionization fraction, electron/ion temperatures, and bulk potential. Derived values (neutral density, plasma density, Debye length, plasma frequency) are logged automatically.
- `domain`: sizes in meters, grid resolution, macroparticles, Poisson iterations, relaxation steps, RNG seed, etc.
- `probe`: circle or rectangle geometry specified in meters.
- `bias_scan`: either explicit `bias_values` or `min/max/step`, along with ramp/settle/measure steps.
- `diagnostics`: optional snapshot support. Provide a `snapshot_dir`, list of `snapshot_steps` (and/or `snapshot_interval`), `summary_path`, downsample factor, and optional particle sampling limits.
- `window_fraction_x` / `window_fraction_y`: (optional) two-element lists `[start, end]` defining which portion of the large domain is streamed/saved. Use a big domain (many λ_D) to suppress edge effects, then pick a central window (e.g., `[0.375, 0.625]`) so the UI still shows the familiar probe region.
- `planar_symmetry`: set to `true` to collapse the solver into a quasi-1D sheath above a planar probe. When this mode is enabled, you can supply `planar_effective_area_m2` so the strip modeled in x represents the physical collection area of your probe (defaults to `lx × domain_depth` if omitted).

Snapshots are written as `.npz` files containing downsampled `φ`, `ρ`, `E`, probe currents, and particle counts; they can be inspected with NumPy/Matplotlib. The summary text file mirrors the metadata, captured snapshots, and the final I–V values returned by the run.

### Xe Benchmark Workflow

`backend/configs/xe_benchmark.yaml` implements the Xe 0.5 Pa / 5 % / 15 V benchmark referenced in the task:

- Derived density `n₀ ≈ 6×10¹⁸ m⁻³`, Debye length `λ_D ≈ 16 µm`, and `T_e = 3 eV`, `T_i = 0.05 eV`.
- Grid `96×120` over a 2.4 mm × 1.6 mm domain resolves several Debye lengths surrounding the probe (radius 80 µm, positioned near the lower boundary).
- `particles_per_species = 6000`, `poisson_iterations = 80`, `relaxation_steps = 60`, and a single bias value (15 V) stabilize the sheath before averaging probe currents.
- Diagnostics capture snapshots at steps `[0,100,200,400,600,800]` into `backend/outputs/xe_benchmark/` and write a run summary with derived parameters plus averaged probe currents.

You can duplicate/adjust this config, rerun `python -m app.run_config`, and cross-check the snapshots with the Web UI. The API endpoints remain backward compatible—the CLI simply exposes the same solver with extra diagnostics for automated testing. Need a fast smoke test? `backend/configs/xe_quicktest.yaml` reduces the grid and step counts so you can verify code changes in ~30 s before launching the heavier benchmark job. In planar mode remember that a plate biased near the plasma potential collects the electron saturation current (≈0.8 A for the quick test, ≈3 A for the larger benchmark area); scan lower biases to approach the floating condition where ion and electron fluxes balance. Both configs now run on domains several Debye lengths wider/taller than the displayed window—controlled via `window_fraction_x/y`—so the central sheath looks uniform even though boundaries remain far away.

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
好吧，我承认在数学上实现这个无限长的导体的计算是不可能的。那你就要让仿真的计算域远大于德拜长度，然后只取中心的一小块，即我们现有仿真域的大小，来呈现结果，这样可以最大程度的抑制导体的有限尺寸效应，同时又不让计算量太高。

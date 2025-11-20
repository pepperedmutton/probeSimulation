"""FastAPI router exposing Langmuir IV simulations."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Iterable, TextIO

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .schemas import IVDynamicRequest, IVDynamicResponse
from .solver import DynamicIVResult, compute_dynamic_iv, compute_dynamic_iv_streaming


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/iv", tags=["langmuir-iv"])

# Calculate project root: backend/app/iv_simulation/api.py -> go up 3 levels to project root
EXPORT_DIR = Path(__file__).resolve().parents[3] / "iv_exports"
FILE_HEADER = "# Voltage(V)\tTotal_Current(A)\tIon_Current(A)\tElectron_Current(A)\n"

# Debug: print at module load to verify path calculation
_api_file = Path(__file__).resolve()
print(f"[IV_EXPORT_DEBUG] ========================================")
print(f"[IV_EXPORT_DEBUG] Module loaded: {_api_file}")
print(f"[IV_EXPORT_DEBUG] parents[0] (iv_simulation): {_api_file.parents[0]}")
print(f"[IV_EXPORT_DEBUG] parents[1] (app): {_api_file.parents[1]}")
print(f"[IV_EXPORT_DEBUG] parents[2] (backend): {_api_file.parents[2]}")
print(f"[IV_EXPORT_DEBUG] parents[3] (probe): {_api_file.parents[3]}")
print(f"[IV_EXPORT_DEBUG] EXPORT_DIR set to: {EXPORT_DIR.absolute()}")
print(f"[IV_EXPORT_DEBUG] EXPORT_DIR exists: {EXPORT_DIR.exists()}")
print(f"[IV_EXPORT_DEBUG] ========================================")


def _timestamped_export_path() -> Path:
    print(f"[IV_EXPORT_DEBUG] Creating export directory: {EXPORT_DIR.absolute()}")
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[IV_EXPORT_DEBUG] Export directory exists: {EXPORT_DIR.exists()}")
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
    export_path = EXPORT_DIR / f"{timestamp}.txt"
    print(f"[IV_EXPORT_DEBUG] Generated export file path: {export_path.absolute()}")
    return export_path


def _write_rows(
    handle: TextIO,
    vp_values: Iterable[float],
    total_values: Iterable[float],
    ion_values: Iterable[float],
    electron_values: Iterable[float],
) -> None:
    for vp_val, total_val, ion_val, electron_val in zip(
        vp_values, total_values, ion_values, electron_values
    ):
        handle.write(f"{vp_val}\t{total_val}\t{ion_val}\t{electron_val}\n")


def save_result_to_file(
    vp_values: Iterable[float],
    total_values: Iterable[float],
    ion_values: Iterable[float],
    electron_values: Iterable[float],
) -> str:
    """Persist the simulation arrays to disk and return the file path."""
    print("[IV_EXPORT_DEBUG] save_result_to_file() called")
    export_path = _timestamped_export_path()
    print(f"[IV_EXPORT_DEBUG] Opening file for writing: {export_path}")
    
    vp_list = list(vp_values)
    total_list = list(total_values)
    ion_list = list(ion_values)
    electron_list = list(electron_values)
    num_points = len(vp_list)
    print(f"[IV_EXPORT_DEBUG] Writing {num_points} data points to file")
    
    with export_path.open("w", encoding="utf-8") as handle:
        handle.write(FILE_HEADER)
        _write_rows(handle, vp_list, total_list, ion_list, electron_list)
    
    print(f"[IV_EXPORT_DEBUG] File written successfully: {export_path}")
    print(f"[IV_EXPORT_DEBUG] File size: {export_path.stat().st_size} bytes")
    return str(export_path)


class StreamingResultWriter:
    """Incrementally writes streaming chunks to a timestamped file."""

    def __init__(self) -> None:
        print("[IV_EXPORT_DEBUG] StreamingResultWriter initialized")
        self.path = _timestamped_export_path()
        print(f"[IV_EXPORT_DEBUG] Opening streaming file: {self.path}")
        self._handle = self.path.open("w", encoding="utf-8")
        self._handle.write(FILE_HEADER)
        print(f"[IV_EXPORT_DEBUG] Header written to streaming file")
        self._chunks_written = 0

    def write_chunk(
        self,
        vp_values: Iterable[float],
        total_values: Iterable[float],
        ion_values: Iterable[float],
        electron_values: Iterable[float],
    ) -> None:
        vp_list = list(vp_values)
        chunk_size = len(vp_list)
        self._chunks_written += 1
        print(f"[IV_EXPORT_DEBUG] Writing chunk #{self._chunks_written} ({chunk_size} points) to {self.path.name}")
        _write_rows(self._handle, vp_list, list(total_values), list(ion_values), list(electron_values))
        self._handle.flush()
        print(f"[IV_EXPORT_DEBUG] Chunk #{self._chunks_written} flushed to disk")

    def close(self) -> None:
        if not self._handle.closed:
            print(f"[IV_EXPORT_DEBUG] Closing streaming file: {self.path}")
            print(f"[IV_EXPORT_DEBUG] Total chunks written: {self._chunks_written}")
            self._handle.close()
            print(f"[IV_EXPORT_DEBUG] File closed successfully")
            print(f"[IV_EXPORT_DEBUG] Final file size: {self.path.stat().st_size} bytes")
        else:
            print(f"[IV_EXPORT_DEBUG] File already closed: {self.path}")



@router.post("/dynamic", response_model=IVDynamicResponse)
def run_dynamic_simulation(request: IVDynamicRequest) -> IVDynamicResponse:
    try:
        result: DynamicIVResult = compute_dynamic_iv(
            ne_base=request.plasma.ne,
            te_ev_base=request.plasma.te_eV,
            vs_base=request.plasma.vs,
            gas_type=request.plasma.gas_type,
            mi_custom=request.plasma.mi_custom,
            area=request.probe.area,
            radius=request.probe.radius,
            length=request.probe.length,
            capacitance=request.probe.capacitance,
            model=request.model,
            frequency_hz=request.rf.frequency_hz,
            te_amplitude_ev=request.rf.te_amplitude_ev,
            ne_amplitude=request.rf.ne_amplitude,
            vs_amplitude_v=request.rf.vs_amplitude_v,
            total_time_s=request.time_range.total_time_s,
            dt_s=request.time_range.dt_s,
            vp_initial=request.vp_initial,
            vp_final=request.vp_final,
            voltage_step_rf_cycles=request.time_range.voltage_step_rf_cycles,
            integrator=request.integrator,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    vp_values = result.vp.tolist()
    total_values = result.i_total.tolist()
    ion_values = result.ii.tolist()
    electron_values = result.ie.tolist()
    saved_file = save_result_to_file(vp_values, total_values, ion_values, electron_values)

    metadata = dict(result.metadata) if result.metadata else {}
    metadata["saved_file"] = saved_file

    return IVDynamicResponse(
        time=result.time.tolist(),
        vp=vp_values,
        ne=result.ne.tolist(),
        te_eV=result.te_eV.tolist(),
        vs=result.vs.tolist(),
        ie=electron_values,
        ii=ion_values,
        i_total=total_values,
        metadata=metadata,
    )


@router.post("/dynamic/stream")
async def run_dynamic_simulation_stream(request: IVDynamicRequest) -> StreamingResponse:
    """Streaming version that sends data as simulation progresses."""
    
    print(f"[IV_EXPORT_DEBUG] ===== STREAM ENDPOINT CALLED =====")
    print(f"[IV_EXPORT_DEBUG] Request received: plasma.ne={request.plasma.ne}, rf.frequency_hz={request.rf.frequency_hz}")

    result_writer = StreamingResultWriter()

    async def generate_stream() -> AsyncGenerator[str, None]:
        print(f"[IV_EXPORT_DEBUG] Stream generator started")
        try:
            chunk_size = 20000  # Send updates every 20000 points to avoid overwhelming UI
            print(f"[IV_EXPORT_DEBUG] Starting compute_dynamic_iv_streaming with chunk_size={chunk_size}")
            async for chunk_data in compute_dynamic_iv_streaming(
                ne_base=request.plasma.ne,
                te_ev_base=request.plasma.te_eV,
                vs_base=request.plasma.vs,
                gas_type=request.plasma.gas_type,
                mi_custom=request.plasma.mi_custom,
                area=request.probe.area,
                radius=request.probe.radius,
                length=request.probe.length,
                capacitance=request.probe.capacitance,
                model=request.model,
                frequency_hz=request.rf.frequency_hz,
                te_amplitude_ev=request.rf.te_amplitude_ev,
                ne_amplitude=request.rf.ne_amplitude,
                vs_amplitude_v=request.rf.vs_amplitude_v,
                total_time_s=request.time_range.total_time_s,
                dt_s=request.time_range.dt_s,
                vp_initial=request.vp_initial,
                vp_final=request.vp_final,
                voltage_step_rf_cycles=request.time_range.voltage_step_rf_cycles,
                integrator=request.integrator,
                chunk_size=chunk_size,
            ):
                print(f"[IV_EXPORT_DEBUG] Received chunk from solver, keys: {list(chunk_data.keys())}")
                if "vp" in chunk_data:
                    num_points = len(chunk_data.get("vp", []))
                    print(f"[IV_EXPORT_DEBUG] Chunk contains {num_points} data points, writing to file...")
                    result_writer.write_chunk(
                        chunk_data.get("vp", []),
                        chunk_data.get("i_total", []),
                        chunk_data.get("ii", []),
                        chunk_data.get("ie", []),
                    )
                    print(f"[IV_EXPORT_DEBUG] Chunk written successfully")
                else:
                    print(f"[IV_EXPORT_DEBUG] Chunk is metadata-only, not writing to file")
                metadata_chunk = chunk_data.get("metadata")
                if isinstance(metadata_chunk, dict):
                    metadata_chunk["saved_file"] = str(result_writer.path)
                yield f"data: {json.dumps(chunk_data)}\n\n"

        except Exception as exc:
            print(f"[IV_EXPORT_DEBUG] !!! Exception in stream generator: {exc}")
            import traceback
            traceback.print_exc()
            error_msg = {"error": str(exc)}
            yield f"data: {json.dumps(error_msg)}\n\n"
        finally:
            print(f"[IV_EXPORT_DEBUG] Stream generator finished, calling close()")
            result_writer.close()

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )

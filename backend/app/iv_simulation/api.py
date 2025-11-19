"""FastAPI router exposing Langmuir IV simulations."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Iterable, TextIO

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .schemas import IVDynamicRequest, IVDynamicResponse
from .solver import DynamicIVResult, compute_dynamic_iv, compute_dynamic_iv_streaming


router = APIRouter(prefix="/api/iv", tags=["langmuir-iv"])

EXPORT_DIR = Path(__file__).resolve().parents[3] / "iv_exports"
FILE_HEADER = "# Voltage(V)\tTotal_Current(A)\tIon_Current(A)\tElectron_Current(A)\n"


def _timestamped_export_path() -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
    return EXPORT_DIR / f"{timestamp}.txt"


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
    export_path = _timestamped_export_path()
    with export_path.open("w", encoding="utf-8") as handle:
        handle.write(FILE_HEADER)
        _write_rows(handle, vp_values, total_values, ion_values, electron_values)
    return str(export_path)


class StreamingResultWriter:
    """Incrementally writes streaming chunks to a timestamped file."""

    def __init__(self) -> None:
        self.path = _timestamped_export_path()
        self._handle = self.path.open("w", encoding="utf-8")
        self._handle.write(FILE_HEADER)

    def write_chunk(
        self,
        vp_values: Iterable[float],
        total_values: Iterable[float],
        ion_values: Iterable[float],
        electron_values: Iterable[float],
    ) -> None:
        _write_rows(self._handle, vp_values, total_values, ion_values, electron_values)

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.close()



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

    result_writer = StreamingResultWriter()

    async def generate_stream() -> AsyncGenerator[str, None]:
        try:
            chunk_size = 20000  # Send updates every 20000 points to avoid overwhelming UI
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
                if "vp" in chunk_data:
                    result_writer.write_chunk(
                        chunk_data.get("vp", []),
                        chunk_data.get("i_total", []),
                        chunk_data.get("ii", []),
                        chunk_data.get("ie", []),
                    )
                metadata_chunk = chunk_data.get("metadata")
                if isinstance(metadata_chunk, dict):
                    metadata_chunk["saved_file"] = str(result_writer.path)
                yield f"data: {json.dumps(chunk_data)}\n\n"

        except Exception as exc:
            error_msg = {"error": str(exc)}
            yield f"data: {json.dumps(error_msg)}\n\n"
        finally:
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

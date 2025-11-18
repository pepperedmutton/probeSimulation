"""FastAPI router exposing Langmuir IV simulations."""

from __future__ import annotations

import json
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .schemas import IVDynamicRequest, IVDynamicResponse
from .solver import DynamicIVResult, compute_dynamic_iv, compute_dynamic_iv_streaming


router = APIRouter(prefix="/api/iv", tags=["langmuir-iv"])


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
            integrator=request.integrator,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return IVDynamicResponse(
        time=result.time.tolist(),
        vp=result.vp.tolist(),
        ne=result.ne.tolist(),
        te_eV=result.te_eV.tolist(),
        vs=result.vs.tolist(),
        ie=result.ie.tolist(),
        ii=result.ii.tolist(),
        i_total=result.i_total.tolist(),
        metadata=result.metadata,
    )


@router.post("/dynamic/stream")
async def run_dynamic_simulation_stream(request: IVDynamicRequest) -> StreamingResponse:
    """Streaming version that sends data as simulation progresses."""
    
    async def generate_stream() -> AsyncGenerator[str, None]:
        try:
            chunk_size = 1000  # Send updates every 1000 points
            
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
                integrator=request.integrator,
                chunk_size=chunk_size,
            ):
                # Send each chunk as Server-Sent Event
                yield f"data: {json.dumps(chunk_data)}\n\n"
                
        except ValueError as exc:
            error_msg = {"error": str(exc)}
            yield f"data: {json.dumps(error_msg)}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

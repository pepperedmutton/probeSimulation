from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .iv_simulation.api import router as iv_router

app = FastAPI(
    title="Langmuir Probe RF Response API",
    version="0.1.0",
    description="Backend service that evaluates the time-domain Langmuir probe solver.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(iv_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

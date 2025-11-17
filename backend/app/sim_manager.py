from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Dict, List, Optional

from .pic2d import BiasScanSettings, ProbePICSimulation, SimulationConfig


class SimulationJob:
    """Manages one long-running PIC simulation and its subscribers."""

    def __init__(self, config: SimulationConfig, scan: BiasScanSettings):
        self.job_id = uuid.uuid4().hex
        self.simulation = ProbePICSimulation(config)
        self.scan = scan
        self.status = "pending"
        self.error: Optional[str] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.task: Optional[asyncio.Task] = None
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self.last_snapshot: Optional[Dict] = None
        self.iv_data: List[Dict[str, float]] = []
        self.completed_bias_points = 0
        self.total_bias_points = len(scan.bias_values)

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self.task is not None:
            return
        self.loop = loop
        self.task = loop.create_task(self._run())

    async def _run(self) -> None:
        self.status = "running"
        self._broadcast(self._status_payload())
        try:
            await asyncio.to_thread(self._execute)
            self.status = "completed"
            self._broadcast(self._status_payload())
        except Exception as exc:  # pragma: no cover - surfaced via HTTP
            self.error = str(exc)
            self.status = "failed"
            self._broadcast({"type": "error", "message": self.error})
            self._broadcast(self._status_payload())

    def _execute(self) -> None:
        def callback(payload: Dict) -> None:
            if self.loop is None:
                return
            self.loop.call_soon_threadsafe(self._process_callback, payload)

        self.simulation.run_bias_scan(self.scan, callback)

    def _process_callback(self, payload: Dict) -> None:
        kind = payload.get("type")
        if kind == "snapshot":
            self.last_snapshot = payload
        elif kind == "iv_point":
            data = payload.get("data")
            if data:
                self.iv_data.append(data)
                self.completed_bias_points = payload.get("bias_index", len(self.iv_data) - 1) + 1
        self._broadcast(payload)

    def _broadcast(self, payload: Dict) -> None:
        if payload is None:
            return
        dead: List[asyncio.Queue] = []
        with self._lock:
            targets = list(self._subscribers)
        for queue in targets:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(payload)
                except asyncio.QueueFull:
                    dead.append(queue)
        if dead:
            with self._lock:
                for queue in dead:
                    self._subscribers.discard(queue)

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=10)
        with self._lock:
            self._subscribers.add(queue)
        await queue.put(self._status_payload())
        if self.last_snapshot:
            await queue.put(self.last_snapshot)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def _status_payload(self) -> Dict:
        return {
            "type": "status",
            "job_id": self.job_id,
            "status": self.status,
            "completed_bias_points": self.completed_bias_points,
            "total_bias_points": self.total_bias_points,
            "error": self.error,
        }

    def to_dict(self) -> Dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "error": self.error,
            "completed_bias_points": self.completed_bias_points,
            "total_bias_points": self.total_bias_points,
            "iv_points": len(self.iv_data),
        }


class SimulationManager:
    """Tracks all currently running simulation jobs."""

    def __init__(self) -> None:
        self._jobs: Dict[str, SimulationJob] = {}
        self._lock = threading.Lock()

    def create_job(self, config: SimulationConfig, scan: BiasScanSettings) -> SimulationJob:
        job = SimulationJob(config, scan)
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[SimulationJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> List[Dict]:
        with self._lock:
            return [job.to_dict() for job in self._jobs.values()]


simulation_manager = SimulationManager()


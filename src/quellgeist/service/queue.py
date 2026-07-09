"""In-process job queue + worker pool (Wave 7, T7.3; DR-0023 decision 1).

The async ingress stays responsive by handing accepted incidents to a bounded pool of
async workers; each worker runs the **synchronous** ``run_loop`` (via the orchestrator)
in a thread executor, so the event loop is never blocked on model I/O. Concurrency lives
here, never in the frozen loop. The queue is created inside ``start`` (on the running
loop), so building the pool at import time needs no event loop.
"""

from __future__ import annotations

import asyncio

from quellgeist.observability import get_logger
from quellgeist.orchestrator import investigate
from quellgeist.service.config import ServiceConfig
from quellgeist.store import connect, dao

_log = get_logger("quellgeist.service.worker")


class WorkerPool:
    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        self.queue: asyncio.Queue[str] | None = None
        self._workers: list[asyncio.Task] = []

    async def start(self) -> None:
        self.queue = asyncio.Queue(maxsize=self.config.queue_maxsize)
        self._workers = [
            asyncio.create_task(self._worker(i)) for i in range(self.config.num_workers)
        ]

    async def stop(self, *, drain_timeout: float = 30.0) -> None:
        """Drain in-flight work BEFORE cancelling workers. Cancelling a task blocked on
        ``run_in_executor`` does not stop the underlying thread (it would keep writing to
        the store after shutdown — review: orphaned executor thread), so we wait for the
        queue to fully drain (each in-flight item calls ``task_done`` when its executor
        run returns) with a bound, then cancel the now-idle workers."""
        if self.queue is not None:
            try:
                await asyncio.wait_for(self.queue.join(), timeout=drain_timeout)
            except TimeoutError:
                _log.warning("worker_stop_drain_timeout", pending=self.queue.qsize())
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    async def enqueue(self, incident_id: str) -> None:
        if self.queue is None:
            raise RuntimeError("worker pool not started")
        await self.queue.put(incident_id)

    async def _worker(self, n: int) -> None:
        queue = self.queue
        if queue is None:  # start() sets it before creating workers; defensive
            return
        while True:
            incident_id = await queue.get()
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._process_sync, incident_id
                )
            except Exception as exc:  # never let one bad incident kill a worker
                _log.warning(
                    "worker_error", worker=n, incident=incident_id, error=str(exc)
                )
            finally:
                queue.task_done()

    def _process_sync(self, incident_id: str) -> None:
        """Runs in an executor thread: load the incident, then investigate over its
        isolated snapshot (opens its own store connection)."""
        conn = connect(self.config.db_path)
        try:
            incident = dao.get_incident(conn, incident_id)
        finally:
            conn.close()
        if incident is None:
            return
        investigate(
            incident_id,
            incident.signals_ref,
            provider=self.config.make_provider(),
            db_path=self.config.db_path,
            model=self.config.model,
            hint=incident.hint,
            now=incident.received_ts,
        )

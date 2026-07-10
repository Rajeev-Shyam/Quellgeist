"""In-process job queue + worker pool (Wave 7, T7.3; DR-0023 decision 1).

The async ingress stays responsive by handing accepted incidents to a bounded pool of
async workers; each worker runs the **synchronous** ``run_loop`` (via the orchestrator)
in a thread executor, so the event loop is never blocked on model I/O. Concurrency lives
here, never in the frozen loop. The queue is created inside ``start`` (on the running
loop), so building the pool at import time needs no event loop.
"""

from __future__ import annotations

import asyncio
import concurrent.futures

from quellgeist.observability import get_logger
from quellgeist.orchestrator import investigate
from quellgeist.service.config import ServiceConfig
from quellgeist.service.snapshots import discard_snapshot
from quellgeist.store import connect, dao

_log = get_logger("quellgeist.service.worker")


class WorkerPool:
    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        self.queue: asyncio.Queue[str] | None = None
        self._workers: list[asyncio.Task] = []
        # A pool-OWNED executor (not the loop default) so stop() can join in-flight
        # investigation threads — cancelling the awaiting task does not stop its thread.
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None

    async def start(self) -> None:
        self.queue = asyncio.Queue(maxsize=self.config.queue_maxsize)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.config.num_workers, thread_name_prefix="qg-worker"
        )
        self._workers = [
            asyncio.create_task(self._worker(i)) for i in range(self.config.num_workers)
        ]

    async def stop(self, *, drain_timeout: float = 30.0) -> None:
        """Drain in-flight work BEFORE cancelling workers, then JOIN the executor threads.
        Cancelling a task blocked on ``run_in_executor`` does not stop the underlying
        thread (it would keep writing to the store after shutdown — review: orphaned
        executor thread), so: (1) wait, with a bound, for the queue to drain (each item
        calls ``task_done`` when its executor run returns); (2) cancel the now-idle worker
        tasks; (3) ``executor.shutdown(wait=True)`` to block until any thread STILL inside
        ``_process_sync`` (drain-timeout case) finishes, so no store write outlives stop().
        """
        if self.queue is not None:
            try:
                await asyncio.wait_for(self.queue.join(), timeout=drain_timeout)
            except TimeoutError:
                _log.warning("worker_stop_drain_timeout", pending=self.queue.qsize())
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []
        if self._executor is not None:
            # Join any executor thread still inside _process_sync (a cancelled worker task
            # does NOT stop its thread). shutdown(wait=True) blocks, so run it off-loop.
            await asyncio.to_thread(self._executor.shutdown, wait=True)
            self._executor = None

    async def enqueue(self, incident_id: str) -> None:
        """Non-blocking. Raises ``asyncio.QueueFull`` when the bounded queue is full so
        the caller can shed load (503) instead of stalling the request handler on a full
        queue — a blocked ingress would hold the incident 'queued' with no backpressure.
        """
        if self.queue is None:
            raise RuntimeError("worker pool not started")
        self.queue.put_nowait(incident_id)

    async def _worker(self, n: int) -> None:
        queue = self.queue
        if queue is None:  # start() sets it before creating workers; defensive
            return
        while True:
            incident_id = await queue.get()
            try:
                await asyncio.get_running_loop().run_in_executor(
                    self._executor, self._process_sync, incident_id
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
        result = investigate(
            incident_id,
            incident.signals_ref,
            provider=self.config.make_provider(),
            db_path=self.config.db_path,
            model=self.config.model,
            hint=incident.hint,
            now=incident.received_ts,
        )
        # Reap only when the incident is ACTUALLY persisted terminal-'failed'. The
        # in-memory result says 'failed' whenever investigate's body raised, but its
        # failure persistence is best-effort — if the terminal 'failed' write was also
        # swallowed (e.g. DB still locked), the row stays 'running' and startup recovery
        # still needs the snapshot, so re-read the persisted status before deleting it.
        if result.run.outcome == "failed":
            conn = connect(self.config.db_path)
            try:
                final = dao.get_incident(conn, incident_id)
            finally:
                conn.close()
            if final is not None and final.status == "failed":
                discard_snapshot(incident.signals_ref)

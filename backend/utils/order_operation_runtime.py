"""Finite Motor session ownership shared by recoverable order operations."""

import asyncio
from contextlib import asynccontextmanager

from pymongo import timeout as mongo_timeout
from pymongo.errors import PyMongoError


class OperationRuntime:
    def __init__(self, deadline, cleanup_budget, background_work, logger, prefix):
        self.deadline = deadline
        self.cleanup_budget = cleanup_budget
        self.background_work = background_work
        self.logger = logger
        self.prefix = prefix

    @asynccontextmanager
    async def request_deadline(self):
        seconds = self.deadline()
        with mongo_timeout(seconds):
            async with asyncio.timeout(seconds):
                yield

    def observe(self, task):
        self.background_work.discard(task)
        if not task.cancelled():
            task.exception()

    def tracked(self, awaitable):
        task = asyncio.ensure_future(awaitable)
        self.background_work.add(task)
        task.add_done_callback(self.observe)
        return task

    async def bounded_cleanup(self, action):
        seconds = self.cleanup_budget()
        with mongo_timeout(seconds):
            task = self.tracked(action())
        try:
            done, _ = await asyncio.wait({task}, timeout=seconds)
            if not done:
                self.logger.warning("%s_cleanup_incomplete", self.prefix)
                return task
            task.result()
        except (Exception, asyncio.CancelledError):
            self.logger.warning("%s_cleanup_incomplete", self.prefix)
            if not task.done():
                return task
            self.observe(task)
        return None

    @staticmethod
    async def worker_result(worker):
        # Cancelling a waiter does not prove Motor's executor worker has stopped.
        await asyncio.wait({worker})
        return worker.result()

    async def cleanup_session(self, session):
        if session.in_transaction:
            unfinished = await self.bounded_cleanup(session.abort_transaction)
            if unfinished is not None:
                def finish_abort(task):
                    self.observe(task)
                    if not task.cancelled():
                        self.tracked(self.bounded_cleanup(session.end_session))
                unfinished.add_done_callback(finish_abort)
                return
        unfinished = await self.bounded_cleanup(session.end_session)
        if unfinished is not None:
            unfinished.add_done_callback(self.observe)

    async def finish_after_worker(self, worker, session=None):
        try:
            result = await self.worker_result(worker)
        except asyncio.CancelledError:
            return
        except Exception:
            result = None
        if session is not None:
            await self.cleanup_session(session)
        elif result is not None:
            await self.cleanup_session(result)

    async def start_session(self, client):
        worker = self.tracked(client.start_session())
        try:
            return await self.worker_result(worker)
        except BaseException:
            self.tracked(self.finish_after_worker(worker))
            raise

    @staticmethod
    async def commit(session, attempts):
        for attempt in range(attempts):
            try:
                await session.commit_transaction()
                return True
            except PyMongoError as exc:
                if not exc.has_error_label("UnknownTransactionCommitResult"):
                    raise
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.05 * (attempt + 1))
        return False


class SessionLifecycle:
    def __init__(self, runtime, session):
        self.runtime = runtime
        self.session = session
        self.inflight = None

    async def wait(self, awaitable):
        worker = self.inflight = self.runtime.tracked(awaitable)
        try:
            return await self.runtime.worker_result(worker)
        finally:
            if worker.done() and not worker.cancelled():
                self.inflight = None

    async def cleanup(self):
        worker = self.inflight
        if worker is None:
            await self.runtime.cleanup_session(self.session)
        else:
            # Serialize the original worker, abort, then end; never share session.
            self.runtime.tracked(self.runtime.finish_after_worker(worker, self.session))

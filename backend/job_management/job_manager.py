
import asyncio
import uuid
import logging
import time
from typing import Optional, Dict
from .models import JobStatus, TTSRequest, JobInfo
from .job_processor import JobProcessor
from .auto_deletion import AutoDeletionManager, AUDIO_DIR
import os

logger = logging.getLogger(__name__)

class JobManager:
    def __init__(self, max_concurrent: int, webhook_url: str, auto_delete_delay: int = 300):
        self.max_concurrent = max_concurrent
        self.webhook_url = webhook_url
        self.auto_delete_delay = auto_delete_delay
        self.queue = asyncio.PriorityQueue()
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        self.running = False
        self.jobs: Dict[str, JobInfo] = {}
        self.job_priority_threshold = 300

        os.makedirs(AUDIO_DIR, exist_ok=True)

        self.auto_deletion_manager = AutoDeletionManager(
            auto_delete_delay=self.auto_delete_delay,
            webhook_url=self.webhook_url,
            jobs=self.jobs
        )

        self.job_processor = JobProcessor(
            semaphore=self.semaphore,
            jobs=self.jobs,
            webhook_url=self.webhook_url,
            auto_deletion_manager=self.auto_deletion_manager
        )

    async def start(self):
        if not self.running:
            self.running = True
            logger.info(f"Starting job manager with {self.max_concurrent} concurrent jobs")
            asyncio.create_task(self._worker())
            asyncio.create_task(self.auto_deletion_manager.cleanup_old_jobs())

    async def add_job(self, tts_request: TTSRequest) -> str:
        job_id = str(uuid.uuid4())
        job_info = JobInfo(job_id=job_id, request=tts_request)
        self.jobs[job_id] = job_info
        await self.queue.put((100, job_info))
        logger.info(f"Added job {job_id} to queue. Current queue size: {self.queue.qsize()}")
        return job_id

    def get_job_status(self, job_id: str) -> Optional[JobStatus]:
        job = self.jobs.get(job_id)
        return job.status if job else None

    def get_queue_size(self) -> int:
        return self.queue.qsize()

    async def _worker(self):
        logger.info("Worker started")
        while True:
            try:
                _, job_info = await self.queue.get()
                
                if job_info.job_id not in self.jobs:
                    self.queue.task_done()
                    continue
                    
                if job_info.status == JobStatus.QUEUED and job_info.age > self.job_priority_threshold:
                    await self.queue.put((50, job_info))
                    self.queue.task_done()
                    continue

                # Defensive semaphore handling to prevent deadlock
                #
                # PROBLEM: If create_task() fails (rare but possible if event loop is corrupted),
                # the semaphore would be acquired but the task never runs, so job_processor's
                # finally block (which releases the semaphore) never executes → deadlock.
                #
                # SOLUTION: Track whether task creation succeeded. Only release here if we
                # acquired the semaphore but failed to create the task. If task creation
                # succeeds, the task's finally block handles the release (job_processor.py:109).
                #
                # This prevents double-release: we only release in except if task_created=False.
                acquired = False
                task_created = False
                try:
                    await self.semaphore.acquire()
                    acquired = True
                    asyncio.create_task(self.job_processor.process_job(job_info))
                    task_created = True  # Task successfully created, it will handle release
                except Exception as e:
                    logger.error(f"Failed to start job {job_info.job_id}: {e}")

                    # Only release if we acquired semaphore but failed to create task
                    if acquired and not task_created:
                        logger.error(f"Corner case exception of semaphore being acquired but task not created.")
                        self.semaphore.release()
                finally:
                    self.queue.task_done()
            except Exception as e:
                logger.error(f"Error in worker: {e}")
                await asyncio.sleep(1)  # Prevent tight loop on error
    
    async def cleanup_job(self, job_id: str):
        """Manually clean up a job when explicitly deleted by the user"""
        if job_id in self.jobs:
            del self.jobs[job_id]
            logger.info(f"Removed job {job_id} from memory after manual deletion")

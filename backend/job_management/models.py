import enum
import time
import datetime
from typing import Optional
from pydantic import BaseModel
from dataclasses import dataclass
from typing import Optional, Dict
import asyncio

class JobStatus(enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "en-US-AriaNeural"
    pitch: Optional[str] = "0"
    speed: Optional[str] = "1"
    volume: Optional[str] = "100"

class JobResult(BaseModel):
    job_id: str
    status: str
    message: Optional[str] = None
    processing_time: Optional[float] = None
    timestamp: Optional[datetime.datetime] = None

class JobInfo:
    def __init__(self, job_id: str, request: TTSRequest):
        self.job_id = job_id
        self.request = request
        self.status = JobStatus.QUEUED
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.error_message: Optional[str] = None
        self.created_at = time.time()
        self.priority = 100  # Default priority

    def __lt__(self, other):
        # Lower number = higher priority
        if not isinstance(other, JobInfo):
            return NotImplemented
        return self.priority < other.priority

    def __eq__(self, other):
        if not isinstance(other, JobInfo):
            return NotImplemented
        return self.job_id == other.job_id

    @property
    def processing_time(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None
        
    @property
    def age(self) -> float:
        return time.time() - self.created_at

@dataclass
class PrioritizedJob:
    priority: int
    timestamp: float
    job_info: 'JobInfo'

    def __lt__(self, other):
        if not isinstance(other, PrioritizedJob):
            return NotImplemented
        # First compare by priority, then by timestamp
        if self.priority == other.priority:
            return self.timestamp < other.timestamp
        return self.priority < other.priority

class JobManager:
    def __init__(self, max_concurrent: int, webhook_url: str, auto_delete_delay: int = 300):
        self.max_concurrent = max_concurrent
        self.webhook_url = webhook_url
        self.auto_delete_delay = auto_delete_delay
        self.queue = asyncio.PriorityQueue()
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        self.running = False
        self.jobs: Dict[str, JobInfo] = {}
        
    async def add_job(self, tts_request: TTSRequest) -> str:
        job_id = str(uuid.uuid4())
        job_info = JobInfo(job_id=job_id, request=tts_request)
        self.jobs[job_id] = job_info
        
        # Create prioritized job
        pjob = PrioritizedJob(
            priority=100,
            timestamp=time.time(),
            job_info=job_info
        )
        await self.queue.put(pjob)
        return job_id

    async def _worker(self):
        while True:
            try:
                pjob = await self.queue.get()
                job_info = pjob.job_info
                
                if job_info.job_id not in self.jobs:
                    self.queue.task_done()
                    continue
                
                # Check if job needs reprioritization
                if job_info.status == JobStatus.QUEUED and job_info.age > self.job_priority_threshold:
                    new_pjob = PrioritizedJob(
                        priority=50,  # Higher priority
                        timestamp=time.time(),
                        job_info=job_info
                    )
                    await self.queue.put(new_pjob)
                    self.queue.task_done()
                    continue
                
                await self.semaphore.acquire()
                asyncio.create_task(self.job_processor.process_job(job_info))
                self.queue.task_done()
                
            except Exception as e:
                logger.error(f"Error in worker: {e}")
                await asyncio.sleep(1)


import asyncio
import os
import logging
import time
import datetime
from typing import Dict, Optional
from .models import JobStatus, JobInfo
from .webhook_handler import send_webhook
from .models import JobResult

logger = logging.getLogger(__name__)
AUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audio_files")

class AutoDeletionManager:
    def __init__(self, auto_delete_delay: int, webhook_url: str, jobs: Dict[str, JobInfo]):
        self.auto_delete_delay = auto_delete_delay
        self.webhook_url = webhook_url
        self.jobs = jobs
        self.cleanup_interval = 60  # Run cleanup every minute

    async def schedule_auto_delete(self, job_id: str):
        """Schedule automatic deletion of the job and its audio file after the specified delay"""
        try:
            logger.info(f"Scheduling auto-deletion for job {job_id} in {self.auto_delete_delay} seconds")
            await asyncio.sleep(self.auto_delete_delay)
            
            # Check if job is still in memory
            if job_id not in self.jobs:
                logger.info(f"Job {job_id} no longer in memory, skipping auto-delete")
                return
                
            # Delete audio file
            audio_path = os.path.join(AUDIO_DIR, f"{job_id}.mp3")
            if os.path.exists(audio_path):
                os.remove(audio_path)
                logger.info(f"Auto-deleted audio file for job {job_id}")
            else:
                logger.warning(f"Audio file for job {job_id} not found during auto-delete")
            
            # Remove job from memory
            if job_id in self.jobs:
                del self.jobs[job_id]
                logger.info(f"Auto-deleted job {job_id} from memory")
                
            # Send webhook notification about deletion if configured
            result = JobResult(
                job_id=job_id,
                status="deleted",
                message="Job and audio file automatically deleted after timeout",
                timestamp=datetime.datetime.now()
            )
            asyncio.create_task(send_webhook(self.webhook_url, result))
        except Exception as e:
            logger.error(f"Error during auto-deletion of job {job_id}: {e}")

    async def cleanup_old_jobs(self):
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                logger.info("Running scheduled cleanup of old jobs and files")
                
                # Scan audio directory for old files
                current_time = time.time()
                try:
                    files_deleted = 0
                    if os.path.exists(AUDIO_DIR):
                        for filename in os.listdir(AUDIO_DIR):
                            # Remove both .mp3 and .mp3.temp
                            if not (filename.endswith('.mp3') or filename.endswith('.mp3.temp')):
                                continue
                                
                            file_path = os.path.join(AUDIO_DIR, filename)
                            file_age = current_time - os.path.getmtime(file_path)
                            
                            # Files older than auto_delete_delay should be removed
                            if file_age > self.auto_delete_delay:
                                job_id = os.path.splitext(filename)[0]
                                logger.info(f"Cleaning up old audio file: {filename} (age: {file_age:.1f}s)")
                                
                                try:
                                    os.remove(file_path)
                                    files_deleted += 1
                                    # Remove from jobs memory if present
                                    if job_id in self.jobs:
                                        del self.jobs[job_id]
                                    logger.info(f"Deleted old audio file: {filename}")
                                except Exception as e:
                                    logger.error(f"Failed to delete old file {filename}: {e}")
                        
                        if files_deleted > 0:
                            logger.info(f"Cleaned up {files_deleted} old audio files")
                except Exception as e:
                    logger.error(f"Error scanning audio directory: {e}")
                
                # Clean up completed/failed jobs from memory
                jobs_to_remove = [
                    job_id for job_id, job_info in list(self.jobs.items())
                    if (job_info.status in (JobStatus.COMPLETED, JobStatus.FAILED) and 
                       job_info.end_time and 
                       current_time - job_info.end_time > 3600) or  # 1 hour for completed/failed
                       current_time - job_info.created_at > 7200  # 2 hours for any job (safety cleanup)
                ]
                
                for job_id in jobs_to_remove:
                    # Double check if audio file exists and delete it if it does
                    audio_path = os.path.join(AUDIO_DIR, f"{job_id}.mp3")
                    if os.path.exists(audio_path):
                        try:
                            os.remove(audio_path)
                            logger.info(f"Deleted audio for stale job {job_id}")
                        except Exception as e:
                            logger.error(f"Failed to delete audio for stale job {job_id}: {e}")
                    
                    # Remove from memory
                    if job_id in self.jobs:
                        del self.jobs[job_id]
                
                if jobs_to_remove:
                    logger.info(f"Cleaned up {len(jobs_to_remove)} old jobs from memory")
                    
                # Log memory usage stats
                logger.info(f"Current memory usage: {len(self.jobs)} active jobs")
            except Exception as e:
                logger.error(f"Error in job cleanup: {e}")
                await asyncio.sleep(60)  # Prevent tight loop on recurring errors


import os
import asyncio
import time
import logging
import datetime
import traceback
from typing import Dict
from dotenv import load_dotenv
from .models import JobStatus, JobInfo, JobResult
from .tts_processor import process_tts_request, AUDIO_DIR
from .webhook_handler import send_webhook
from .auto_deletion import AutoDeletionManager

# Load .env file before reading environment variables
load_dotenv()

logger = logging.getLogger(__name__)

PROCESS_TIMEOUT = float(os.getenv('PROCESS_TIMEOUT', '600.0'))

class JobProcessor:
    def __init__(self, semaphore: asyncio.Semaphore, jobs: Dict[str, JobInfo], 
                 webhook_url: str, auto_deletion_manager: AutoDeletionManager):
        self.semaphore = semaphore
        self.jobs = jobs
        self.webhook_url = webhook_url
        self.auto_deletion_manager = auto_deletion_manager

    async def process_job(self, job_info: JobInfo):
        job_info.start_time = time.time()
        job_info.status = JobStatus.PROCESSING

        try:
            logger.info(f"Processing job {job_info.job_id} - started")
            logger.info(f"Job {job_info.job_id} parameters: voice={job_info.request.voice}, text_length={len(job_info.request.text)}")
            
            # Process the TTS request with a timeout
            try:
                # Process the TTS request
                await asyncio.wait_for(
                    process_tts_request(
                        job_info.job_id,
                        job_info.request.text,
                        job_info.request.voice,
                        job_info.request.pitch,
                        job_info.request.speed,
                        job_info.request.volume
                    ),
                    timeout=PROCESS_TIMEOUT  # Overall timeout for the entire process
                )
            except asyncio.TimeoutError:
                error_msg = f"TTS processing timed out for job {job_info.job_id} ({PROCESS_TIMEOUT}s timeout exceeded)"
                logger.error(error_msg)
                raise Exception(error_msg)
            except Exception as e:
                error_msg = f"TTS processing error for job {job_info.job_id}: {str(e)}"
                logger.error(f"{error_msg}\n{traceback.format_exc()}")
                raise Exception(error_msg)
            
            job_info.status = JobStatus.COMPLETED
            
            # Send webhook notification immediately when audio is ready
            result = JobResult(
                job_id=job_info.job_id,
                status="completed",
                message="Audio file is ready",
                processing_time=time.time() - job_info.start_time,
                timestamp=datetime.datetime.now()
            )
            
            # Send webhook in a separate task to prevent blocking
            logger.info(f"Job {job_info.job_id} completed successfully. Sending webhook notification.")
            webhook_task = asyncio.create_task(send_webhook(self.webhook_url, result))
            
            # Schedule auto-deletion
            logger.info(f"Scheduling auto-deletion for job {job_info.job_id}")
            deletion_task = asyncio.create_task(self.auto_deletion_manager.schedule_auto_delete(job_info.job_id))
            
            # Wait for webhook to complete (but don't block forever)
            try:
                await asyncio.wait_for(webhook_task, timeout=5.0)
                logger.info(f"Webhook notification sent successfully for job {job_info.job_id}")
            except asyncio.TimeoutError:
                logger.warning(f"Webhook notification timed out for job {job_info.job_id}")
            except Exception as e:
                logger.error(f"Webhook notification failed for job {job_info.job_id}: {str(e)}")
                
        except Exception as e:
            error_message = str(e)
            logger.error(f"Job {job_info.job_id} failed: {error_message}")
            job_info.status = JobStatus.FAILED
            job_info.error_message = error_message
            
            # Send failure notification
            result = JobResult(
                job_id=job_info.job_id,
                status="failed",
                message=error_message,
                timestamp=datetime.datetime.now()
            )
            
            # Send webhook in a separate task
            try:
                await asyncio.wait_for(
                    send_webhook(self.webhook_url, result),
                    timeout=5.0
                )
                logger.info(f"Webhook failure notification sent for job {job_info.job_id}")
            except Exception as webhook_error:
                logger.error(f"Failed to send webhook failure notification for job {job_info.job_id}: {str(webhook_error)}")
        finally:
            job_info.end_time = time.time()
            processing_time = job_info.end_time - job_info.start_time
            logger.info(f"Job {job_info.job_id} processing finished in {processing_time:.2f} seconds with status {job_info.status.value}")
            self.semaphore.release()
            logger.info(f"Released semaphore for job {job_info.job_id}")


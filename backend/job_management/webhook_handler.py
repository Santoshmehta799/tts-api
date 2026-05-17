
import logging
import asyncio
import aiohttp
from .models import JobResult

logger = logging.getLogger(__name__)

async def send_webhook(webhook_url: str, result: JobResult) -> None:
    """
    Send a webhook notification with job result data.
    Implements retry logic with exponential backoff.
    """
    if not webhook_url or webhook_url.strip() == "":
        logger.info(f"No webhook URL configured, skipping notification for job {result.job_id}")
        return
        
    try:
        logger.info(f"Preparing webhook payload for job {result.job_id}")
        
        payload = {
            "job_id": result.job_id,
            "status": result.status,
            "timestamp": result.timestamp.isoformat() if result.timestamp else None
        }
        if result.message:
            payload["message"] = result.message
        if result.processing_time:
            payload["processing_time_seconds"] = result.processing_time
            
        # Retry logic for webhook delivery
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Create a new session for each retry to avoid connection pooling issues
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                    logger.info(f"Sending webhook for job {result.job_id}, attempt {attempt + 1}/{max_retries}")
                    
                    async with session.post(webhook_url, json=payload, timeout=10.0) as resp:
                        response_text = await resp.text()
                        logger.info(f"Webhook response status: {resp.status}, body: {response_text[:100]}...")
                        
                        if resp.status == 200:
                            logger.info(f"Webhook notification sent successfully for job {result.job_id}")
                            break
                        else:
                            logger.warning(f"Webhook attempt {attempt + 1} failed with status {resp.status}: {response_text}")
                            if attempt == max_retries - 1:
                                logger.error(f"All webhook attempts failed for job {result.job_id}")
            except Exception as e:
                logger.error(f"Webhook attempt {attempt + 1} error: {str(e)}")
                if attempt == max_retries - 1:
                    logger.error(f"All webhook attempts failed for job {result.job_id} due to exceptions")
                
            # Exponential backoff with jitter
            backoff_time = 1 * (2 ** attempt) + (0.1 * attempt)
            logger.info(f"Backing off webhook retry for {backoff_time:.2f} seconds")
            await asyncio.sleep(backoff_time)
    except Exception as e:
        logger.error(f"Failed to send webhook for job {result.job_id}: {e}")

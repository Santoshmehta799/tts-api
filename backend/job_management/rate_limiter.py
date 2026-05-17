import asyncio
import time
import logging
from collections import deque

logger = logging.getLogger(__name__)

class RateLimiter:
    """Rate limiter to control requests to Microsoft's TTS service"""

    def __init__(self, max_requests_per_minute=30, min_delay_between_requests=0.5):
        """
        Args:
            max_requests_per_minute: Maximum requests allowed per minute
            min_delay_between_requests: Minimum seconds between consecutive requests
        """
        self.max_requests_per_minute = max_requests_per_minute
        self.min_delay = min_delay_between_requests
        self.request_times = deque(maxlen=max_requests_per_minute)
        self.lock = asyncio.Lock()
        self.last_request_time = 0

        logger.info(f"RateLimiter initialized: {self.max_requests_per_minute} req/min, {self.min_delay}s min delay")

    async def acquire(self):
        """Wait if necessary to respect rate limits"""
        async with self.lock:
            current_time = time.time()

            # Enforce minimum delay between requests
            time_since_last = current_time - self.last_request_time
            logger.info(f"RateLimiter time_since_last: {time_since_last} s")
            if time_since_last < self.min_delay:
                wait_time = self.min_delay - time_since_last
                logger.info(f"Rate limiter: waiting {wait_time:.2f}s (min delay)")
                await asyncio.sleep(wait_time)
                current_time = time.time()

            # Enforce max requests per minute
            if len(self.request_times) >= self.max_requests_per_minute:
                oldest_request = self.request_times[0]
                time_window = current_time - oldest_request
                logger.info(f"RateLimiter time window: {time_window} s")

                if time_window < 60:
                    wait_time = 60 - time_window + 0.1  # Add small buffer
                    logger.warning(f"Rate limiter: hit max {self.max_requests_per_minute} req/min, waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
                    current_time = time.time()

            # Record this request
            self.request_times.append(current_time)
            self.last_request_time = current_time

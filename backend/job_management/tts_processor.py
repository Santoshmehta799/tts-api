import os
import asyncio
import edge_tts
import logging
import traceback
import time
import random
from dotenv import load_dotenv
from .rate_limiter import RateLimiter

# Load .env file before reading environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Retry configuration - Load from environment
MAX_RETRIES = int(os.getenv('TTS_MAX_RETRIES', '3'))
BASE_DELAY = int(os.getenv('TTS_BASE_DELAY', '2'))
MAX_DELAY = int(os.getenv('TTS_MAX_DELAY', '30'))

# Rate limiter configuration - Load from environment
MAX_REQUESTS_PER_MINUTE = int(os.getenv('MAX_REQUESTS_PER_MINUTE', '30'))
MIN_DELAY_BETWEEN_REQUESTS = float(os.getenv('MIN_DELAY_BETWEEN_REQUESTS', '0.5'))

# Create global rate limiter instance
# Controls request velocity to Microsoft's TTS service
rate_limiter = RateLimiter(
    max_requests_per_minute=MAX_REQUESTS_PER_MINUTE,
    min_delay_between_requests=MIN_DELAY_BETWEEN_REQUESTS
)

AUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audio_files")
REQUEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "request_files")
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(REQUEST_DIR, exist_ok=True)

async def write_out_request(job_id: str, text: str, voice: str, pitch: str, speed: str, volume: str) -> None:
    filename = os.path.join(REQUEST_DIR, f"{job_id}.txt")
    with open(filename, "w") as fp:
        fp.write(f"Job ID: {job_id}\n")
        fp.write(f"Voice used: {voice}\n")
        fp.write(f"Text length: {len(text)} characters\n")
        fp.write(f"Text content (first 200 chars): {repr(text[:200])}\n")
        fp.write(f"Text content (last 200 chars): {repr(text[-200:])}\n")
        fp.write(f"Parameters - rate={speed}, pitch={pitch}, volume={volume}\n")
        fp.write(f"Complete text:\n{text}")

async def generate_audio_with_retry(
    job_id: str,
    text: str,
    voice: str,
    rate_value: str,
    volume_value: str,
    pitch_value: str,
    temp_filename: str
) -> None:
    """
    Attempt to generate audio with retry logic and exponential backoff.

    Raises:
        edge_tts.exceptions.NoAudioReceived: If all retry attempts fail
    """
    start_time = time.time()

    # Create initial communicate object
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate_value,
        volume=volume_value,
        pitch=pitch_value
    )

    # Retry logic with exponential backoff
    for attempt in range(MAX_RETRIES):
        try:
            if attempt > 0:
                # Calculate exponential backoff with jitter
                delay = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)
                jitter = random.uniform(0, delay * 0.1)  # Add 10% jitter
                total_delay = delay + jitter
                logger.warning(f"Retry attempt {attempt + 1}/{MAX_RETRIES} for job {job_id} after {total_delay:.2f}s delay")
                await asyncio.sleep(total_delay)

                # Recreate communicate object for retry
                communicate = edge_tts.Communicate(
                    text=text,
                    voice=voice,
                    rate=rate_value,
                    volume=volume_value,
                    pitch=pitch_value
                )

            # Wait for rate limiter before attempting Microsoft API call
            await rate_limiter.acquire()

            # Attempt to generate audio
            await communicate.save(temp_filename)

            # If successful, break out of retry loop
            generation_time = time.time() - start_time
            logger.info(f"TTS generation completed for job {job_id} in {generation_time:.2f} seconds (total attempts: {attempt + 1})")

            return
        except edge_tts.exceptions.NoAudioReceived as e:
            logger.warning(f"NoAudioReceived on attempt {attempt + 1}/{MAX_RETRIES} for job {job_id}")

            # Clean up temp file before retry
            if os.path.exists(temp_filename):
                os.remove(temp_filename)

            # If this was the last attempt, raise with detailed logging
            if attempt == MAX_RETRIES - 1:
                logger.error(f"NoAudioReceived exception for job {job_id} after {MAX_RETRIES} attempts")
                raise e

def format_tts_parameters(pitch: str, speed: str, volume: str) -> tuple[str, str, str]:
    pitch_value = "+0Hz" if pitch == "0" else f"{pitch}Hz"
    if not pitch_value.startswith("+") and not pitch_value.startswith("-"):
        pitch_value = f"+{pitch_value}"
        
    speed_percentage = int((float(speed) - 1) * 100)
    rate_value = f"+{speed_percentage}%" if speed_percentage >= 0 else f"{speed_percentage}%"
    
    volume_percentage = int(float(volume)) - 100
    volume_value = f"+{volume_percentage}%" if volume_percentage >= 0 else f"{volume_percentage}%"

    return pitch_value, rate_value, volume_value
 

async def process_tts_request(job_id: str, text: str, voice: str, pitch: str, speed: str, volume: str) -> None:
    # Format TTS parameters
    pitch_value, rate_value, volume_value = format_tts_parameters(pitch, speed, volume)
   
    # Log the job parameters for debugging
    preview_text = text[:100] + "..." if len(text) > 100 else text
    logger.info(f"Processing TTS job {job_id}: voice={voice}, text length={len(text)}, rate={rate_value}, volume={volume_value}, pitch={pitch_value}, text={preview_text}")
    
    # Write out the request
    # TODO: for now only write out failing request see first exception below
    # await write_out_request(job_id, text, voice, pitch, speed, volume)

    filename = os.path.join(AUDIO_DIR, f"{job_id}.mp3")
    temp_filename = f"{filename}.temp"

    try:
        # Log start of TTS generation
        logger.info(f"Starting TTS generation for job {job_id}")

        # Generate audio with retry logic
        await generate_audio_with_retry(
            job_id=job_id,
            text=text,
            voice=voice,
            rate_value=rate_value,
            volume_value=volume_value,
            pitch_value=pitch_value,
            temp_filename=temp_filename
        )

        # Verify file was created
        if not os.path.exists(temp_filename) or os.path.getsize(temp_filename) == 0:
            error_msg = f"Failed to generate audio file for job {job_id} - file is empty or not created"
            logger.error(error_msg)
            raise Exception(error_msg)

        file_size = os.path.getsize(temp_filename)
        logger.info(f"Generated audio file size for job {job_id}: {file_size} bytes")

        # Calculate average bytes per character
        bytes_per_char = file_size / len(text)
        logger.info(f"Audio file metrics for job {job_id}: {bytes_per_char:.2f} bytes per character")

        # Rename temp file to final file
        os.rename(temp_filename, filename)

        logger.info(f"Job {job_id}: TTS conversion saved to {filename} ({file_size} bytes)")

        # Add a small delay to ensure the file is properly written to disk
        await asyncio.sleep(0.5)

    except edge_tts.exceptions.NoAudioReceived as e:
        # Already logged detailed error in generate_audio_with_retry
        await write_out_request(job_id, text, voice, pitch, speed, volume)

        # Re-raise so job_processor marks job as FAILED
        raise

    except Exception as e:
        # Clean up temp file if it exists
        if os.path.exists(temp_filename):
            os.remove(temp_filename)

        # Log the full stack trace for debugging
        logger.error(f"Error during TTS file save for job {job_id}: {str(e)}\n{traceback.format_exc()}")

        # Re-raise so job_processor marks job as FAILED
        raise
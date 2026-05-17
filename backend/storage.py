
import os
import logging
import datetime
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AUDIO_DIR = "audio_files"  # Directory containing audio files

def load_jobs() -> List[Dict[str, Any]]:
    """
    Load jobs by directly scanning the audio files directory.
    Each audio file represents a completed job.
    """
    # Create audio directory if it doesn't exist
    if not os.path.exists(AUDIO_DIR):
        os.makedirs(AUDIO_DIR, exist_ok=True)
        logger.info(f"Created audio directory: {AUDIO_DIR}")

    try:
        # Get all audio files
        jobs = []
        
        if os.path.exists(AUDIO_DIR):
            for filename in os.listdir(AUDIO_DIR):
                if filename.endswith('.mp3'):
                    job_id = os.path.splitext(filename)[0]
                    file_path = os.path.join(AUDIO_DIR, filename)
                    
                    # Get file modification time as creation timestamp
                    try:
                        mtime = os.path.getmtime(file_path)
                        created_at = datetime.datetime.fromtimestamp(mtime).isoformat()
                    except:
                        created_at = datetime.datetime.now().isoformat()
                    
                    # Add job information
                    jobs.append({
                        "job_id": job_id,
                        "status": "completed",  # All existing files are completed jobs
                        "audio_exists": True,
                        "created_at": created_at,
                        "file_size": os.path.getsize(file_path)
                    })
        
        logger.info(f"Found {len(jobs)} jobs from audio files directory")
        return jobs
    except Exception as e:
        logger.error(f"Error in load_jobs: {e}")
        return []

async def save_jobs_async(jobs: List[Dict[str, Any]]) -> None:
    """
    This function is kept for compatibility but does nothing
    since we now scan the directory directly
    """
    logger.debug("save_jobs_async called but not used in directory-based implementation")
    pass

# Ensure audio directory exists
if not os.path.exists(AUDIO_DIR):
    os.makedirs(AUDIO_DIR, exist_ok=True)

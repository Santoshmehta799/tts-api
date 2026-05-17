import os
import datetime
import asyncio
import traceback
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Response, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
import aiofiles
from models import TTSRequestModel, TTSResponseModel, JobStatusResponse, DetailedErrorResponse
from storage import load_jobs
from job_management import JobManager, JobStatus, TTSRequest
from job_management.tts_processor import AUDIO_DIR

# Load .env file before reading environment variables
load_dotenv()

# Load text length constraints from environment
MAX_TEXT_LENGTH = int(os.getenv('MAX_TEXT_LENGTH', '14000'))
MIN_TEXT_LENGTH = int(os.getenv('MIN_TEXT_LENGTH', '2'))

router = APIRouter()
job_manager = None

def initialize_router(manager: JobManager):
    global job_manager
    job_manager = manager

def validate_tts_text(text: str) -> None:
    """Validate TTS text to prevent common failures"""
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail={"message": "Text cannot be empty"})

    # Check if text contains at least some alphanumeric characters
    if not any(c.isalnum() for c in text):
        raise HTTPException(
            status_code=400,
            detail={"message": "Text must contain alphanumeric characters (not just punctuation like '...' or '!!!')"}
        )

    # Check for minimum text length
    if len(text.strip()) < MIN_TEXT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Text too short (minimum {MIN_TEXT_LENGTH} characters)"}
        )

    # Check for maximum text length
    if len(text.strip()) > MAX_TEXT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Text too long (maximum {MAX_TEXT_LENGTH} characters)"}
        )

@router.get("/tts/jobs")
async def get_all_jobs():
    """Get all jobs by scanning the audio directory"""
    try:
        # Get completed jobs from audio files
        completed_jobs = load_jobs()
        
        # Get active jobs from job manager
        active_jobs = []
        if job_manager:
            for job_id, job_info in job_manager.jobs.items():
                # Skip if this job already has an audio file (would be in completed_jobs)
                audio_path = os.path.join(AUDIO_DIR, f"{job_id}.mp3")
                if os.path.exists(audio_path):
                    continue
                    
                active_job = {
                    "job_id": job_id,
                    "status": job_info.status.value,
                    "created_at": datetime.datetime.fromtimestamp(job_info.created_at).isoformat(),
                    "audio_exists": False,
                    "text": job_info.request.text[:100] + "..." if len(job_info.request.text) > 100 else job_info.request.text
                }
                active_jobs.append(active_job)
        
        # Combine and sort all jobs by creation time (newest first)
        all_jobs = completed_jobs + active_jobs
        all_jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        # Limit to most recent jobs
        return all_jobs[:50]  # Return only the 50 most recent jobs
    except Exception as e:
        error_detail = f"Error getting jobs: {str(e)}\n{traceback.format_exc()}"
        print(error_detail)  # Console log for server-side debugging
        raise HTTPException(status_code=500, detail={"message": str(e), "traceback": traceback.format_exc()})

@router.post("/tts", response_model=TTSResponseModel)
async def tts_endpoint(request: TTSRequestModel, req: Request):
    try:
        # Validate text before processing
        validate_tts_text(request.text)

        # Log client information for debugging
        client_host = req.client.host if req.client else "unknown"
        user_agent = req.headers.get("user-agent", "unknown")
        content_length = len(request.text)
        
        print(f"TTS request from {client_host} with User-Agent: {user_agent}, content length: {content_length}")
        
        # Ensure we have capacity for this job
        if job_manager.get_queue_size() > job_manager.max_concurrent * 2:
            raise HTTPException(
                status_code=503, 
                detail={"message": "Server is currently at capacity. Please try again later.", 
                        "queue_size": job_manager.get_queue_size()}
            )
        
        job_id = await job_manager.add_job(
            TTSRequest(
                text=request.text.strip(),
                voice=request.voice,
                pitch=request.pitch,
                speed=request.speed,
                volume=request.volume,
            )
        )
        
        return TTSResponseModel(job_id=job_id)
    except HTTPException as he:
        # Re-raise HTTP exceptions
        raise he
    except Exception as e:
        # Log the exception with detailed traceback
        error_detail = f"Error in /tts endpoint: {str(e)}\n{traceback.format_exc()}"
        print(error_detail)
        raise HTTPException(
            status_code=500, 
            detail={"message": f"Internal server error: {str(e)}", "traceback": traceback.format_exc()}
        )

@router.get("/tts/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """Check the status of a TTS job"""
    try:
        # First check if the audio file already exists
        audio_path = os.path.join(AUDIO_DIR, f"{job_id}.mp3")
        if os.path.exists(audio_path):
            return JobStatusResponse(job_id=job_id, status="completed", message="Audio is ready")
        
        # If not, check the job in memory
        status = job_manager.get_job_status(job_id)
        if status is None:
            raise HTTPException(
                status_code=404, 
                detail={"message": f"Job {job_id} not found", "job_id": job_id}
            )
            
        return JobStatusResponse(
            job_id=job_id,
            status=status.value,
            message="Audio is being processed" if status == JobStatus.PROCESSING else "Audio is ready"
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        error_detail = f"Error checking job status: {str(e)}\n{traceback.format_exc()}"
        print(error_detail)
        raise HTTPException(
            status_code=500, 
            detail={"message": f"Error checking job status: {str(e)}", "traceback": traceback.format_exc()}
        )

@router.get("/tts/audio/{job_id}")
async def get_audio(job_id: str):
    """Serve the generated audio file with caching headers"""
    audio_path = os.path.join(AUDIO_DIR, f"{job_id}.mp3")
    
    if not os.path.exists(audio_path):
        raise HTTPException(
            status_code=404, 
            detail={"message": f"Audio for job {job_id} not found or not ready yet", "job_id": job_id}
        )
    
    try:
        # Get file size for Content-Length header
        file_size = os.path.getsize(audio_path)
        
        if file_size < 100:
            raise HTTPException(
                status_code=422, 
                detail={"message": f"Audio file appears to be incomplete for job {job_id}", "job_id": job_id}
            )
        
        async def iterfile():
            async with aiofiles.open(audio_path, 'rb') as f:
                chunk_size = 1024 * 1024  # 1MB chunks
                while chunk := await f.read(chunk_size):
                    yield chunk
        
        return StreamingResponse(
            iterfile(),
            media_type="audio/mpeg",
            headers={
                "Content-Length": str(file_size),
                "Cache-Control": "public, max-age=86400",
                "ETag": f'"{hash(job_id)}"'
            }
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        error_detail = f"Error reading audio file: {str(e)}\n{traceback.format_exc()}"
        print(error_detail)
        raise HTTPException(
            status_code=500, 
            detail={"message": f"Error reading audio file: {str(e)}", "traceback": traceback.format_exc()}
        )

@router.delete("/tts/audio/{job_id}")
async def delete_audio(job_id: str, background_tasks: BackgroundTasks):
    """Delete the generated audio file"""
    audio_path = os.path.join(AUDIO_DIR, f"{job_id}.mp3")
    
    if not os.path.exists(audio_path):
        raise HTTPException(
            status_code=404, 
            detail={"message": f"Audio for job {job_id} not found", "job_id": job_id}
        )
    
    try:
        os.remove(audio_path)
        
        # Also clean up from job manager if it exists there
        if job_id in job_manager.jobs:
            background_tasks.add_task(job_manager.cleanup_job, job_id)
        
        return {"message": f"Audio for job {job_id} deleted successfully"}
    except Exception as e:
        error_detail = f"Failed to delete audio: {str(e)}\n{traceback.format_exc()}"
        print(error_detail)
        raise HTTPException(
            status_code=500, 
            detail={"message": f"Failed to delete audio: {str(e)}", "traceback": traceback.format_exc()}
        )

@router.get("/health")
async def health_check():
    """Health check endpoint for load balancers with system statistics"""
    try:
        # Scan audio directory
        audio_files_count = 0
        if os.path.exists(AUDIO_DIR):
            audio_files = [f for f in os.listdir(AUDIO_DIR) if f.endswith('.mp3')]
            audio_files_count = len(audio_files)

        # Get active jobs in the queue
        active_jobs_size = job_manager.get_queue_size() if job_manager else 0
        memory_jobs_count = len(job_manager.jobs) if job_manager else 0

        return {
            "status": "healthy",
            "audio_files_count": audio_files_count,
            "active_jobs_size": active_jobs_size,
            "memory_jobs_count": memory_jobs_count,
            "message": "System is operational"
        }
    except Exception as e:
        error_detail = f"Health check error: {str(e)}\n{traceback.format_exc()}"
        print(error_detail)
        return {
            "status": "unhealthy",
            "audio_files_count": 0,
            "active_jobs_size": 0,
            "memory_jobs_count": 0,
            "message": f"Error: {str(e)}",
            "traceback": traceback.format_exc()
        }

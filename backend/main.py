
import os
# ... your existing imports ...
from fastapi import FastAPI, Security, HTTPException, Depends
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from job_management import JobManager
from routes import router, initialize_router
from urllib.parse import urlparse
import asyncio

load_dotenv()

# Configuration from environment variables
MAX_CONCURRENT_REQUESTS = int(os.getenv('MAX_CONCURRENT_REQUESTS', '50'))
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
API_KEY = os.getenv('API_KEY')
AUTO_DELETE_DELAY = int(os.getenv('AUTO_DELETE_DELAY', '300'))

if not API_KEY:
    raise ValueError("API_KEY must be set in environment variables")

# API Key security
api_key_header = APIKeyHeader(name="api-key", auto_error=True)

async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key_header

# Validate WEBHOOK_URL
if WEBHOOK_URL:
    parsed_url = urlparse(WEBHOOK_URL)
    if not all([parsed_url.scheme, parsed_url.netloc]):
        print(f"Warning: Invalid WEBHOOK_URL format: {WEBHOOK_URL}")

# Initialize FastAPI
app = FastAPI(
    title="TTS API", 
    description="High-performance Text-to-Speech API",
    version="1.0.0",
    dependencies=[Depends(get_api_key)]
)

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "https://vocal-craft-orchestrator.vercel.app",
        "https://speechma.com",
        "http://speechma.com",
        "https://www.speechma.com",
        "http://www.speechma.com",
        "http://lightgray-ibis-796203.hostingersite.com",
        "https://lightgray-ibis-796203.hostingersite.com",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=86400
)

# Initialize JobManager (do NOT call async code here)
job_manager = JobManager(
    max_concurrent=MAX_CONCURRENT_REQUESTS,
    webhook_url=WEBHOOK_URL,
    auto_delete_delay=AUTO_DELETE_DELAY
)

# Hook into FastAPI startup
@app.on_event("startup")
async def start_job_manager():
    asyncio.create_task(job_manager.start())  # Start the async job manager safely

# Setup routes
initialize_router(job_manager)
app.include_router(router)

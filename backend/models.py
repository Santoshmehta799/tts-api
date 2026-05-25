
from pydantic import BaseModel, validator
import os
from dotenv import load_dotenv

# Load .env file before reading environment variables
load_dotenv()

MAX_TEXT_LENGTH = int(os.getenv('MAX_TEXT_LENGTH', '50000'))

class TTSRequestModel(BaseModel):
    text: str
    voice: str = "en-US-AriaNeural"
    pitch: str = "0"
    speed: str = "1"
    volume: str = "100"
    
    @validator('text')
    def validate_text_length(cls, v):
        if len(v) > MAX_TEXT_LENGTH:
            raise ValueError(f"Text exceeds maximum length of {MAX_TEXT_LENGTH} characters")
        if len(v.strip()) == 0:
            raise ValueError("Text cannot be empty")
        return v

class TTSResponseModel(BaseModel):
    job_id: str

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    message: str = ""

class DetailedErrorResponse(BaseModel):
    message: str
    traceback: str = None
    job_id: str = None


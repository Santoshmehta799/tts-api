import os
from fastapi import FastAPI, UploadFile, File, Form, Security, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.security.api_key import APIKeyHeader
from LavaSR.model import LavaEnhance2
import soundfile as sf
import uuid

# Local .env support (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# API Key
API_KEY = os.getenv("API_KEY")

if not API_KEY:
    raise ValueError("API_KEY must be set in environment variables")

# API Key Security
api_key_header = APIKeyHeader(
    name="api-key",
    auto_error=True,
    scheme_name="API Key"
)

async def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key

app = FastAPI(
    title="LavaSR API",
    version="1.0.0",
    dependencies=[Depends(get_api_key)]
)

print("Loading LavaSR model...")
model = LavaEnhance2("YatharthS/LavaSR", "cpu")
print("Model loaded!")

@app.post("/enhance-audio")
async def enhance_audio(
    file: UploadFile = File(...),
    denoise: bool = Form(False),
    batch: bool = Form(False),
    input_sr: int = Form(16000)
):
    uid = str(uuid.uuid4())

    input_file = f"input_{uid}.wav"
    output_file = f"output_{uid}.wav"

    with open(input_file, "wb") as f:
        f.write(await file.read())

    input_audio, _ = model.load_audio(
        input_file,
        input_sr=input_sr
    )

    output_audio = model.enhance(
        input_audio,
        denoise=denoise,
        batch=batch
    ).cpu().numpy().squeeze()

    sf.write(output_file, output_audio, 48000)

    return FileResponse(
        output_file,
        media_type="audio/wav",
        filename="enhanced.wav"
    )
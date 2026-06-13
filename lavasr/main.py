from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse
from LavaSR.model import LavaEnhance2
import soundfile as sf
import uuid

app = FastAPI(
    title="LavaSR API",
    version="1.0.0"
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
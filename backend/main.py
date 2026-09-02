import os
import json
import logging
from fastapi import FastAPI, UploadFile, Form, File, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("safesnap")

# Optional .env support
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = FastAPI(title="SafeSnap Triage API")

# Payload size limit middleware (2MB)
class LimitUploadSize(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 2 * 1024 * 1024:
            return Response(
                content=json.dumps({"detail": "Payload too large. Maximum size is 2MB."}),
                status_code=413,
                media_type="application/json",
            )
        return await call_next(request)

app.add_middleware(LimitUploadSize)

# CORS Middleware
allowed_origin = os.environ.get("ALLOWED_CORS_ORIGIN", "*")
origins = [o.strip() for o in allowed_origin.split(",") if o.strip()]
if not origins:
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True if origins != ["*"] else False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

system_instruction = """
You are a triage assistant for minor campus emergencies.
Your goal is to identify physical hazards or situations from the provided image or text and provide standard triage steps.
DO NOT provide medical advice or medical diagnosis. Stick to general physical triage and safety.
Respond ONLY with a JSON object in the following format:
{
  "hazard_identified": "string",
  "severity_level": "Low | Medium | High",
  "immediate_steps": ["string", "string", "string"]
}
Provide exactly 3 immediate steps.
"""

model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=system_instruction)

def validate_image_bytes(data: bytes) -> bool:
    """Validates common image magic headers (JPEG, PNG, GIF, WebP)."""
    if len(data) < 4:
        return False
    # JPEG
    if data[:2] == b"\xff\xd8":
        return True
    # PNG
    if data[:4] == b"\x89PNG":
        return True
    # GIF
    if data[:4] in (b"GIF8", b"GIF7"):
        return True
    # WebP
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return True
    return False

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.post("/api/analyze")
async def analyze(
    image: UploadFile = File(None),
    text: str = Form(None)
):
    contents = []

    # Validate image input if provided
    if image and image.filename:
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Invalid file type. Must be an image.")
        img_bytes = await image.read()
        if len(img_bytes) == 0:
            raise HTTPException(status_code=400, detail="Provided image file is empty.")
        if len(img_bytes) > 2 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Payload too large. Maximum size is 2MB.")
        if not validate_image_bytes(img_bytes):
            raise HTTPException(status_code=400, detail="Corrupted or unrecognized image format.")
        contents.append({"mime_type": image.content_type, "data": img_bytes})

    # Validate quick-text input if provided
    if text and text.strip():
        raw_text = text.strip()
        if len(raw_text) > 1000:
            raise HTTPException(status_code=400, detail="Text input exceeds maximum length of 1000 characters.")
        contents.append(raw_text)

    if not contents:
        raise HTTPException(status_code=400, detail="Must provide either an image or text input.")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY environment variable is missing.")
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY environment variable is not configured on the server."
        )

    try:
        genai.configure(api_key=api_key)
        response = model.generate_content(
            contents,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
            ),
        )
        data = json.loads(response.text)

        hazard = str(data.get("hazard_identified", "Unspecified Hazard"))
        severity = str(data.get("severity_level", "Medium")).strip().capitalize()
        if severity not in ["Low", "Medium", "High"]:
            severity = "Medium"

        steps = data.get("immediate_steps", [])
        if not isinstance(steps, list):
            steps = [str(steps)]
        steps = [str(s).strip() for s in steps if str(s).strip()]
        if len(steps) < 3:
            defaults = [
                "Move to a safe location away from immediate hazards.",
                "Notify campus safety or nearby staff for assistance.",
                "Monitor condition and seek emergency medical care if symptoms escalate."
            ]
            steps.extend(defaults[len(steps):3])
        elif len(steps) > 3:
            steps = steps[:3]

        return {
            "hazard_identified": hazard,
            "severity_level": severity,
            "immediate_steps": steps
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Gemini API triage call failed.")
        # Redact any accidental credential pattern in exception message
        import re
        sanitized_msg = re.sub(r"AIza[0-9A-Za-z-_]{35}", "[REDACTED_API_KEY]", str(e))
        raise HTTPException(status_code=500, detail=f"AI analysis failed: {sanitized_msg}")

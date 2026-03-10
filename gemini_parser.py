import json
import logging
import os
import tempfile
from datetime import date
from google import genai
from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)

client = genai.Client(api_key=GEMINI_API_KEY, http_options={"timeout": 300000})

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
SUPPORTED_FILE_TYPES = {"application/pdf"}


def extract_events(file_bytes: bytes, mime_type: str) -> list:
    today = date.today().isoformat()

    prompt = f"""
    Look at this schedule and extract every event, class, or meeting you can find.

    Return a JSON array only — no extra text, no markdown, no backticks.

    Today's date is {today}. Use this to determine the correct year and upcoming dates.
    If no year is visible, use the current year from today's date.
    If no end time is visible, add 1 hour to the start time.

    Each item must have these fields:
    - title: the class or event name only, strip out any room numbers, instructor names, or TA names from the title
    - date: YYYY-MM-DD
    - start_time: HH:MM (24hr)
    - end_time: HH:MM (24hr)
    - description: instructor name and TA name if present, otherwise empty string
    - location: the room number or room code. This may appear as a separate column next to the event
      (e.g. "1.16", "3.01", "1.12") OR it may be written inside the event cell itself. Extract it either way.
      If no room is visible, use empty string.

    Example where room is a separate column:
    [{{"title":"Signal and System Theory Lec","date":"2026-03-12","start_time":"09:00","end_time":"10:00","description":"Prof. Mohamed Ashour / TA: Dina Sherif","location":"1.16"}}]

    Example where room is inside the event name:
    [{{"title":"Computer Programming Lab","date":"2026-03-14","start_time":"09:00","end_time":"10:00","description":"Dr. Ahmed Hussein / TA: Menrit Hanna","location":"1.16"}}]
    """

    if mime_type not in SUPPORTED_IMAGE_TYPES and mime_type not in SUPPORTED_FILE_TYPES:
        raise ValueError(f"Unsupported file type: {mime_type}")

    try:
        if mime_type == "application/pdf":
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(file_bytes)
                    tmp_path = tmp.name

                logger.info(f"Uploading PDF ({len(file_bytes)} bytes)...")
                uploaded = client.files.upload(
                    file=tmp_path, config={"mime_type": "application/pdf"}
                )
                logger.info(f"Upload done: {uploaded.name}, waiting for processing...")

                # wait for the file to be ready
                import time

                while uploaded.state.name == "PROCESSING":
                    time.sleep(2)
                    uploaded = client.files.get(name=uploaded.name)

                if uploaded.state.name == "FAILED":
                    raise ValueError("File processing failed on Gemini's side")

                logger.info("File ready, sending to model...")
                contents = [uploaded, prompt]

            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        else:
            contents = [
                {
                    "parts": [
                        {"inline_data": {"mime_type": mime_type, "data": file_bytes}},
                        {"text": prompt},
                    ]
                }
            ]

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=contents,
        )

    except Exception as e:
        logger.error(f"Gemini API call failed: {type(e).__name__}: {e}")
        raise

    raw = response.text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    return json.loads(raw)

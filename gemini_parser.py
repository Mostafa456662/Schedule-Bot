import json
import logging
import google.generativeai as genai
from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")


def extract_events(image_bytes: bytes) -> list:
    prompt = """
    Look at this schedule image and extract every event, class, or meeting you can find.

    Return a JSON array only — no extra text, no markdown, no backticks.

    Each item must have these fields:
    - title: name of the event
    - date: YYYY-MM-DD
    - start_time: HH:MM (24hr)
    - end_time: HH:MM (24hr)
    - description: any extra detail, or empty string

    If no year is visible, use the current year.
    If no end time is visible, add 1 hour to the start time.

    Example:
    [{"title":"Math","date":"2026-03-10","start_time":"09:00","end_time":"10:00","description":"Room 204"}]
    """

    response = model.generate_content(
        [{"mime_type": "image/jpeg", "data": image_bytes}, prompt]
    )

    # strip markdown fences if the model adds them anyway
    raw = response.text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    return json.loads(raw)
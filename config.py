import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SCOPES = ["https://www.googleapis.com/auth/calendar"]
TIMEZONE = "Europe/Berlin"
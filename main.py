import os
import json
import logging
from dotenv import load_dotenv
import google.generativeai as genai
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────────────────
load_dotenv()
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# ─── Gemini Setup ──────────────────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

# ─── User State (tracks who is in "delete mode") ──────────────────────────────
user_states = {}  # { chat_id: "delete" }


# ─── Google Calendar Auth ──────────────────────────────────────────────────────
def get_calendar_service():
    creds = None

    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build("calendar", "v3", credentials=creds)


# ─── Add Events to Google Calendar ────────────────────────────────────────────
def add_events_to_calendar(events: list) -> tuple[int, list]:
    service = get_calendar_service()
    added = 0
    failed = []

    for event in events:
        try:
            calendar_event = {
                "summary": event.get("title", "Untitled Event"),
                "description": event.get("description", ""),
                "start": {
                    "dateTime": f"{event['date']}T{event['start_time']}:00",
                    "timeZone": "Europe/Berlin",
                },
                "end": {
                    "dateTime": f"{event['date']}T{event['end_time']}:00",
                    "timeZone": "Europe/Berlin",
                },
            }

            service.events().insert(calendarId="primary", body=calendar_event).execute()
            added += 1
            logger.info(f"Added event: {event.get('title')}")

        except Exception as e:
            logger.error(f"Failed to add event {event.get('title')}: {e}")
            failed.append(event.get("title", "Untitled"))

    return added, failed


# ─── Delete Events from Google Calendar ───────────────────────────────────────
def delete_events_from_calendar(events: list) -> tuple[int, int]:
    """
    For each event extracted from the image, search Google Calendar
    by title + date and delete any matches found.
    Returns (deleted_count, not_found_count)
    """
    service = get_calendar_service()
    deleted = 0
    not_found = 0

    for event in events:
        try:
            date = event["date"]
            time_min = f"{date}T00:00:00+02:00"  # Africa/Cairo is UTC+2
            time_max = f"{date}T23:59:59+02:00"

            results = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=time_min,
                    timeMax=time_max,
                    q=event.get("title", ""),
                    singleEvents=True,
                )
                .execute()
            )

            calendar_events = results.get("items", [])

            if not calendar_events:
                logger.warning(f"No match found for: {event.get('title')} on {date}")
                not_found += 1
                continue

            for cal_event in calendar_events:
                service.events().delete(
                    calendarId="primary", eventId=cal_event["id"]
                ).execute()
                logger.info(f"Deleted event: {cal_event.get('summary')} on {date}")
                deleted += 1

        except Exception as e:
            logger.error(f"Failed to delete event {event.get('title')}: {e}")
            not_found += 1

    return deleted, not_found


# ─── Extract Events from Image via Gemini ─────────────────────────────────────
def extract_events_from_image(image_bytes: bytes) -> list:
    prompt = """
    You are a schedule parser. Look at this schedule image and extract ALL events/classes/meetings.
    
    Return ONLY a valid JSON array with no extra text, no markdown, no backticks.
    
    Each object in the array must have exactly these fields:
    - title: (string) name of the event
    - date: (string) in YYYY-MM-DD format
    - start_time: (string) in HH:MM format (24hr)
    - end_time: (string) in HH:MM format (24hr)
    - description: (string) any extra details, or empty string if none
    
    If the year is not shown, assume the current year.
    If an end time is not shown, assume 1 hour after start time.
    
    Example output:
    [{"title":"Math Class","date":"2025-03-10","start_time":"09:00","end_time":"10:00","description":"Room 204"}]
    """

    response = model.generate_content(
        [{"mime_type": "image/jpeg", "data": image_bytes}, prompt]
    )

    raw = response.text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    return json.loads(raw)


# ─── Telegram Handlers ─────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello! Here's what I can do:\n\n"
        "📅 *Add events:* Just send me a photo of your schedule\n"
        "🗑️ *Delete events:* Type /delete then send a photo\n",
        parse_mode="Markdown",
    )


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_states[chat_id] = "delete"
    await update.message.reply_text(
        "🗑️ Delete mode on! Now send me the schedule photo and I'll remove those events from your calendar."
    )


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    mode = user_states.pop(chat_id, "add")  # Default is add, clears state after use

    if update.message.photo:
        file_ref = update.message.photo[-1]
        file = await context.bot.get_file(file_ref.file_id)
    elif update.message.document and update.message.document.mime_type.startswith(
        "image/"
    ):
        file = await context.bot.get_file(update.message.document.file_id)
    else:
        await update.message.reply_text("Please send an image of your schedule.")
        return

    await update.message.reply_text("📸 Got your schedule! Analyzing it with Gemini...")

    image_bytes = bytes(await file.download_as_bytearray())

    try:
        events = extract_events_from_image(image_bytes)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        await update.message.reply_text(
            "❌ Couldn't read the schedule properly. Try sending a clearer image."
        )
        return
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        await update.message.reply_text(
            "❌ Something went wrong while analyzing the image."
        )
        return

    if not events:
        await update.message.reply_text(
            "🤔 No events found in this image. Try a clearer photo."
        )
        return

    event_list = "\n".join(
        [
            f"• {e['title']} — {e['date']} {e['start_time']}–{e['end_time']}"
            for e in events
        ]
    )

    if mode == "delete":
        await update.message.reply_text(
            f"🗑️ Found {len(events)} events to delete:\n\n{event_list}\n\nRemoving from Google Calendar..."
        )
        try:
            deleted, not_found = delete_events_from_calendar(events)
        except Exception as e:
            logger.error(f"Calendar delete error: {e}")
            await update.message.reply_text(
                "❌ Failed to connect to Google Calendar. Check your credentials."
            )
            return

        msg = f"✅ Successfully deleted {deleted}/{len(events)} events from your Google Calendar!"
        if not_found:
            msg += f"\n\n⚠️ {not_found} event(s) were not found in your calendar (may have already been deleted)."
        await update.message.reply_text(msg)

    else:
        await update.message.reply_text(
            f"📋 Found {len(events)} events:\n\n{event_list}\n\nAdding to Google Calendar..."
        )
        try:
            added, failed = add_events_to_calendar(events)
        except Exception as e:
            logger.error(f"Calendar error: {e}")
            await update.message.reply_text(
                "❌ Failed to connect to Google Calendar. Check your credentials."
            )
            return

        msg = f"✅ Successfully added {added}/{len(events)} events to your Google Calendar!"
        if failed:
            msg += f"\n\n⚠️ Failed to add: {', '.join(failed)}"
        await update.message.reply_text(msg)


async def handle_non_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Please send a photo of your schedule and I'll handle the rest!\n"
        "Use /delete first if you want to remove events instead of adding them."
    )


# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    logger.info("Authenticating with Google Calendar...")
    get_calendar_service()
    logger.info("Google Calendar authenticated!")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_image)
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_non_image))

    logger.info("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()

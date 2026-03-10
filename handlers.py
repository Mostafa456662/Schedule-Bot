import logging
import json
from telegram import Update
from telegram.ext import ContextTypes
from gemini_parser import extract_events
from calendar_service import add_events, delete_events

logger = logging.getLogger(__name__)

user_states: dict[int, str] = {}


def chunk_message(text: str, max_length: int = 4000) -> list[str]:
    lines = text.split("\n")
    chunks = []
    current = ""

    for line in lines:
        if len(current) + len(line) + 1 > max_length:
            chunks.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line

    if current:
        chunks.append(current)

    return chunks


async def send_long_message(update: Update, text: str):
    for chunk in chunk_message(text):
        await update.message.reply_text(chunk)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me a photo of your schedule and I'll add the events to Google Calendar.\n"
        "Use /delete before sending a photo if you want to remove events instead."
    )


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_states[update.message.chat_id] = "delete"
    await update.message.reply_text(
        "Delete mode on. Send me the schedule photo and I'll remove those events from your calendar."
    )


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    mode = user_states.pop(chat_id, "add")
    mime_type = "image/jpeg"

    if update.message.photo:
        file = await context.bot.get_file(update.message.photo[-1].file_id)

    elif update.message.document:
        doc = update.message.document
        mime_type = doc.mime_type or "image/jpeg"

        supported = {
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/heic",
            "application/pdf",
        }
        if mime_type not in supported:
            await update.message.reply_text(
                "Unsupported file type. Send an image (JPEG, PNG, WEBP) or a PDF."
            )
            return

        file = await context.bot.get_file(doc.file_id)

    else:
        await update.message.reply_text("Send an image or PDF of your schedule.")
        return

    await update.message.reply_text("Got it, analyzing the schedule...")

    file_bytes = bytes(await file.download_as_bytearray())

    try:
        events = extract_events(file_bytes, mime_type)
    except json.JSONDecodeError:
        await update.message.reply_text(
            "Couldn't parse the schedule. Try a clearer file."
        )
        return
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        await update.message.reply_text("Something went wrong while reading the file.")
        return

    if not events:
        await update.message.reply_text("No events found. Try a clearer photo.")
        return

    event_list = "\n".join(
        f"- {e['title']} | {e['date']} {e['start_time']}-{e['end_time']}"
        for e in events
    )

    if mode == "delete":
        await send_long_message(
            update, f"Found {len(events)} events to delete:\n\n{event_list}"
        )
        await update.message.reply_text("Removing them now...")

        try:
            deleted, not_found = delete_events(events)
        except Exception as e:
            logger.error(f"Delete error: {e}")
            await update.message.reply_text("Failed to connect to Google Calendar.")
            return

        msg = f"Deleted {deleted}/{len(events)} events."
        if not_found:
            msg += f"\n{not_found} event(s) were not found and may have already been removed."
        await update.message.reply_text(msg)

    else:
        await send_long_message(update, f"Found {len(events)} events:\n\n{event_list}")
        await update.message.reply_text("Adding them now...")

        try:
            added, skipped, failed = add_events(events)
        except Exception as e:
            logger.error(f"Add error: {e}")
            await update.message.reply_text("Failed to connect to Google Calendar.")
            return

        msg = f"Added {added}/{len(events)} events to your calendar."
        if skipped:
            msg += f"\n{skipped} event(s) skipped as something already exists in that time slot."
        if failed:
            msg += f"\nFailed to add: {', '.join(failed)}"
        await update.message.reply_text(msg)


async def handle_non_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send a photo of your schedule.\n"
        "Use /delete first if you want to remove events."
    )

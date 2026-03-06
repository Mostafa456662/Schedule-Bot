import logging
import json
from telegram import Update
from telegram.ext import ContextTypes
from gemini_parser import extract_events
from calendar_service import add_events, delete_events

logger = logging.getLogger(__name__)

# tracks which users are in delete mode
user_states: dict[int, str] = {}


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

    if update.message.photo:
        file = await context.bot.get_file(update.message.photo[-1].file_id)
    elif update.message.document and update.message.document.mime_type.startswith(
        "image/"
    ):
        file = await context.bot.get_file(update.message.document.file_id)
    else:
        await update.message.reply_text("Send an image of your schedule.")
        return

    await update.message.reply_text("Got it, analyzing the schedule...")

    image_bytes = bytes(await file.download_as_bytearray())

    try:
        events = extract_events(image_bytes)
    except json.JSONDecodeError:
        await update.message.reply_text(
            "Couldn't parse the schedule. Try a clearer image."
        )
        return
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        await update.message.reply_text("Something went wrong while reading the image.")
        return

    if not events:
        await update.message.reply_text("No events found. Try a clearer photo.")
        return

    event_list = "\n".join(
        f"- {e['title']} | {e['date']} {e['start_time']}-{e['end_time']}"
        for e in events
    )

    if mode == "delete":
        await update.message.reply_text(
            f"Found {len(events)} events to delete:\n\n{event_list}\n\nRemoving them now..."
        )
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
        await update.message.reply_text(
            f"Found {len(events)} events:\n\n{event_list}\n\nAdding them now..."
        )
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

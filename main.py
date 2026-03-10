import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from config import TELEGRAM_BOT_TOKEN
from calendar_service import get_calendar_service
from handlers import start, delete_command, handle_image, handle_non_image

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)


def main():
    # run OAuth flow on startup so it doesn't interrupt a message later
    get_calendar_service()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.Document.IMAGE | filters.Document.PDF, handle_image
        )
    )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_non_image))

    app.run_polling()


if __name__ == "__main__":
    main()

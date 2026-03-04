# Telegram Schedule Bot

A Telegram bot that reads a photo of a schedule and automatically adds or removes the events from Google Calendar using the Gemini vision API.

## How it works

1. You send a photo of a schedule to the bot
2. Gemini reads the image and extracts all events
3. The bot adds them to your Google Calendar

To remove events, type `/delete` before sending the photo.

## Setup

### Requirements

- Python 3.10+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Google Gemini API key from [Google AI Studio](https://aistudio.google.com)
- A Google Cloud project with the Calendar API enabled

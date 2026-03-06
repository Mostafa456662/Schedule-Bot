import os
import pickle
import logging
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from config import SCOPES, TIMEZONE

logger = logging.getLogger(__name__)


def get_calendar_service():
    creds = None

    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        with open("token.pickle", "wb") as f:
            pickle.dump(creds, f)

    return build("calendar", "v3", credentials=creds)


def add_events(events: list) -> tuple[int, list]:
    service = get_calendar_service()
    added = 0
    skipped = 0
    failed = []

    for event in events:
        try:
            # check if something already exists at that exact time
            existing = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=f"{event['date']}T{event['start_time']}:00Z",
                    timeMax=f"{event['date']}T{event['end_time']}:00Z",
                    singleEvents=True,
                )
                .execute()
            )

            if existing.get("items"):
                logger.info(f"Skipped (time slot taken): {event.get('title')}")
                skipped += 1
                continue

            body = {
                "summary": event.get("title", "Untitled"),
                "description": event.get("description", ""),
                "start": {
                    "dateTime": f"{event['date']}T{event['start_time']}:00",
                    "timeZone": TIMEZONE,
                },
                "end": {
                    "dateTime": f"{event['date']}T{event['end_time']}:00",
                    "timeZone": TIMEZONE,
                },
            }
            service.events().insert(calendarId="primary", body=body).execute()
            added += 1
            logger.info(f"Added: {event.get('title')}")

        except Exception as e:
            logger.error(f"Failed to add {event.get('title')}: {e}")
            failed.append(event.get("title", "Untitled"))

    return added, skipped, failed


def delete_events(events: list) -> tuple[int, int]:
    service = get_calendar_service()
    deleted = 0
    not_found = 0

    for event in events:
        try:
            date = event["date"]
            # search the whole day for a matching event title
            results = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=f"{date}T00:00:00Z",
                    timeMax=f"{date}T23:59:59Z",
                    q=event.get("title", ""),
                    singleEvents=True,
                )
                .execute()
            )

            matches = results.get("items", [])

            if not matches:
                logger.warning(f"Not found: {event.get('title')} on {date}")
                not_found += 1
                continue

            for match in matches:
                service.events().delete(
                    calendarId="primary", eventId=match["id"]
                ).execute()
                logger.info(f"Deleted: {match.get('summary')} on {date}")
                deleted += 1

        except Exception as e:
            logger.error(f"Failed to delete {event.get('title')}: {e}")
            not_found += 1

    return deleted, not_found

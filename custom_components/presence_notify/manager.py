"""Core logic of Domestic Intelligence Service.

Responsibilities:
- send: push to persons at home and announce on speakers in earshot,
  or store the message when nobody is home
- pending store: persistent, duplicates are merged and counted
- arrival: after someone comes home, wait for the first motion in a
  "return room" and deliver everything there as one briefing
- priorities: emergency (all channels, repeated until acknowledged),
  urgent, normal, low
- clear: remove a tagged notification from all phones and from the store
"""

from __future__ import annotations

import asyncio
from functools import partial
import os
import uuid
from collections.abc import Callable
from datetime import datetime, time
import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, slugify

from .const import (
    ACTION_PREFIX,
    CONF_AI_TASK,
    CONF_DOOR_WINDOW,
    CONF_EMERGENCY_INTERVAL,
    CONF_EMERGENCY_REPEATS,
    CONF_EMERGENCY_STEP,
    CONF_ENTRY_DOORS,
    CONF_PET_MODE,
    CONF_ASK_ALEXA,
    CONF_ASK_SCRIPT,
    CONF_HIGH_PRIORITY,
    CONF_HOLD,
    CONF_HOME_ENTITY,
    CONF_HOME_STATES,
    CONF_IMAGE_MERGE_SECONDS,
    CONF_IMAGES_SEPARATE,
    CONF_MAX_PENDING,
    CONF_NOTIFY,
    CONF_PERSON,
    CONF_PERSONS,
    CONF_PRESENCE,
    CONF_PUSH_ON_ARRIVAL,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_RETURN_ROOM,
    CONF_ROOM_NAME,
    CONF_ROOMS,
    CONF_SPEAKER,
    CONF_TTS_ENTITY,
    DEFAULT_DOOR_WINDOW,
    DEFAULT_EMERGENCY_INTERVAL,
    DEFAULT_EMERGENCY_REPEATS,
    DEFAULT_EMERGENCY_STEP,
    DEFAULT_IMAGE_MERGE_SECONDS,
    DEFAULT_MAX_PENDING,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    DOMAIN,
    EMERGENCY_DATA,
    EVENT_DELIVERED,
    HIGH_PRIORITY_DATA,
    LOW_PRIORITY_DATA,
    PERSON_HOME_STATES,
    PRESENCE_ON_STATES,
    PRIORITY_EMERGENCY,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    PRIORITY_URGENT,
    SIGNAL_UPDATE,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

AI_TIMEOUT = 60
AI_ATTEMPTS = 2

# Emergency announcements: how long to keep the raised volume. Alexa returns
# before it has finished speaking, so the duration is estimated from the text.
ANNOUNCE_BASE_SECONDS = 4.0
ANNOUNCE_SECONDS_PER_CHAR = 0.07
ANNOUNCE_MAX_SECONDS = 60.0
VOLUME_SETTLE_SECONDS = 1.0

TEXTS = {
    "de": {
        "yes": "Ja",
        "no": "Nein",
        "forward": "Weitergeben",
        "forwarded": "(von {name} weitergegeben)",
        "decided": "{who} hat entschieden: {result}.",
        "by_alexa": "Per Alexa entschieden",
        "result_yes": "ja",
        "result_no": "nein",
        "ok_yes": "Alles klar.",
        "ok_no": "In Ordnung, vielleicht später.",
        "missed": "Verpasst",
        "welcome": "Willkommen zu Hause",
        "times": "{n}-mal, zuerst {first}",
        "times_short": "{n}-mal",
        "fallback": "{n} Meldungen: ",
        "prompt": (
            "Du bekommst Smart-Home-Meldungen, die eingegangen sind, während "
            "niemand zu Hause war (Format: Datum Uhrzeit Titel: Text). Fasse sie "
            "zu EINER kurzen, natürlich klingenden Ansage auf Deutsch zusammen, "
            "die ein Sprachassistent vorliest. Regeln: Gleiches oder Ähnliches "
            "zusammenfassen statt wiederholen; Wichtiges zuerst; Uhrzeiten nur "
            "nennen, wenn sie hilfreich sind; keine Begrüßung (die kommt schon "
            "davor); keine Emojis, kein Markdown, keine Aufzählungszeichen; "
            "höchstens vier Sätze. Steht bei einer Meldung, dass sie mehrfach "
            "aufgetreten ist, erwähne das natürlich (z. B. dreimal). Antworte "
            "nur mit dem Ansagetext.\n\nMeldungen:\n{items}"
        ),
        "item_repeat": " [{n}-mal aufgetreten, zuerst {first}]",
        "seen": "Gesehen",
        "acked": "{who} hat den Notfall quittiert.",
        "acked_alexa": "Notfall per Alexa quittiert.",
        "acked_anon": "Der Notfall wurde quittiert.",
        "heard": "Hast du das gehört?",
        "heard_ok": "Danke, ich habe quittiert.",
    },
    "en": {
        "yes": "Yes",
        "no": "No",
        "forward": "Pass on",
        "forwarded": "(passed on by {name})",
        "decided": "{who} decided: {result}.",
        "by_alexa": "Decided via Alexa",
        "result_yes": "yes",
        "result_no": "no",
        "ok_yes": "All right.",
        "ok_no": "Okay, maybe later.",
        "missed": "Missed",
        "welcome": "Welcome home",
        "times": "{n} times, first at {first}",
        "times_short": "{n} times",
        "fallback": "{n} notifications: ",
        "prompt": (
            "You receive smart home notifications that arrived while nobody was "
            "home (format: date time title: text). Summarize them into ONE short, "
            "natural sounding announcement in English that a voice assistant "
            "reads out. Rules: merge identical or similar items instead of "
            "repeating them; most important first; only mention times when "
            "helpful; no greeting (it is added before); no emojis, no markdown, "
            "no bullet points; at most four sentences. If an item occurred "
            "several times, mention it naturally (e.g. three times). Reply with "
            "the announcement text only.\n\nNotifications:\n{items}"
        ),
        "item_repeat": " [occurred {n} times, first at {first}]",
        "seen": "Seen",
        "acked": "{who} acknowledged the emergency.",
        "acked_alexa": "Emergency acknowledged via Alexa.",
        "acked_anon": "The emergency was acknowledged.",
        "heard": "Did you hear that?",
        "heard_ok": "Thanks, acknowledged.",
    },
}

_NON_LATIN1 = re.compile(r"[^\x00-\xFF]")
CAMERA_PROXY_PREFIX = "/api/camera_proxy/"
SNAPSHOT_KEEP_SECONDS = 15 * 60


def _clean_data(data: dict[str, Any] | None) -> dict[str, Any]:
    """Push data without internal keys."""
    return {k: v for k, v in (data or {}).items() if not k.startswith("_")}


def _merge_push(base: dict[str, Any], extras: dict[str, Any] | None) -> dict[str, Any]:
    """Push data from a priority preset plus the caller's data.

    Keys given by the caller win; the iOS ``push`` block is merged key by key,
    so e.g. a custom sound keeps the interruption level.
    """
    extras = dict(extras or {})
    merged = {**base, **extras}
    if isinstance(extras.get("push"), dict) and isinstance(base.get("push"), dict):
        merged["push"] = {**base["push"], **extras["push"]}
    return merged


def _with_priority(extras: dict[str, Any] | None) -> dict[str, Any]:
    """Push data with high priority for Android and iOS."""
    return _merge_push(HIGH_PRIORITY_DATA, extras)


def _escape_ssml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _announce_seconds(text: str) -> float:
    return min(ANNOUNCE_BASE_SECONDS + ANNOUNCE_SECONDS_PER_CHAR * len(text), ANNOUNCE_MAX_SECONDS)


def _button_id(title: str) -> str:
    slug = slugify(title).upper()
    return f"{ACTION_PREFIX}{slug or 'ACTION'}"


def _with_actions(
    data: dict[str, Any], actions: list[dict[str, str]] | None
) -> dict[str, Any]:
    """Turn the form-based buttons into Companion app push actions.

    Each button has a title and optionally an ID (sent back in the
    ``mobile_app_notification_action`` event) or a link to open.
    """
    if not actions:
        return data
    buttons = list(data.get("actions") or [])
    for item in actions:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        uri = (item.get("uri") or "").strip()
        if uri:
            buttons.append({"action": "URI", "title": title, "uri": uri})
        else:
            action = (item.get("action") or "").strip() or _button_id(title)
            buttons.append({"action": action, "title": title})
    return {**data, "actions": buttons} if buttons else data


def _parse_time(value: str | None, default: str) -> time:
    parsed = dt_util.parse_time(value or default)
    return parsed or dt_util.parse_time(default)  # type: ignore[return-value]


class PresenceNotifyManager:
    """Holds state and logic for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.pending: list[dict[str, Any]] = []
        self.last_delivery: datetime | None = None
        self.waiting: bool = False
        self._unsubs: list[Callable[[], None]] = []
        self._wait_unsub: Callable[[], None] | None = None
        self._someone_home: bool = False
        self._deliver_lock = asyncio.Lock()
        self._prepared: tuple[list[dict[str, Any]], str, str] | None = None
        self._last_door_open: datetime | None = None
        self._armed: bool = False
        self._emergencies: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ config

    @property
    def options(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def persons(self) -> list[dict[str, str]]:
        return self.options.get(CONF_PERSONS, [])

    @property
    def rooms(self) -> list[dict[str, Any]]:
        return self.options.get(CONF_ROOMS, [])

    @property
    def lang(self) -> str:
        return "de" if (self.hass.config.language or "").startswith("de") else "en"

    @property
    def texts(self) -> dict[str, str]:
        return TEXTS[self.lang]

    # --------------------------------------------------------------- lifecycle

    async def async_setup(self) -> None:
        """Load stored messages and start listening for arrivals."""
        stored = await self._store.async_load() or {}
        self.pending = stored.get("pending", [])
        last = stored.get("last_delivery")
        self.last_delivery = dt_util.parse_datetime(last) if last else None

        await self.hass.async_add_executor_job(self._cleanup_orphans)
        self._someone_home = self.someone_home()
        person_ids = [p[CONF_PERSON] for p in self.persons]
        if home_entity := self.options.get(CONF_HOME_ENTITY):
            person_ids.append(home_entity)
        if person_ids:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, person_ids, self._handle_person_change
                )
            )
        doors = self.options.get(CONF_ENTRY_DOORS) or []
        if self.options.get(CONF_PET_MODE) and doors:
            self._unsubs.append(
                async_track_state_change_event(self.hass, doors, self._handle_door)
            )
        # Messages left over from before a restart: wait again if someone is home
        if self.pending and self._someone_home:
            self._start_waiting()

    @callback
    def async_unload(self) -> None:
        self._stop_waiting()
        for emergency in list(self._emergencies.values()):
            if task := emergency.get("task"):
                task.cancel()
        self._emergencies.clear()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "pending": self.pending,
                "last_delivery": self.last_delivery.isoformat()
                if self.last_delivery
                else None,
            }
        )
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    # ---------------------------------------------------------------- presence

    def someone_home(self) -> bool:
        """Home source entity (e.g. a house mode) if set, otherwise the persons."""
        home_entity = self.options.get(CONF_HOME_ENTITY)
        if home_entity:
            state = self.hass.states.get(home_entity)
            home_states = self.options.get(CONF_HOME_STATES) or list(PERSON_HOME_STATES)
            return state is not None and state.state in home_states
        return any(
            (state := self.hass.states.get(p[CONF_PERSON])) is not None
            and state.state in PERSON_HOME_STATES
            for p in self.persons
        )

    def persons_home(self) -> list[dict[str, str]]:
        home = [
            p
            for p in self.persons
            if (state := self.hass.states.get(p[CONF_PERSON])) is not None
            and state.state in PERSON_HOME_STATES
        ]
        if not home and self.options.get(CONF_HOME_ENTITY) and self.someone_home():
            # house mode says "home" but no person is tracked as home: push to all
            return list(self.persons)
        return home

    def _room_recency(self, room: dict[str, Any]) -> float | None:
        """How recently someone was detected in the room.

        Returns None if nobody counts as present, ``inf`` while a presence
        entity is on, otherwise the time the last entity went off, as long as
        that is within the room's hold time.
        """
        hold = float(room.get(CONF_HOLD) or 0) * 60
        now = dt_util.utcnow()
        best: float | None = None
        for eid in room.get(CONF_PRESENCE) or []:
            state = self.hass.states.get(eid)
            if state is None:
                continue
            if state.state in PRESENCE_ON_STATES:
                return float("inf")
            if hold and state.state not in ("unavailable", "unknown"):
                age = (now - state.last_changed).total_seconds()
                if age <= hold:
                    ts = state.last_changed.timestamp()
                    best = ts if best is None else max(best, ts)
        return best

    def _room_occupied(self, room: dict[str, Any]) -> bool | None:
        """True/False if the room has presence entities, None if it has none.

        With a hold time, a room still counts as occupied for that many
        minutes after its presence entities went off.
        """
        if not room.get(CONF_PRESENCE):
            return None
        return self._room_recency(room) is not None

    def speakers_in_earshot(self, allowed: list[str] | None = None) -> list[str]:
        """Speakers of occupied rooms plus rooms without sensors.

        Falls back to all speakers when nobody is detected anywhere.
        """
        rooms = [
            r
            for r in self.rooms
            if r.get(CONF_SPEAKER) and (allowed is None or r[CONF_SPEAKER] in allowed)
        ]
        detected: list[str] = []
        unsensed: list[str] = []
        for room in rooms:
            occupied = self._room_occupied(room)
            if occupied:
                detected.append(room[CONF_SPEAKER])
            elif occupied is None:
                unsensed.append(room[CONF_SPEAKER])
        if detected:
            result = detected + unsensed
        else:
            result = [r[CONF_SPEAKER] for r in rooms]
        if allowed is not None:
            # speakers passed explicitly but not configured in any room
            known = {r[CONF_SPEAKER] for r in self.rooms}
            result += [s for s in allowed if s not in known]
        return list(dict.fromkeys(result))

    def in_quiet_hours(self, now: datetime | None = None) -> bool:
        now_t = (now or dt_util.now()).time()
        start = _parse_time(self.options.get(CONF_QUIET_START), DEFAULT_QUIET_START)
        end = _parse_time(self.options.get(CONF_QUIET_END), DEFAULT_QUIET_END)
        if start == end:
            return False
        if start < end:
            return start <= now_t < end
        return now_t >= start or now_t < end

    # -------------------------------------------------------------------- send

    async def async_send(
        self,
        title: str,
        message: str,
        data: dict[str, Any] | None = None,
        speakers: list[str] | None = None,
        ignore_quiet_hours: bool = False,
        actions: list[dict[str, str]] | None = None,
        priority: str = PRIORITY_NORMAL,
        tag: str | None = None,
    ) -> None:
        """Main entry point used by the presence_notify.send service.

        - emergency: push to everyone and announce on all speakers, also at
          night and when nobody is home; repeated until acknowledged
        - urgent: push to everyone right away, announce in earshot if someone
          is home (not during quiet hours)
        - normal: push/announce if someone is home, otherwise store
        - low: push only, and only if someone is home; otherwise dropped
        """
        data = _with_actions(dict(data or {}), actions)
        tag = (tag or str(data.get("tag") or "")).strip() or None
        if tag:
            data["tag"] = tag

        if priority == PRIORITY_EMERGENCY:
            await self._async_emergency(title, message, data, speakers, tag)
            return

        home = self.someone_home()
        if priority == PRIORITY_LOW:
            if home:
                await self._push(title, message, _merge_push(LOW_PRIORITY_DATA, data), raw=True)
            else:
                _LOGGER.debug("Nobody home, low priority notification dropped: %s", title)
            return

        if priority == PRIORITY_URGENT:
            jobs = [
                self._push(title, message, _with_priority(data), persons=self.persons, raw=True)
            ]
            if home:
                jobs.append(
                    self._announce_to(
                        self.speakers_in_earshot(speakers),
                        self._ssml(title, message),
                        ignore_quiet_hours,
                    )
                )
            await asyncio.gather(*jobs)
            return

        if not home:
            await self.async_store(title, message, data, tag)
            return
        await asyncio.gather(
            self._push(title, message, data),
            self._announce_to(
                self.speakers_in_earshot(speakers),
                f"{title}: {message}",
                ignore_quiet_hours,
            ),
        )

    @staticmethod
    def _ssml(title: str, message: str) -> dict[str, str]:
        """Announcement with the title emphasized on Alexa, plain text elsewhere."""
        plain = f"{title}: {message}"
        ssml = (
            f"<emphasis level='strong'>{_escape_ssml(title)}</emphasis>: "
            f"{_escape_ssml(message)}"
        )
        return {"plain": plain, "ssml": ssml}

    async def async_remove(self, tag: str) -> None:
        """Remove a tagged notification everywhere (presence_notify.clear).

        Clears the push on all phones, drops it from the store (so it is not
        part of the briefing) and ends an emergency with the same tag.
        """
        tag = tag.strip()
        if not tag:
            return
        for emergency in list(self._emergencies.values()):
            if emergency["tag"] == tag and not emergency["done"].is_set():
                emergency["by"] = None
                emergency["done"].set()
        removed = [i for i in self.pending if i.get("tag") == tag]
        if removed:
            self.pending = [i for i in self.pending if i.get("tag") != tag]
            self._delete_snapshots(removed)
            if not self.pending:
                self._stop_waiting()
            await self._async_save()
        await self._clear_push(tag, self.persons)

    async def _clear_push(self, tag: str, persons: list[dict[str, str]]) -> None:
        for person in persons:
            await self._notify_person(
                person, "", "clear_notification", _with_priority({"tag": tag})
            )

    async def async_store(
        self, title: str, message: str, data: dict[str, Any], tag: str | None = None
    ) -> None:
        """Store a message.

        Without an image, identical title+message are merged and counted.
        With an image (e.g. a doorbell), every message keeps its own snapshot;
        only a repeat within the merge window (same person ringing twice) is merged.
        A message with a tag replaces a stored one with the same tag.
        """
        now = dt_util.now()
        now_str = now.strftime("%d.%m. %H:%M")
        has_image = bool((data or {}).get("image"))
        window = int(self.options.get(CONF_IMAGE_MERGE_SECONDS, DEFAULT_IMAGE_MERGE_SECONDS))

        merged: dict[str, Any] | None = None
        remaining: list[dict[str, Any]] = []
        replaced: list[dict[str, Any]] = []
        for item in self.pending:
            same = item.get("title") == title and item.get("message") == message
            if same and has_image:
                same = now.timestamp() - float(item.get("ts", 0)) <= window
            if tag and item.get("tag") != tag:
                same = False
            if same and merged is None:
                merged = item
            elif tag and item.get("tag") == tag:
                replaced.append(item)
            else:
                remaining.append(item)
        self._delete_snapshots(replaced)

        if merged is not None:
            merged["count"] = int(merged.get("count", 1)) + 1
            merged["time"] = now_str
            merged["ts"] = now.timestamp()
            # keep the first snapshot (shows who rang)
            if not has_image:
                merged["data"] = data
            remaining.append(merged)
        else:
            if has_image:
                data = await self._async_snapshot(data)
            new_item: dict[str, Any] = {
                "title": title,
                "message": message,
                "data": data,
                "time": now_str,
                "first": now_str,
                "ts": now.timestamp(),
                "count": 1,
            }
            if tag:
                new_item["tag"] = tag
            remaining.append(new_item)
        max_pending = int(self.options.get(CONF_MAX_PENDING, DEFAULT_MAX_PENDING))
        dropped = remaining[:-max_pending]
        self.pending = remaining[-max_pending:]
        self._delete_snapshots(dropped)
        await self._async_save()

    # --------------------------------------------------------------- snapshots

    def _snapshot_dir(self) -> str:
        base = self.hass.config.media_dirs.get("local") or self.hass.config.path("media")
        return os.path.join(base, DOMAIN)

    async def _async_snapshot(self, data: dict[str, Any]) -> dict[str, Any]:
        """Replace a live camera image with a snapshot taken right now."""
        image = str(data.get("image", ""))
        if not image.startswith(CAMERA_PROXY_PREFIX):
            return data
        camera = image[len(CAMERA_PROXY_PREFIX):].split("?", 1)[0]
        folder = self._snapshot_dir()
        name = f"{uuid.uuid4().hex}.jpg"
        path = os.path.join(folder, name)
        if not self.hass.config.is_allowed_path(path):
            _LOGGER.warning("Snapshot folder %s is not allowed, keeping live camera image", folder)
            return data
        try:
            await self.hass.async_add_executor_job(partial(os.makedirs, folder, exist_ok=True))
            await self.hass.services.async_call(
                "camera", "snapshot", {"entity_id": camera, "filename": path}, blocking=True
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Snapshot of %s failed, keeping live image: %s", camera, err)
            return data
        media_rel = os.path.relpath(path, self.hass.config.media_dirs.get("local") or self.hass.config.path("media"))
        return {**data, "image": f"/media/local/{media_rel}", "_snapshot": path}

    def _cleanup_orphans(self) -> None:
        """Remove snapshot files that no stored message refers to (runs in executor)."""
        folder = self._snapshot_dir()
        if not os.path.isdir(folder):
            return
        keep = {(i.get("data") or {}).get("_snapshot") for i in self.pending}
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if path not in keep and name.endswith(".jpg"):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _delete_snapshots(self, items: list[dict[str, Any]], delay: float = 0) -> None:
        files = [
            f for item in items if (f := (item.get("data") or {}).get("_snapshot"))
        ]
        if not files:
            return

        def _remove() -> None:
            for f in files:
                try:
                    os.remove(f)
                except OSError:
                    pass

        if delay:
            async def _later(_now: Any) -> None:
                await self.hass.async_add_executor_job(_remove)

            self._unsubs.append(async_call_later(self.hass, delay, _later))
        else:
            self.hass.async_add_executor_job(_remove)

    async def async_clear(self) -> None:
        self._delete_snapshots(self.pending)
        self.pending = []
        self._stop_waiting()
        await self._async_save()

    # ------------------------------------------------------------- arrival flow

    @callback
    def _handle_person_change(self, event: Event[EventStateChangedData]) -> None:
        was_home = self._someone_home
        self._someone_home = self.someone_home()
        if not was_home and self._someone_home and self.pending:
            self._start_waiting()
        elif was_home and not self._someone_home:
            # everybody left again: keep messages, stop waiting
            self._stop_waiting()

    @property
    def pet_mode(self) -> bool:
        return bool(self.options.get(CONF_PET_MODE) and self.options.get(CONF_ENTRY_DOORS))

    @property
    def wait_phase(self) -> str | None:
        if not self.waiting:
            return None
        return "motion" if self._armed else "door"

    @staticmethod
    def _is_door_open_event(old: str | None, new: str | None) -> bool:
        if new is None:
            return False
        if new == "on":  # binary_sensor door/opening
            return old != "on"
        if new in ("unlocked", "open", "opening", "unlocking"):  # lock
            return old not in ("unlocked", "open", "opening", "unlocking")
        return False

    @callback
    def _handle_door(self, event: Event[EventStateChangedData]) -> None:
        old = event.data["old_state"]
        new = event.data["new_state"]
        if not self._is_door_open_event(old.state if old else None, new.state if new else None):
            return
        self._last_door_open = dt_util.utcnow()
        if self.waiting and not self._armed:
            self._armed = True
            _LOGGER.debug("Entry door opened, motion in return rooms now counts")
            async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    def _door_opened_recently(self) -> bool:
        if self._last_door_open is None:
            return False
        window = int(self.options.get(CONF_DOOR_WINDOW, DEFAULT_DOOR_WINDOW)) * 60
        return (dt_util.utcnow() - self._last_door_open).total_seconds() <= window

    def _return_rooms(self) -> list[dict[str, Any]]:
        return [
            r for r in self.rooms if r.get(CONF_RETURN_ROOM) and r.get(CONF_PRESENCE)
        ]

    @callback
    def _start_waiting(self) -> None:
        self._stop_waiting()
        rooms = self._return_rooms()
        if not rooms:
            # nothing to wait for: deliver right away to speakers in earshot
            self.hass.async_create_task(self.async_deliver())
            return
        entity_to_room: dict[str, dict[str, Any]] = {}
        for room in rooms:
            for eid in room[CONF_PRESENCE]:
                entity_to_room.setdefault(eid, room)

        # pet mode: motion only counts after an entry door was opened
        self._armed = (not self.pet_mode) or self._door_opened_recently()

        @callback
        def _motion(event: Event[EventStateChangedData]) -> None:
            if not self._armed:
                return
            new = event.data["new_state"]
            old = event.data["old_state"]
            if new is None or new.state not in PRESENCE_ON_STATES:
                return
            if old is not None and old.state in PRESENCE_ON_STATES:
                return
            room = entity_to_room.get(event.data["entity_id"])
            self._stop_waiting(keep_prepared=True)
            speakers = [room[CONF_SPEAKER]] if room and room.get(CONF_SPEAKER) else None
            self.hass.async_create_task(self.async_deliver(speakers))

        self._wait_unsub = async_track_state_change_event(
            self.hass, list(entity_to_room), _motion
        )
        self.waiting = True
        if self.options.get(CONF_PUSH_ON_ARRIVAL, True):
            self.hass.async_create_task(self._async_push_on_arrival())
        _LOGGER.debug("Waiting for motion in %s", [r[CONF_ROOM_NAME] for r in rooms])
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    @callback
    def _stop_waiting(self, keep_prepared: bool = False) -> None:
        if not keep_prepared:
            self._prepared = None
        if self._wait_unsub:
            self._wait_unsub()
            self._wait_unsub = None
        self._armed = False
        if self.waiting:
            self.waiting = False
            async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    async def _compose(self, items: list[dict[str, Any]]) -> tuple[str, str, dict[str, Any]]:
        """Title, text and push data for a set of stored messages."""
        t = self.texts
        if len(items) == 1:
            item = items[0]
            message = item["message"]
            if int(item.get("count", 1)) > 1:
                message += " (" + t["times"].format(
                    n=item["count"], first=item.get("first", "")
                ) + ")"
            return f"🏠 {t['missed']}: {item['title']}", message, item.get("data") or {}
        return f"🏠 {t['welcome']}", await self._briefing(items), {}

    async def _push_items(
        self, items: list[dict[str, Any]], title: str, message: str, data: dict[str, Any]
    ) -> None:
        if len(items) == 1:
            await self._push(title, message, _clean_data(data))
            return
        with_image = [i for i in items if (i.get("data") or {}).get("image")]
        if len(with_image) == 1:
            # single picture: attach it to the briefing -> exactly one push
            await self._push(title, message, {"image": with_image[0]["data"]["image"]})
            return
        await self._push(title, message, data)
        if with_image and self.options.get(CONF_IMAGES_SEPARATE, True):
            for item in with_image:
                count = int(item.get("count", 1))
                text = item["message"]
                if count > 1:
                    text += " (" + self.texts["times_short"].format(n=count) + ")"
                await self._push(
                    f"{item['title']} · {item.get('time', '')}",
                    text,
                    {**_clean_data(item["data"]), "group": DOMAIN},
                )

    async def _async_push_on_arrival(self) -> None:
        """Push the briefing right away; the announcement waits for motion."""
        async with self._deliver_lock:
            items = list(self.pending)
            if not items or not self.waiting:
                return
            title, message, data = await self._compose(items)
            await self._push_items(items, title, message, data)
            self._prepared = (items, title, message)

    async def async_deliver(self, speakers: list[str] | None = None) -> None:
        """Deliver all pending messages as one briefing (ignores quiet hours)."""
        async with self._deliver_lock:
            if not self.pending:
                return
            items = self.pending
            prepared = self._prepared if self._prepared and self._prepared[0] == items else None
            # clear first so nothing new is lost or delivered twice
            self.pending = []
            self._stop_waiting()
            await self._async_save()

            if speakers is None:
                speakers = self.speakers_in_earshot()

            if prepared:
                # push already went out on arrival
                _, title, message = prepared
                await self._announce_to(speakers, f"{title}: {message}", True)
            else:
                title, message, data = await self._compose(items)
                await asyncio.gather(
                    self._push_items(items, title, message, data),
                    self._announce_to(speakers, f"{title}: {message}", True),
                )

            self._delete_snapshots(items, delay=SNAPSHOT_KEEP_SECONDS)
            self.last_delivery = dt_util.utcnow()
            await self._async_save()
            self.hass.bus.async_fire(
                EVENT_DELIVERED, {"count": len(items), "speakers": speakers}
            )

    # ---------------------------------------------------------------- briefing

    def _fallback_text(self, items: list[dict[str, Any]]) -> str:
        t = self.texts
        parts = []
        for item in items:
            part = f"{item['title']}: {item['message']}"
            if int(item.get("count", 1)) > 1:
                part += " (" + t["times_short"].format(n=item["count"]) + ")"
            parts.append(part)
        return t["fallback"].format(n=len(items)) + ". ".join(parts) + "."

    async def _briefing(self, items: list[dict[str, Any]]) -> str:
        ai_entity = self.options.get(CONF_AI_TASK)
        if not ai_entity:
            return self._fallback_text(items)
        t = self.texts
        lines = []
        for item in items:
            line = f"- {item.get('time', '')} {item['title']}: {item['message']}"
            if int(item.get("count", 1)) > 1:
                line += t["item_repeat"].format(n=item["count"], first=item.get("first", ""))
            lines.append(line)
        instructions = t["prompt"].format(items="\n".join(lines))

        for attempt in range(1, AI_ATTEMPTS + 1):
            try:
                async with asyncio.timeout(AI_TIMEOUT):
                    response = await self.hass.services.async_call(
                        "ai_task",
                        "generate_data",
                        {
                            "task_name": "Domestic Intelligence Service briefing",
                            "entity_id": ai_entity,
                            "instructions": instructions,
                        },
                        blocking=True,
                        return_response=True,
                    )
                text = str((response or {}).get("data") or "").strip()
                if text:
                    return text
            except Exception as err:  # noqa: BLE001 - any AI failure falls back
                _LOGGER.warning("AI briefing attempt %s failed: %s", attempt, err)
            if attempt < AI_ATTEMPTS:
                await asyncio.sleep(2)
        return self._fallback_text(items)


    # -------------------------------------------------------------- emergency

    @property
    def emergency_active(self) -> bool:
        return any(not e["done"].is_set() for e in self._emergencies.values())

    def _name_for_user(self, user_id: str | None) -> str:
        if not user_id:
            return ""
        for state in self.hass.states.async_all("person"):
            if state.attributes.get("user_id") == user_id:
                return state.name
        return ""

    def _all_speakers(self, allowed: list[str] | None) -> list[str]:
        if allowed:
            return list(dict.fromkeys(allowed))
        return list(dict.fromkeys(r[CONF_SPEAKER] for r in self.rooms if r.get(CONF_SPEAKER)))

    def _volume_step(self, speaker: str) -> int:
        for room in self.rooms:
            if room.get(CONF_SPEAKER) == speaker:
                return int(room.get(CONF_EMERGENCY_STEP, DEFAULT_EMERGENCY_STEP) or 0)
        return 0

    async def _raise_volume(self, speakers: list[str]) -> dict[str, tuple[float, float]]:
        """Raise each speaker by its room's step (Alexa scale 0–10, max 10).

        Returns {speaker: (old, new)} for the speakers that were changed.
        """
        changed: dict[str, tuple[float, float]] = {}
        for speaker in speakers:
            step = self._volume_step(speaker)
            state = self.hass.states.get(speaker)
            old = state.attributes.get("volume_level") if state else None
            if step <= 0 or old is None:
                continue
            new = round(min(1.0, float(old) + step / 10), 2)
            if new <= float(old):
                continue
            try:
                await self.hass.services.async_call(
                    "media_player",
                    "volume_set",
                    {"entity_id": speaker, "volume_level": new},
                    blocking=True,
                )
                changed[speaker] = (float(old), new)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Raising the volume of %s failed: %s", speaker, err)
        if changed and VOLUME_SETTLE_SECONDS:
            await asyncio.sleep(VOLUME_SETTLE_SECONDS)
        return changed

    async def _restore_volume(self, changed: dict[str, tuple[float, float]]) -> None:
        for speaker, (old, new) in changed.items():
            state = self.hass.states.get(speaker)
            current = state.attributes.get("volume_level") if state else None
            if current is not None and abs(float(current) - new) > 0.011:
                continue  # changed by hand in the meantime: leave it
            try:
                await self.hass.services.async_call(
                    "media_player",
                    "volume_set",
                    {"entity_id": speaker, "volume_level": old},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Restoring the volume of %s failed: %s", speaker, err)

    async def _async_emergency(
        self,
        title: str,
        message: str,
        data: dict[str, Any],
        speakers: list[str] | None,
        tag: str | None,
    ) -> None:
        """Push right away; announcement and repetitions in the background."""
        t = self.texts
        eid = uuid.uuid4().hex[:10]
        tag = tag or f"{DOMAIN}_emergency_{eid}"
        ack_action = f"PN_ACK_{eid}"
        alexa_id = f"{DOMAIN}_emergency_{eid}"
        push_data = _merge_push(EMERGENCY_DATA, {**data, "tag": tag})
        push_data["actions"] = [{"action": ack_action, "title": t["seen"]}] + list(
            push_data.get("actions") or []
        )
        emergency: dict[str, Any] = {
            "tag": tag,
            "done": asyncio.Event(),
            "by": None,
            "acked": False,
        }

        @callback
        def _ack(by: str) -> None:
            if emergency["done"].is_set():
                return
            emergency["by"] = by
            emergency["acked"] = True
            emergency["done"].set()

        emergency["ack"] = _ack

        @callback
        def _on_push(event: Event) -> None:
            if event.data.get("action") == ack_action:
                _ack(self._name_for_user(event.context.user_id))

        @callback
        def _on_alexa(event: Event) -> None:
            if (
                event.data.get("event_id") == alexa_id
                and event.data.get("event_response_type") == "ResponseYes"
            ):
                _ack("Alexa")

        unsubs = [
            self.hass.bus.async_listen("mobile_app_notification_action", _on_push),
            self.hass.bus.async_listen("alexa_actionable_notification", _on_alexa),
        ]
        self._emergencies[eid] = emergency
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

        async def _round(push: bool = True) -> None:
            if push:
                await self._push(title, message, push_data, persons=self.persons, raw=True)
            if emergency["done"].is_set():
                return
            targets = self._all_speakers(speakers)
            changed = await self._raise_volume(targets)
            text = self._ssml(title, message)
            await self._announce_to(targets, text, True)
            if changed:
                await asyncio.sleep(_announce_seconds(text["plain"]))
                await self._restore_volume(changed)
            if asked := await self._ask_heard(alexa_id, speakers):
                emergency["alexa_speaker"] = asked

        async def _repeat() -> None:
            interval = float(
                self.options.get(CONF_EMERGENCY_INTERVAL, DEFAULT_EMERGENCY_INTERVAL)
            ) * 60
            repeats = int(self.options.get(CONF_EMERGENCY_REPEATS, DEFAULT_EMERGENCY_REPEATS))
            try:
                await _round(push=False)  # first announcement
                for _ in range(repeats):
                    try:
                        async with asyncio.timeout(interval):
                            await emergency["done"].wait()
                    except TimeoutError:
                        await _round()
                    if emergency["done"].is_set():
                        break
                if not emergency["done"].is_set():
                    # last repetition sent: still give time to acknowledge it
                    try:
                        async with asyncio.timeout(interval):
                            await emergency["done"].wait()
                    except TimeoutError:
                        pass
            finally:
                for unsub in unsubs:
                    unsub()
                self._emergencies.pop(eid, None)
                async_dispatcher_send(self.hass, SIGNAL_UPDATE)
            if emergency["acked"]:
                await self._after_ack(title, tag, emergency["by"] or "")
                if emergency["by"] == "Alexa" and emergency.get("alexa_speaker"):
                    await self._alexa_say(emergency["alexa_speaker"], self.texts["heard_ok"])

        # the push goes out before the service call returns; announcement,
        # volume and repetitions run in the background
        await self._push(title, message, push_data, persons=self.persons, raw=True)
        emergency["task"] = self.entry.async_create_background_task(
            self.hass, _repeat(), f"{DOMAIN} emergency {eid}"
        )

    async def _ask_heard(self, alexa_id: str, speakers: list[str] | None) -> str | None:
        """Alexa asks "Did you hear that?" in the room where someone is detected.

        Returns the speaker that was asked.
        """
        script = self.options.get(CONF_ASK_SCRIPT)
        if not (self.options.get(CONF_ASK_ALEXA) and script):
            return None
        speaker = self._detected_speaker(speakers)
        if not speaker:
            return None
        try:
            await self.hass.services.async_call(
                "script",
                "turn_on",
                {
                    "entity_id": script,
                    "variables": {
                        "text": self.texts["heard"],
                        "event_id": alexa_id,
                        "alexa_device": speaker,
                        "suppress_confirmation": "true",
                    },
                },
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Alexa emergency question via %s failed: %s", script, err)
            return None
        return speaker

    async def _alexa_say(self, speaker: str, text: str) -> None:
        try:
            await self.hass.services.async_call(
                "notify",
                "alexa_media",
                {"message": _NON_LATIN1.sub("", text), "target": [speaker], "data": {"type": "tts"}},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Alexa confirmation failed: %s", err)

    async def _after_ack(self, title: str, tag: str, by: str) -> None:
        """Remove the emergency push everywhere and tell the others."""
        t = self.texts
        await self._clear_push(tag, self.persons)
        if by == "Alexa":
            info = t["acked_alexa"]
        elif by:
            info = t["acked"].format(who=by)
        else:
            info = t["acked_anon"]
        for person in self.persons:
            if by and self._person_name(person[CONF_PERSON]) == by:
                continue
            await self._notify_person(
                person, title, info, _with_priority({"tag": f"{tag}_ack"})
            )

    @callback
    def async_acknowledge(self, user_id: str | None = None) -> None:
        """Acknowledge all running emergencies (button entity)."""
        name = self._name_for_user(user_id)
        for emergency in list(self._emergencies.values()):
            emergency["ack"](name)

    # -------------------------------------------------------------------- ask

    def _detected_speaker(self, allowed: list[str] | None) -> str | None:
        """Speaker of the room with the most recent detection (no fallback).

        A room where someone is detected right now wins over one that only
        counts as occupied because of its hold time.
        """
        best: tuple[float, str] | None = None
        for room in self.rooms:
            speaker = room.get(CONF_SPEAKER)
            if not speaker or (allowed is not None and speaker not in allowed):
                continue
            if not room.get(CONF_PRESENCE):
                continue
            recency = self._room_recency(room)
            if recency is not None and (best is None or recency > best[0]):
                best = (recency, speaker)
        return best[1] if best else None

    def _person_name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return state.name if state else entity_id

    async def async_ask(
        self,
        title: str,
        question: str,
        timeout_min: float = 15,
        text_yes: str | None = None,
        text_no: str | None = None,
        speakers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ask yes/no by push (and Alexa if enabled). First answer wins.

        Returns {"answer": "yes"|"no"|"timeout", "by": <name or "Alexa" or "">}.
        """
        t = self.texts
        ask_id = uuid.uuid4().hex[:10]
        tag = f"{DOMAIN}_ask_{ask_id}"
        a_yes, a_no, a_fwd = f"PN_YES_{ask_id}", f"PN_NO_{ask_id}", f"PN_FWD_{ask_id}"

        home = self.persons_home() if self.someone_home() else []
        forwarded_to: list[dict[str, str]] = []
        if home:
            asked = list(home)
            can_forward = False
        else:
            asked = self.persons[:1]
            can_forward = len(self.persons) > 1
        others = [p for p in self.persons if p not in asked]

        def _actions(with_forward: bool) -> list[dict[str, str]]:
            acts = [{"action": a_yes, "title": t["yes"]}, {"action": a_no, "title": t["no"]}]
            if with_forward:
                acts.append({"action": a_fwd, "title": t["forward"]})
            return acts

        async def _push_to(persons: list[dict[str, str]], message: str, with_forward: bool) -> None:
            data = _with_priority({"tag": tag, "actions": _actions(with_forward)})
            for person in persons:
                await self._notify_person(person, title, message, data)

        answer: asyncio.Future[tuple[str, str]] = self.hass.loop.create_future()

        def _name_from_context(event: Event) -> str:
            user_id = event.context.user_id
            for state in self.hass.states.async_all("person"):
                if user_id and state.attributes.get("user_id") == user_id:
                    return state.name
            return ""

        @callback
        def _on_push(event: Event) -> None:
            action = event.data.get("action")
            if answer.done():
                return
            if action == a_yes:
                answer.set_result(("yes", _name_from_context(event)))
            elif action == a_no:
                answer.set_result(("no", _name_from_context(event)))
            elif action == a_fwd and others and not forwarded_to:
                forwarded_to.extend(others)
                name = _name_from_context(event) or self._person_name(asked[0][CONF_PERSON])
                self.hass.async_create_task(
                    _push_to(others, f"{question} {t['forwarded'].format(name=name)}", False)
                )

        @callback
        def _on_alexa(event: Event) -> None:
            if answer.done() or event.data.get("event_id") != tag:
                return
            kind = event.data.get("event_response_type")
            if kind == "ResponseYes":
                answer.set_result(("yes", "Alexa"))
            elif kind == "ResponseNo":
                answer.set_result(("no", "Alexa"))

        unsubs = [
            self.hass.bus.async_listen("mobile_app_notification_action", _on_push),
            self.hass.bus.async_listen("alexa_actionable_notification", _on_alexa),
        ]

        await _push_to(asked, question, can_forward)

        alexa_speaker = None
        script = self.options.get(CONF_ASK_SCRIPT)
        if self.options.get(CONF_ASK_ALEXA) and script and home and not self.in_quiet_hours():
            alexa_speaker = self._detected_speaker(speakers)
            if alexa_speaker:
                try:
                    await self.hass.services.async_call(
                        "script",
                        "turn_on",
                        {
                            "entity_id": script,
                            "variables": {
                                "text": question,
                                "event_id": tag,
                                "alexa_device": alexa_speaker,
                                "suppress_confirmation": "true",
                            },
                        },
                        blocking=True,
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Alexa question via %s failed: %s", script, err)
                    alexa_speaker = None

        try:
            async with asyncio.timeout(max(float(timeout_min), 0.05) * 60):
                result, by = await answer
        except TimeoutError:
            result, by = "timeout", ""
        finally:
            for unsub in unsubs:
                unsub()

        # remove the question everywhere
        for person in asked + forwarded_to:
            await self._notify_person(
                person, "", "clear_notification", _with_priority({"tag": tag})
            )

        # Alexa confirms its own question
        if by == "Alexa" and alexa_speaker:
            reply = (text_yes or t["ok_yes"]) if result == "yes" else (text_no or t["ok_no"])
            try:
                await self.hass.services.async_call(
                    "notify",
                    "alexa_media",
                    {"message": _NON_LATIN1.sub("", reply), "target": [alexa_speaker], "data": {"type": "tts"}},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Alexa confirmation failed: %s", err)

        # tell the others who decided, when several people were asked
        if result in ("yes", "no") and len(asked + forwarded_to) > 1:
            who = t["by_alexa"] if by == "Alexa" else (by or "?")
            info = t["decided"].format(
                who=who, result=t["result_yes"] if result == "yes" else t["result_no"]
            )
            for person in asked + forwarded_to:
                if by and self._person_name(person[CONF_PERSON]) == by:
                    continue
                await self._notify_person(
                    person, title, info, _with_priority({"tag": f"{tag}_info"})
                )

        return {"answer": result, "by": by}

    async def _notify_person(
        self, person: dict[str, str], title: str, message: str, data: dict[str, Any]
    ) -> None:
        domain, _, name = person.get(CONF_NOTIFY, "").partition(".")
        if domain != "notify" or not name:
            return
        payload: dict[str, Any] = {"message": message, "data": data}
        if title:
            payload["title"] = title
        try:
            await self.hass.services.async_call("notify", name, payload, blocking=True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Push via notify.%s failed: %s", name, err)

    # ----------------------------------------------------------- push/announce

    async def _push(
        self,
        title: str,
        message: str,
        data: dict[str, Any],
        persons: list[dict[str, str]] | None = None,
        raw: bool = False,
    ) -> None:
        """Push to the persons at home (or the given persons).

        ``raw`` sends the data as given (priority already applied), otherwise
        the general "high priority" setting decides.
        """
        extras = data if isinstance(data, dict) else {}
        if raw or not self.options.get(CONF_HIGH_PRIORITY, True):
            payload_data = extras
        else:
            payload_data = _with_priority(extras)
        for person in self.persons_home() if persons is None else persons:
            service = person.get(CONF_NOTIFY, "")
            domain, _, name = service.partition(".")
            if domain != "notify" or not name:
                _LOGGER.warning("Invalid notify service for %s: %s", person[CONF_PERSON], service)
                continue
            try:
                await self.hass.services.async_call(
                    "notify",
                    name,
                    {"title": title, "message": message, "data": payload_data},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Push via %s failed: %s", service, err)

    async def _announce_to(
        self, speakers: list[str], text: str | dict[str, str], ignore_quiet_hours: bool
    ) -> None:
        """Announce on the speakers.

        ``text`` is plain text or {"plain": ..., "ssml": ...}; Alexa speakers
        get the SSML version, other speakers the plain one.
        """
        if not speakers:
            return
        if not ignore_quiet_hours and self.in_quiet_hours():
            _LOGGER.debug("Quiet hours, announcement skipped")
            return
        if isinstance(text, dict):
            plain, alexa_text, alexa_data = text["plain"], text["ssml"], {
                "type": "announce",
                "method": "speak",
            }
        else:
            plain, alexa_text, alexa_data = text, text, {"type": "announce"}
        text = plain
        ent_reg = er.async_get(self.hass)
        alexa = []
        other = []
        for speaker in speakers:
            entry = ent_reg.async_get(speaker)
            if entry and entry.platform == "alexa_media":
                alexa.append(speaker)
            else:
                other.append(speaker)

        if alexa:
            try:
                await self.hass.services.async_call(
                    "notify",
                    "alexa_media",
                    {
                        "message": _NON_LATIN1.sub("", alexa_text).strip(),
                        "target": alexa,
                        "data": alexa_data,
                    },
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Alexa announcement failed: %s", err)

        if other:
            tts_entity = self.options.get(CONF_TTS_ENTITY)
            if not tts_entity:
                _LOGGER.warning(
                    "No TTS entity configured, cannot announce on %s", other
                )
                return
            try:
                await self.hass.services.async_call(
                    "tts",
                    "speak",
                    {
                        "entity_id": tts_entity,
                        "media_player_entity_id": other,
                        "message": text,
                    },
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("TTS announcement failed: %s", err)

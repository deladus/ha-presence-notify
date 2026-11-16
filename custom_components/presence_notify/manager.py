"""Core logic of Domestic Intelligence Service.

Responsibilities:
- send: push to persons at home and announce on speakers in earshot,
  or store the message when nobody is home
- pending store: persistent, duplicates are merged and counted
- arrival: after someone comes home, wait for the first motion in a
  "return room" and deliver everything there as one briefing
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, time
import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AI_TASK,
    CONF_HIGH_PRIORITY,
    CONF_HOME_ENTITY,
    CONF_HOME_STATES,
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
    DEFAULT_MAX_PENDING,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    EVENT_DELIVERED,
    HIGH_PRIORITY_DATA,
    PERSON_HOME_STATES,
    PRESENCE_ON_STATES,
    SIGNAL_UPDATE,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

AI_TIMEOUT = 60
AI_ATTEMPTS = 2

TEXTS = {
    "de": {
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
    },
    "en": {
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
    },
}

_NON_LATIN1 = re.compile(r"[^\x00-\xFF]")


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
        # Messages left over from before a restart: wait again if someone is home
        if self.pending and self._someone_home:
            self._start_waiting()

    @callback
    def async_unload(self) -> None:
        self._stop_waiting()
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

    def _room_occupied(self, room: dict[str, Any]) -> bool | None:
        """True/False if the room has presence entities, None if it has none."""
        entities = room.get(CONF_PRESENCE) or []
        if not entities:
            return None
        return any(
            (state := self.hass.states.get(eid)) is not None
            and state.state in PRESENCE_ON_STATES
            for eid in entities
        )

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
    ) -> None:
        """Main entry point used by the presence_notify.send service."""
        data = data or {}
        if not self.someone_home():
            await self.async_store(title, message, data)
            return
        await asyncio.gather(
            self._push(title, message, data),
            self._announce_to(
                self.speakers_in_earshot(speakers),
                f"{title}: {message}",
                ignore_quiet_hours,
            ),
        )

    async def async_store(self, title: str, message: str, data: dict[str, Any]) -> None:
        """Store a message; identical title+message are merged and counted."""
        now_str = dt_util.now().strftime("%d.%m. %H:%M")
        count, first = 1, now_str
        remaining: list[dict[str, Any]] = []
        for item in self.pending:
            if item.get("title") == title and item.get("message") == message:
                count += int(item.get("count", 1))
                first = item.get("first", item.get("time", now_str))
            else:
                remaining.append(item)
        remaining.append(
            {
                "title": title,
                "message": message,
                "data": data,
                "time": now_str,
                "first": first,
                "count": count,
            }
        )
        max_pending = int(self.options.get(CONF_MAX_PENDING, DEFAULT_MAX_PENDING))
        self.pending = remaining[-max_pending:]
        await self._async_save()

    async def async_clear(self) -> None:
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

        @callback
        def _motion(event: Event[EventStateChangedData]) -> None:
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
        await self._push(title, message, data)
        if len(items) > 1 and self.options.get(CONF_IMAGES_SEPARATE, True):
            for item in items:
                item_data = item.get("data") or {}
                if item_data.get("image"):
                    await self._push(
                        f"🏠 {self.texts['missed']}: {item['title']}",
                        item["message"],
                        item_data,
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

    # ----------------------------------------------------------- push/announce

    async def _push(self, title: str, message: str, data: dict[str, Any]) -> None:
        extras = data if isinstance(data, dict) else {}
        if self.options.get(CONF_HIGH_PRIORITY, True):
            payload_data = {**HIGH_PRIORITY_DATA, **extras}
        else:
            payload_data = extras
        for person in self.persons_home():
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
        self, speakers: list[str], text: str, ignore_quiet_hours: bool
    ) -> None:
        if not speakers:
            return
        if not ignore_quiet_hours and self.in_quiet_hours():
            _LOGGER.debug("Quiet hours, announcement skipped")
            return
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
                        "message": _NON_LATIN1.sub("", text).strip(),
                        "target": alexa,
                        "data": {"type": "announce"},
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

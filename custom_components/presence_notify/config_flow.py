"""Config and options flow for Presence Notify."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_AI_TASK,
    CONF_HIGH_PRIORITY,
    CONF_IMAGES_SEPARATE,
    CONF_MAX_PENDING,
    CONF_NOTIFY,
    CONF_PERSON,
    CONF_PERSONS,
    CONF_PRESENCE,
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
    DOMAIN,
)

CONF_ADD_ANOTHER = "add_another"
CONF_ROOM_SELECT = "room"
PRESENCE_DOMAINS = [
    "binary_sensor",
    "light",
    "switch",
    "media_player",
    "input_boolean",
    "device_tracker",
]


def _notify_services(hass: HomeAssistant) -> list[str]:
    skip = {"send_message", "persistent_notification"}
    return sorted(
        f"notify.{name}"
        for name in hass.services.async_services_for_domain("notify")
        if name not in skip
    )


def _general_schema(full: bool) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(CONF_QUIET_START, default=DEFAULT_QUIET_START): selector.TimeSelector(),
        vol.Required(CONF_QUIET_END, default=DEFAULT_QUIET_END): selector.TimeSelector(),
        vol.Optional(CONF_AI_TASK): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="ai_task")
        ),
        vol.Optional(CONF_TTS_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="tts")
        ),
    }
    if full:
        fields.update(
            {
                vol.Required(CONF_MAX_PENDING, default=DEFAULT_MAX_PENDING): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=100, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_HIGH_PRIORITY, default=True): selector.BooleanSelector(),
                vol.Required(CONF_IMAGES_SEPARATE, default=True): selector.BooleanSelector(),
            }
        )
    return vol.Schema(fields)


PERSONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PERSONS): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="person", multiple=True)
        )
    }
)


def _room_schema(with_add_another: bool) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(CONF_ROOM_NAME): selector.TextSelector(),
        vol.Optional(CONF_SPEAKER): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="media_player")
        ),
        vol.Optional(CONF_PRESENCE, default=[]): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=PRESENCE_DOMAINS, multiple=True)
        ),
        vol.Required(CONF_RETURN_ROOM, default=False): selector.BooleanSelector(),
    }
    if with_add_another:
        fields[vol.Required(CONF_ADD_ANOTHER, default=False)] = selector.BooleanSelector()
    return vol.Schema(fields)


def _clean_room(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_ROOM_NAME: user_input[CONF_ROOM_NAME].strip(),
        CONF_SPEAKER: user_input.get(CONF_SPEAKER),
        CONF_PRESENCE: list(user_input.get(CONF_PRESENCE) or []),
        CONF_RETURN_ROOM: bool(user_input.get(CONF_RETURN_ROOM)),
    }


class _PersonsMixin:
    """Shared steps: choose persons, then one notify service per person."""

    hass: HomeAssistant
    _opts: dict[str, Any]
    _person_queue: list[str]
    _persons: list[dict[str, str]]

    def _start_persons(self, persons: list[str]) -> None:
        self._person_queue = list(persons)
        self._persons = []

    def _person_notify_form(self, existing: dict[str, str]) -> ConfigFlowResult:
        person = self._person_queue[0]
        state = self.hass.states.get(person)
        name = state.name if state else person
        schema = vol.Schema(
            {
                vol.Required(CONF_NOTIFY, default=existing.get(person, "")): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_notify_services(self.hass),
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="person_notify",
            data_schema=schema,
            description_placeholders={"person": name},
        )


class PresenceNotifyConfigFlow(_PersonsMixin, ConfigFlow, domain=DOMAIN):
    """Initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._opts: dict[str, Any] = {CONF_ROOMS: []}
        self._person_queue = []
        self._persons = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._opts.update(user_input)
            return await self.async_step_persons()
        return self.async_show_form(step_id="user", data_schema=_general_schema(False))

    async def async_step_persons(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._start_persons(user_input[CONF_PERSONS])
            return await self.async_step_person_notify()
        return self.async_show_form(step_id="persons", data_schema=PERSONS_SCHEMA)

    async def async_step_person_notify(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            person = self._person_queue.pop(0)
            self._persons.append({CONF_PERSON: person, CONF_NOTIFY: user_input[CONF_NOTIFY]})
        if self._person_queue:
            return self._person_notify_form({})
        self._opts[CONF_PERSONS] = self._persons
        return await self.async_step_room()

    async def async_step_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._opts[CONF_ROOMS].append(_clean_room(user_input))
            if user_input.get(CONF_ADD_ANOTHER):
                return self.async_show_form(step_id="room", data_schema=_room_schema(True))
            return self.async_create_entry(title="Presence Notify", data={}, options=self._opts)
        return self.async_show_form(step_id="room", data_schema=_room_schema(True))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PresenceNotifyOptionsFlow()


class PresenceNotifyOptionsFlow(_PersonsMixin, OptionsFlow):
    """Change settings, persons and rooms later."""

    def __init__(self) -> None:
        self._opts: dict[str, Any] = {}
        self._person_queue = []
        self._persons = []
        self._edit_index: int | None = None

    def _load(self) -> None:
        if not self._opts:
            self._opts = {
                **self.config_entry.options,
                CONF_ROOMS: [dict(r) for r in self.config_entry.options.get(CONF_ROOMS, [])],
            }

    def _save(self) -> ConfigFlowResult:
        return self.async_create_entry(data=self._opts)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._load()
        menu = ["general", "persons", "add_room"]
        if self._opts.get(CONF_ROOMS):
            menu += ["edit_room", "remove_room"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_general(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            for key in (CONF_AI_TASK, CONF_TTS_ENTITY):
                self._opts.pop(key, None)
            user_input[CONF_MAX_PENDING] = int(user_input[CONF_MAX_PENDING])
            self._opts.update(user_input)
            return self._save()
        schema = self.add_suggested_values_to_schema(_general_schema(True), self._opts)
        return self.async_show_form(step_id="general", data_schema=schema)

    async def async_step_persons(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._start_persons(user_input[CONF_PERSONS])
            return await self.async_step_person_notify()
        current = [p[CONF_PERSON] for p in self._opts.get(CONF_PERSONS, [])]
        schema = self.add_suggested_values_to_schema(PERSONS_SCHEMA, {CONF_PERSONS: current})
        return self.async_show_form(step_id="persons", data_schema=schema)

    async def async_step_person_notify(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        existing = {p[CONF_PERSON]: p[CONF_NOTIFY] for p in self._opts.get(CONF_PERSONS, [])}
        if user_input is not None:
            person = self._person_queue.pop(0)
            self._persons.append({CONF_PERSON: person, CONF_NOTIFY: user_input[CONF_NOTIFY]})
        if self._person_queue:
            return self._person_notify_form(existing)
        self._opts[CONF_PERSONS] = self._persons
        return self._save()

    async def async_step_add_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._opts[CONF_ROOMS].append(_clean_room(user_input))
            return self._save()
        return self.async_show_form(step_id="add_room", data_schema=_room_schema(False))

    def _room_choice_schema(self, multiple: bool) -> vol.Schema:
        options = [
            selector.SelectOptionDict(value=str(i), label=r[CONF_ROOM_NAME])
            for i, r in enumerate(self._opts[CONF_ROOMS])
        ]
        return vol.Schema(
            {
                vol.Required(CONF_ROOM_SELECT): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, multiple=multiple)
                )
            }
        )

    async def async_step_edit_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._edit_index = int(user_input[CONF_ROOM_SELECT])
            return await self.async_step_edit_room_details()
        return self.async_show_form(step_id="edit_room", data_schema=self._room_choice_schema(False))

    async def async_step_edit_room_details(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._edit_index is not None
        if user_input is not None:
            self._opts[CONF_ROOMS][self._edit_index] = _clean_room(user_input)
            return self._save()
        room = self._opts[CONF_ROOMS][self._edit_index]
        schema = self.add_suggested_values_to_schema(_room_schema(False), room)
        return self.async_show_form(step_id="edit_room_details", data_schema=schema)

    async def async_step_remove_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            remove = {int(i) for i in user_input[CONF_ROOM_SELECT]}
            self._opts[CONF_ROOMS] = [
                r for i, r in enumerate(self._opts[CONF_ROOMS]) if i not in remove
            ]
            return self._save()
        return self.async_show_form(step_id="remove_room", data_schema=self._room_choice_schema(True))

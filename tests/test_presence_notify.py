"""Tests for Presence Notify."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.presence_notify.const import DOMAIN

OPTIONS = {
    "quiet_start": "22:30:00",
    "quiet_end": "08:00:00",
    "ai_task_entity": "ai_task.test",
    "persons": [
        {"person": "person.dennis", "notify": "notify.dennis_alle_geraete"},
        {"person": "person.christos", "notify": "notify.christos_alle_geraete"},
    ],
    "rooms": [
        {"name": "Wohnzimmer", "speaker": "media_player.studio",
         "presence": ["binary_sensor.wz"], "return_room": True},
        {"name": "Küche", "speaker": "media_player.kueche",
         "presence": ["binary_sensor.kueche"], "return_room": True},
        {"name": "Schlafzimmer", "speaker": "media_player.schlaf",
         "presence": [], "return_room": False},
    ],
}


def _register_services(hass: HomeAssistant, ai_text: str = "Briefing-Text"):
    calls: dict[str, list[ServiceCall]] = {"push": [], "tts": [], "ai": []}

    async def push(call):
        calls["push"].append(call)

    async def tts(call):
        calls["tts"].append(call)

    async def ai(call):
        calls["ai"].append(call)
        return {"data": ai_text}

    hass.services.async_register("notify", "dennis_alle_geraete", push)
    hass.services.async_register("notify", "christos_alle_geraete", push)
    hass.services.async_register("tts", "speak", tts)
    hass.services.async_register("ai_task", "generate_data", ai,
                                 supports_response=SupportsResponse.ONLY)
    return calls


async def _setup(hass: HomeAssistant, home: bool = False, **extra):
    for p in ("person.dennis", "person.christos"):
        hass.states.async_set(p, "home" if home else "not_home")
    for s in ("binary_sensor.wz", "binary_sensor.kueche"):
        hass.states.async_set(s, "off")
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={**OPTIONS, "tts_entity": "tts.test", **extra})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow(hass: HomeAssistant) -> None:
    hass.states.async_set("person.dennis", "home")
    hass.services.async_register("notify", "dennis_alle_geraete", lambda c: None)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"quiet_start": "22:00:00", "quiet_end": "07:00:00"})
    assert result["step_id"] == "persons"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"persons": ["person.dennis"]})
    assert result["step_id"] == "person_notify"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"notify": "notify.dennis_alle_geraete"})
    assert result["step_id"] == "room"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "name": "Wohnzimmer", "speaker": "media_player.studio",
        "presence": ["binary_sensor.wz"], "return_room": True, "add_another": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    opts = result["result"].options
    assert opts["persons"] == [{"person": "person.dennis", "notify": "notify.dennis_alle_geraete"}]
    assert opts["rooms"][0]["return_room"] is True


async def test_options_flow_add_and_remove_room(hass: HomeAssistant) -> None:
    _register_services(hass)
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_room"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "name": "Büro", "speaker": "media_player.buero", "presence": [], "return_room": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert len(entry.options["rooms"]) == 4

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "remove_room"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"room": ["3"]})
    await hass.async_block_till_done()
    assert [r["name"] for r in entry.options["rooms"]] == ["Wohnzimmer", "Küche", "Schlafzimmer"]


async def test_store_and_count_when_nobody_home(hass: HomeAssistant) -> None:
    calls = _register_services(hass)
    entry = await _setup(hass, home=False)
    for _ in range(3):
        await hass.services.async_call(DOMAIN, "send", {"title": "Post", "message": "Briefkasten"}, blocking=True)
    await hass.services.async_call(DOMAIN, "send", {"title": "Waschmaschine", "message": "fertig"}, blocking=True)
    pending = entry.runtime_data.pending
    assert len(pending) == 2
    assert pending[0]["title"] == "Post" and pending[0]["count"] == 3
    assert calls["push"] == [] and calls["tts"] == []
    state = hass.states.get("sensor.presence_notify_stored_notifications")
    assert state is not None and state.state == "2"


async def test_send_when_home_uses_earshot(hass: HomeAssistant) -> None:
    calls = _register_services(hass)
    await _setup(hass, home=True)
    hass.states.async_set("binary_sensor.kueche", "on")
    await hass.services.async_call(DOMAIN, "send", {"title": "T", "message": "M", "ignore_quiet_hours": True}, blocking=True)
    assert len(calls["push"]) == 2
    assert calls["push"][0].data["data"]["priority"] == "high"
    # kitchen detected + bedroom without sensor
    assert calls["tts"][0].data["media_player_entity_id"] == ["media_player.kueche", "media_player.schlaf"]


async def test_send_fallback_all_speakers(hass: HomeAssistant) -> None:
    calls = _register_services(hass)
    entry = await _setup(hass, home=True)
    # nobody detected anywhere -> all speakers
    assert entry.runtime_data.speakers_in_earshot() == [
        "media_player.studio", "media_player.kueche", "media_player.schlaf"]
    # explicit speaker list limits the fallback
    assert entry.runtime_data.speakers_in_earshot(["media_player.studio"]) == ["media_player.studio"]


async def test_arrival_waits_for_motion_then_briefing(hass: HomeAssistant) -> None:
    calls = _register_services(hass, ai_text="Waschmaschine fertig, dreimal Post.")
    entry = await _setup(hass, home=False)
    for msg in ("a", "b"):
        await hass.services.async_call(DOMAIN, "send", {"title": "X", "message": msg}, blocking=True)

    hass.states.async_set("person.dennis", "home")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.presence_notify_waiting_for_return").state == "on"
    assert calls["push"] == []

    hass.states.async_set("binary_sensor.kueche", "on")
    await hass.async_block_till_done()
    assert len(calls["ai"]) == 1
    assert len(calls["push"]) == 1  # only Dennis is home
    assert calls["push"][0].data["message"] == "Waschmaschine fertig, dreimal Post."
    assert calls["tts"][0].data["media_player_entity_id"] == ["media_player.kueche"]
    assert entry.runtime_data.pending == []
    assert hass.states.get("binary_sensor.presence_notify_waiting_for_return").state == "off"


async def test_leaving_again_keeps_messages(hass: HomeAssistant) -> None:
    calls = _register_services(hass)
    entry = await _setup(hass, home=False)
    await hass.services.async_call(DOMAIN, "send", {"title": "X", "message": "a"}, blocking=True)
    hass.states.async_set("person.dennis", "home")
    await hass.async_block_till_done()
    hass.states.async_set("person.dennis", "not_home")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.wz", "on")
    await hass.async_block_till_done()
    assert calls["push"] == []
    assert len(entry.runtime_data.pending) == 1


async def test_single_message_and_ai_fallback(hass: HomeAssistant) -> None:
    calls = _register_services(hass, ai_text="")
    entry = await _setup(hass, home=False)
    await hass.services.async_call(DOMAIN, "send", {"title": "Post", "message": "da"}, blocking=True)
    await hass.services.async_call(DOMAIN, "send", {"title": "Post", "message": "da"}, blocking=True)
    hass.states.async_set("person.christos", "home")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.wz", "on")
    await hass.async_block_till_done()
    assert calls["ai"] == []  # single (merged) item needs no AI
    assert calls["push"][0].data["message"].startswith("da (2")

    # two different items with failing AI -> fallback list
    hass.states.async_set("person.christos", "not_home")
    await hass.async_block_till_done()
    for msg in ("a", "b"):
        await hass.services.async_call(DOMAIN, "send", {"title": "X", "message": msg}, blocking=True)
    await entry.runtime_data.async_deliver(["media_player.studio"])
    assert len(calls["ai"]) == 2  # two attempts

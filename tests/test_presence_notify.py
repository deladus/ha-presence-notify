"""Tests for Presence Notify."""

from __future__ import annotations

import asyncio

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
    state = hass.states.get("sensor.domestic_intelligence_service_stored_notifications")
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


async def test_arrival_push_now_announce_on_motion(hass: HomeAssistant) -> None:
    calls = _register_services(hass, ai_text="Waschmaschine fertig, dreimal Post.")
    entry = await _setup(hass, home=False)
    for msg in ("a", "b"):
        await hass.services.async_call(DOMAIN, "send", {"title": "X", "message": msg}, blocking=True)

    hass.states.async_set("person.dennis", "home")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.domestic_intelligence_service_waiting_for_return").state == "on"
    # push right away (only Dennis is home), no announcement yet
    assert len(calls["push"]) == 1
    assert calls["push"][0].data["message"] == "Waschmaschine fertig, dreimal Post."
    assert calls["tts"] == []

    hass.states.async_set("binary_sensor.kueche", "on")
    await hass.async_block_till_done()
    assert len(calls["ai"]) == 1  # briefing generated once, reused
    assert len(calls["push"]) == 1  # no second push
    assert calls["tts"][0].data["media_player_entity_id"] == ["media_player.kueche"]
    assert "Waschmaschine fertig" in calls["tts"][0].data["message"]
    assert entry.runtime_data.pending == []
    assert hass.states.get("binary_sensor.domestic_intelligence_service_waiting_for_return").state == "off"


async def test_arrival_push_waits_when_option_off(hass: HomeAssistant) -> None:
    calls = _register_services(hass)
    await _setup(hass, home=False, push_on_arrival=False)
    await hass.services.async_call(DOMAIN, "send", {"title": "X", "message": "a"}, blocking=True)
    hass.states.async_set("person.dennis", "home")
    await hass.async_block_till_done()
    assert calls["push"] == []
    hass.states.async_set("binary_sensor.wz", "on")
    await hass.async_block_till_done()
    assert len(calls["push"]) == 1
    assert calls["tts"][0].data["media_player_entity_id"] == ["media_player.studio"]


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
    assert calls["tts"] == []
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


async def test_input_boolean_as_person(hass: HomeAssistant) -> None:
    calls = _register_services(hass)
    hass.states.async_set("input_boolean.test_dennis", "off")
    hass.states.async_set("binary_sensor.wz", "off")
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={
        **OPTIONS, "tts_entity": "tts.test",
        "persons": [{"person": "input_boolean.test_dennis", "notify": "notify.dennis_alle_geraete"}]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(DOMAIN, "send", {"title": "X", "message": "a"}, blocking=True)
    assert len(entry.runtime_data.pending) == 1
    hass.states.async_set("input_boolean.test_dennis", "on")
    await hass.async_block_till_done()
    assert len(calls["push"]) == 1
    hass.states.async_set("binary_sensor.wz", "on")
    await hass.async_block_till_done()
    assert calls["tts"][0].data["media_player_entity_id"] == ["media_player.studio"]


async def test_config_flow_with_house_mode(hass: HomeAssistant) -> None:
    hass.states.async_set("input_select.hausmodus", "Zuhause",
                          {"options": ["Zuhause", "Abwesend", "Urlaub"]})
    hass.states.async_set("person.dennis", "home")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "quiet_start": "22:30:00", "quiet_end": "08:00:00", "home_entity": "input_select.hausmodus"})
    assert result["step_id"] == "home_states"
    schema_field = result["data_schema"].schema["home_states"]
    assert schema_field.config["options"] == ["Zuhause", "Abwesend", "Urlaub"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"home_states": ["Zuhause"]})
    assert result["step_id"] == "persons"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"persons": ["person.dennis"]})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"notify": "notify.x"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "name": "WZ", "presence": [], "return_room": False, "add_another": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].options["home_states"] == ["Zuhause"]


async def test_house_mode_controls_storing_and_arrival(hass: HomeAssistant) -> None:
    calls = _register_services(hass, ai_text="Briefing")
    hass.states.async_set("input_select.hausmodus", "Abwesend")
    # persons are NOT tracked as home (e.g. no phone tracking)
    entry = await _setup(hass, home=False, home_entity="input_select.hausmodus",
                         home_states=["Zuhause"])
    await hass.services.async_call(DOMAIN, "send", {"title": "X", "message": "a"}, blocking=True)
    hass.states.async_set("input_select.hausmodus", "Urlaub")
    await hass.async_block_till_done()
    await hass.services.async_call(DOMAIN, "send", {"title": "X", "message": "b"}, blocking=True)
    assert len(entry.runtime_data.pending) == 2 and calls["push"] == []

    hass.states.async_set("input_select.hausmodus", "Zuhause")
    await hass.async_block_till_done()
    # no person tracked as home -> push goes to all configured persons
    assert len(calls["push"]) == 2
    hass.states.async_set("binary_sensor.wz", "on")
    await hass.async_block_till_done()
    assert calls["tts"][0].data["media_player_entity_id"] == ["media_player.studio"]
    assert entry.runtime_data.pending == []

    # while mode is Zuhause, sends go out immediately (only to tracked persons if any)
    hass.states.async_set("person.dennis", "home")
    await hass.services.async_call(DOMAIN, "send", {"title": "Y", "message": "c", "ignore_quiet_hours": True}, blocking=True)
    assert len(calls["push"]) == 3


def _register_camera(hass: HomeAssistant, written: list[str]):
    async def snapshot(call):
        path = call.data["filename"]
        def _w():
            with open(path, "wb") as f:
                f.write(b"jpg")
        await hass.async_add_executor_job(_w)
        written.append(path)
    hass.services.async_register("camera", "snapshot", snapshot)


async def _setup_media(hass: HomeAssistant, tmp_path, **extra):
    hass.config.media_dirs = {"local": str(tmp_path)}
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    return await _setup(hass, home=False, **extra)


DOORBELL = {"title": "Türklingel", "message": "Es hat geklingelt.",
            "data": {"image": "/api/camera_proxy/camera.door"}}


async def test_doorbell_snapshots_not_counted(hass: HomeAssistant, tmp_path, freezer) -> None:
    _register_services(hass)
    written: list[str] = []
    _register_camera(hass, written)
    entry = await _setup_media(hass, tmp_path)
    await hass.services.async_call(DOMAIN, "send", DOORBELL, blocking=True)
    freezer.tick(10)  # same person rings again within 30 s -> merged
    await hass.services.async_call(DOMAIN, "send", DOORBELL, blocking=True)
    freezer.tick(120)  # later ring -> own entry with own snapshot
    await hass.services.async_call(DOMAIN, "send", DOORBELL, blocking=True)
    pending = entry.runtime_data.pending
    assert len(pending) == 2
    assert pending[0]["count"] == 2 and pending[1]["count"] == 1
    assert len(written) == 2
    assert pending[0]["data"]["image"].startswith("/media/local/presence_notify/")
    assert pending[0]["data"]["image"] != pending[1]["data"]["image"]


async def test_single_image_attached_to_briefing(hass: HomeAssistant, tmp_path) -> None:
    calls = _register_services(hass, ai_text="Briefing")
    _register_camera(hass, [])
    entry = await _setup_media(hass, tmp_path)
    await hass.services.async_call(DOMAIN, "send", DOORBELL, blocking=True)
    await hass.services.async_call(DOMAIN, "send", {"title": "Post", "message": "da"}, blocking=True)
    hass.states.async_set("person.dennis", "home")
    await hass.async_block_till_done()
    assert len(calls["push"]) == 1
    push = calls["push"][0].data
    assert push["message"] == "Briefing"
    assert push["data"]["image"].startswith("/media/local/presence_notify/")
    assert "_snapshot" not in push["data"]


async def test_several_images_grouped_pushes_and_cleanup(hass: HomeAssistant, tmp_path, freezer) -> None:
    calls = _register_services(hass, ai_text="Briefing")
    written: list[str] = []
    _register_camera(hass, written)
    entry = await _setup_media(hass, tmp_path)
    await hass.services.async_call(DOMAIN, "send", DOORBELL, blocking=True)
    freezer.tick(300)
    await hass.services.async_call(DOMAIN, "send", DOORBELL, blocking=True)
    await hass.services.async_call(DOMAIN, "send", {"title": "Post", "message": "da"}, blocking=True)
    hass.states.async_set("person.dennis", "home")
    await hass.async_block_till_done()
    assert len(calls["push"]) == 3  # briefing + 2 doorbell pushes
    assert all(c.data["data"].get("group") == "presence_notify" for c in calls["push"][1:])
    hass.states.async_set("binary_sensor.wz", "on")
    await hass.async_block_till_done()
    import os
    assert all(os.path.exists(p) for p in written)  # kept for a while
    from datetime import timedelta
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    from homeassistant.util import dt as dt_util
    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert not any(os.path.exists(p) for p in written)


async def test_room_selectors_hide_used_entities(hass: HomeAssistant) -> None:
    _register_services(hass)
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_room"})
    schema = result["data_schema"].schema
    assert schema["speaker"].config["exclude_entities"] == [
        "media_player.studio", "media_player.kueche", "media_player.schlaf"]
    assert schema["presence"].config["exclude_entities"] == ["binary_sensor.wz", "binary_sensor.kueche"]
    await hass.config_entries.options.async_configure(result["flow_id"], {"name": "x", "presence": [], "return_room": False})
    await hass.async_block_till_done()

    # editing the kitchen keeps its own entities selectable
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "edit_room"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"room": "1"})
    schema = result["data_schema"].schema
    assert "media_player.kueche" not in schema["speaker"].config["exclude_entities"]
    assert schema["presence"].config["exclude_entities"] == ["binary_sensor.wz"]


async def _ask_task(hass, **data):
    return hass.async_create_task(hass.services.async_call(
        DOMAIN, "ask", {"title": "Trockner", "question": "Starten?", **data},
        blocking=True, return_response=True))


async def test_ask_push_yes(hass: HomeAssistant) -> None:
    calls = _register_services(hass)
    await _setup(hass, home=True)
    task = await _ask_task(hass)
    await asyncio.sleep(0.05)
    pushes = [c for c in calls["push"] if c.data.get("message") == "Starten?"]
    assert len(pushes) == 2  # both at home
    actions = pushes[0].data["data"]["actions"]
    assert [a["title"] for a in actions] == ["Yes", "No"]
    hass.bus.async_fire("mobile_app_notification_action", {"action": actions[0]["action"]})
    result = await task
    assert result["answer"] == "yes"
    # questions cleared + info to the others
    assert any(c.data.get("message") == "clear_notification" for c in calls["push"])


async def test_ask_nobody_home_forward_and_timeout(hass: HomeAssistant) -> None:
    calls = _register_services(hass)
    await _setup(hass, home=False)
    task = await _ask_task(hass, timeout=0.05)
    await asyncio.sleep(0.05)
    first = [c for c in calls["push"] if c.data.get("message") == "Starten?"]
    assert len(first) == 1  # only the first person
    actions = first[0].data["data"]["actions"]
    assert [a["title"] for a in actions] == ["Yes", "No", "Pass on"]
    hass.bus.async_fire("mobile_app_notification_action", {"action": actions[2]["action"]})
    await asyncio.sleep(0.05)
    fwd = [c for c in calls["push"] if "passed on" in c.data.get("message", "")]
    assert len(fwd) == 1
    result = await task
    assert result == {"answer": "timeout", "by": ""}


async def test_ask_via_alexa(hass: HomeAssistant, monkeypatch) -> None:
    calls = _register_services(hass)
    script_calls = []

    async def script_turn_on(call):
        script_calls.append(call)
    hass.services.async_register("script", "turn_on", script_turn_on)
    alexa = []

    async def alexa_notify(call):
        alexa.append(call)
    hass.services.async_register("notify", "alexa_media", alexa_notify)

    await _setup(hass, home=True, ask_alexa=True, ask_alexa_script="script.alexa_frage")
    hass.states.async_set("binary_sensor.kueche", "on")
    import custom_components.presence_notify.manager as m
    monkeypatch.setattr(m.PresenceNotifyManager, "in_quiet_hours", lambda self, now=None: False)
    task = await _ask_task(hass)
    await asyncio.sleep(0.05)
    assert len(script_calls) == 1
    variables = script_calls[0].data["variables"]
    assert variables["alexa_device"] == "media_player.kueche"
    hass.bus.async_fire("alexa_actionable_notification",
                        {"event_id": variables["event_id"], "event_response_type": "ResponseNo"})
    result = await task
    assert result == {"answer": "no", "by": "Alexa"}
    assert alexa and alexa[-1].data["data"]["type"] == "tts"


async def test_config_flow_ask_alexa_step(hass: HomeAssistant) -> None:
    hass.states.async_set("person.dennis", "home")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["description_placeholders"]["docs_url"].endswith("alexa-rueckfragen.md")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "quiet_start": "22:30:00", "quiet_end": "08:00:00", "ask_alexa": True})
    assert result["step_id"] == "ask_alexa"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"ask_alexa_script": "script.x"})
    assert result["step_id"] == "persons"


async def test_pet_mode_motion_before_door_ignored(hass: HomeAssistant) -> None:
    calls = _register_services(hass)
    hass.states.async_set("binary_sensor.haustuer", "off")
    entry = await _setup(hass, home=False, pet_mode=True,
                         entry_doors=["binary_sensor.haustuer"], door_window=10)
    await hass.services.async_call(DOMAIN, "send", {"title": "X", "message": "a"}, blocking=True)
    hass.states.async_set("person.dennis", "home")
    await hass.async_block_till_done()
    w = hass.states.get("binary_sensor.domestic_intelligence_service_waiting_for_return")
    assert w.state == "on" and w.attributes["phase"] == "door"
    # dog / vacuum in the living room before anyone opened the door
    hass.states.async_set("binary_sensor.wz", "on")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.wz", "off")
    await hass.async_block_till_done()
    assert calls["tts"] == [] and len(entry.runtime_data.pending) == 1
    # door opens, then motion -> announcement
    hass.states.async_set("binary_sensor.haustuer", "on")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.domestic_intelligence_service_waiting_for_return").attributes["phase"] == "motion"
    hass.states.async_set("binary_sensor.kueche", "on")
    await hass.async_block_till_done()
    assert calls["tts"][0].data["media_player_entity_id"] == ["media_player.kueche"]
    assert entry.runtime_data.pending == []


async def test_pet_mode_door_before_arrival_and_lock(hass: HomeAssistant, freezer) -> None:
    calls = _register_services(hass)
    hass.states.async_set("lock.haustuer", "locked")
    await _setup(hass, home=False, pet_mode=True, entry_doors=["lock.haustuer"], door_window=10)
    await hass.services.async_call(DOMAIN, "send", {"title": "X", "message": "a"}, blocking=True)
    # unlocked 3 minutes before the arrival is detected
    hass.states.async_set("lock.haustuer", "unlocked")
    await hass.async_block_till_done()
    freezer.tick(180)
    hass.states.async_set("person.dennis", "home")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.domestic_intelligence_service_waiting_for_return").attributes["phase"] == "motion"
    hass.states.async_set("binary_sensor.wz", "on")
    await hass.async_block_till_done()
    assert calls["tts"][0].data["media_player_entity_id"] == ["media_player.studio"]


async def test_pet_mode_door_too_early(hass: HomeAssistant, freezer) -> None:
    calls = _register_services(hass)
    hass.states.async_set("binary_sensor.haustuer", "off")
    await _setup(hass, home=False, pet_mode=True, entry_doors=["binary_sensor.haustuer"], door_window=10)
    await hass.services.async_call(DOMAIN, "send", {"title": "X", "message": "a"}, blocking=True)
    hass.states.async_set("binary_sensor.haustuer", "on")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.haustuer", "off")
    freezer.tick(15 * 60)  # e.g. a house sitter left 15 min ago
    hass.states.async_set("person.dennis", "home")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.wz", "on")
    await hass.async_block_till_done()
    assert calls["tts"] == []


async def test_config_flow_pet_mode_step(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "quiet_start": "22:30:00", "quiet_end": "08:00:00", "pet_mode": True, "ask_alexa": True})
    assert result["step_id"] == "ask_alexa"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"ask_alexa_script": "script.x"})
    assert result["step_id"] == "pet_mode"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "entry_doors": ["binary_sensor.haustuer"], "door_window": 5})
    assert result["step_id"] == "persons"


async def test_hold_time_keeps_room_occupied(hass: HomeAssistant, freezer) -> None:
    """A room with a hold time counts as occupied for that long after 'off'."""
    _register_services(hass)
    rooms = [dict(r) for r in OPTIONS["rooms"]]
    rooms[0]["hold_minutes"] = 5  # Wohnzimmer
    entry = await _setup(hass, home=True, rooms=rooms)
    mgr = entry.runtime_data
    hass.states.async_set("binary_sensor.wz", "on")
    hass.states.async_set("binary_sensor.wz", "off")
    freezer.tick(120)
    assert mgr.speakers_in_earshot() == ["media_player.studio", "media_player.schlaf"]
    freezer.tick(240)  # 6 minutes after 'off'
    assert mgr.speakers_in_earshot() == [
        "media_player.studio", "media_player.kueche", "media_player.schlaf"]  # fallback: all
    # kitchen without hold time: off means off
    hass.states.async_set("binary_sensor.kueche", "on")
    hass.states.async_set("binary_sensor.kueche", "off")
    assert mgr._room_occupied(mgr.rooms[1]) is False


async def test_detected_speaker_prefers_live_then_most_recent(hass: HomeAssistant, freezer) -> None:
    _register_services(hass)
    rooms = [dict(r, hold_minutes=10) for r in OPTIONS["rooms"]]
    entry = await _setup(hass, home=True, rooms=rooms)
    mgr = entry.runtime_data
    hass.states.async_set("binary_sensor.wz", "on")
    hass.states.async_set("binary_sensor.wz", "off")
    freezer.tick(60)
    hass.states.async_set("binary_sensor.kueche", "on")
    hass.states.async_set("binary_sensor.kueche", "off")
    freezer.tick(60)
    # both within hold time: kitchen was more recent
    assert mgr._detected_speaker(None) == "media_player.kueche"
    # someone detected right now wins
    hass.states.async_set("binary_sensor.wz", "on")
    assert mgr._detected_speaker(None) == "media_player.studio"


async def test_remote_counts_as_presence(hass: HomeAssistant) -> None:
    _register_services(hass)
    rooms = [dict(r) for r in OPTIONS["rooms"]]
    rooms[0]["presence"] = ["remote.harmony"]
    hass.states.async_set("remote.harmony", "on")
    entry = await _setup(hass, home=True, rooms=rooms)
    assert entry.runtime_data.speakers_in_earshot() == ["media_player.studio", "media_player.schlaf"]


async def test_priority_android_and_ios(hass: HomeAssistant) -> None:
    calls = _register_services(hass)
    await _setup(hass, home=True)
    await hass.services.async_call(
        DOMAIN, "send",
        {"title": "T", "message": "M", "data": {"push": {"sound": "default"}, "ttl": 60}},
        blocking=True,
    )
    data = calls["push"][0].data["data"]
    assert data["priority"] == "high" and data["importance"] == "high"
    assert data["ttl"] == 60  # caller wins
    assert data["push"] == {"interruption-level": "time-sensitive", "sound": "default"}


async def test_action_buttons_from_form(hass: HomeAssistant) -> None:
    calls = _register_services(hass)
    await _setup(hass, home=True)
    await hass.services.async_call(
        DOMAIN, "send",
        {
            "title": "Garage", "message": "Tor offen",
            "data": {"actions": [{"action": "EXISTING", "title": "Alt"}]},
            "actions": [
                {"title": "Garage schließen"},
                {"title": "Ignorieren", "action": "GARAGE_IGNORE"},
                {"title": "Tür öffnen"},
                {"title": "Kamera", "uri": "/lovelace/kameras"},
            ],
        },
        blocking=True,
    )
    actions = calls["push"][0].data["data"]["actions"]
    assert actions == [
        {"action": "EXISTING", "title": "Alt"},
        {"action": "PN_GARAGE_SCHLIESSEN", "title": "Garage schließen"},
        {"action": "GARAGE_IGNORE", "title": "Ignorieren"},
        {"action": "PN_TUR_OFFNEN", "title": "Tür öffnen"},
        {"action": "URI", "title": "Kamera", "uri": "/lovelace/kameras"},
    ]


async def test_ask_side_pushes_high_priority(hass: HomeAssistant) -> None:
    calls = _register_services(hass)
    await _setup(hass, home=True)
    task = await _ask_task(hass)
    await asyncio.sleep(0.05)
    question = next(c for c in calls["push"] if c.data.get("message") == "Starten?")
    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": question.data["data"]["actions"][0]["action"]}
    )
    await task
    side = [c for c in calls["push"] if c.data.get("message") != "Starten?"]
    assert side and all(c.data["data"]["priority"] == "high" for c in side)
    assert all(c.data["data"]["push"]["interruption-level"] == "time-sensitive" for c in side)

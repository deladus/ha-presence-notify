# Presence Notify

Notifications for Home Assistant that reach whoever is **at home and in earshot**, and don't get lost when nobody is home.

*Deutsche Kurzbeschreibung weiter unten.*

## What it does

One action, `presence_notify.send`, replaces your notification scripts:

- **Someone is home:** push to every person who is home, and announce on the speakers of rooms where someone is detected. Rooms without sensors always get announcements. If nobody is detected anywhere, all speakers are used. No announcements during quiet hours.
- **Nobody is home:** the notification is **stored** (it survives restarts). Identical notifications are merged and counted ("3 times, first at 09:10").
- **Coming home:** Presence Notify waits until motion is detected in a **return room** (e.g. living room or kitchen) rather than using a fixed delay. Then everything is delivered there **as one briefing**, even during quiet hours. With an AI task entity (e.g. Google Gemini), several notifications are summarized into a natural announcement. Without one, a short list is read out.
- If everybody leaves again before reaching a return room, notifications stay stored.

Speakers: Alexa Media Player devices are announced directly via `notify.alexa_media` (announce). Any other `media_player` is announced via `tts.speak` with a TTS engine you choose.

## Installation (HACS)

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/deladus/ha-presence-notify` as type *Integration*.
2. Install **Presence Notify** and restart Home Assistant.
3. *Settings → Devices & services → Add integration → Presence Notify*.

## Setup

1. **General:** quiet hours, optional AI task entity, optional TTS engine.
2. **Persons:** pick persons, then the notify service for each of them (tip: a notify group with all of a person's devices).
3. **Rooms:** name, speaker, presence entities, and whether it is a return room. Presence entities can be any `binary_sensor`, `light`, `switch`, `media_player`, `input_boolean` or `device_tracker`. `on`, `home` or `playing` counts as someone being there, so a TV or a hobby room light can count too.

Everything can be changed later via *Configure*.

## Actions

| Action | Purpose |
|---|---|
| `presence_notify.send` | `title`, `message`, optional `data` (push extras such as `image`, `actions`), `speakers` (limit to these), `ignore_quiet_hours` |
| `presence_notify.deliver_pending` | Deliver stored notifications now as one briefing |
| `presence_notify.clear_pending` | Delete stored notifications |

```yaml
action: presence_notify.send
data:
  title: Washing machine
  message: The laundry is done.
```

## Entities

- `sensor.presence_notify_stored_notifications`: number of stored notifications (attribute `items`)
- `sensor.presence_notify_last_delivery`
- `binary_sensor.presence_notify_waiting_for_return`
- Buttons: *Deliver now*, *Clear stored notifications*
- Event `presence_notify_delivered` (`count`, `speakers`) after each delivery

## Known limitations

- Pets can trigger presence sensors in a return room.
- In a summarized briefing, push extras of individual notifications are dropped; notifications with an `image` are additionally pushed one by one (can be turned off).

---

## Deutsch

Presence Notify schickt Benachrichtigungen an alle, die zu Hause sind (Push), und sagt sie auf den Lautsprechern in Hörweite an. Ist niemand da, werden sie gespeichert. Gleiche Meldungen werden dabei gezählt statt doppelt abgelegt. Nach der Heimkehr wartet die Integration auf die erste Bewegung in einem Heimkehr-Raum und spielt dort **ein** Briefing ab, auf Wunsch per KI zusammengefasst und auch während der Ruhezeit. Einrichtung komplett über die Oberfläche, Oberfläche auf Deutsch und Englisch.

## License

MIT

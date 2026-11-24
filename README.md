<img src="docs/icon.png" alt="" width="96" align="right">

# Domestic Intelligence Service

*Heimischer Nachrichtendienst* · domain `presence_notify`

> [!WARNING]
> **Early beta (0.5.0b1).** This integration is at the very beginning of its development. Expect bugs, breaking changes to settings and actions, and missing features. Please don't rely on it for important notifications yet, and report problems via [Issues](https://github.com/deladus/ha-presence-notify/issues).
>
> **Frühe Beta (0.5.0b1).** Die Integration steht noch ganz am Anfang. Fehler, inkompatible Änderungen an Einstellungen und Aktionen sowie fehlende Funktionen sind zu erwarten. Bitte noch nicht für wichtige Benachrichtigungen verwenden. Probleme gern über [Issues](https://github.com/deladus/ha-presence-notify/issues) melden.

Notifications for Home Assistant that reach whoever is **at home and in earshot**, and don't get lost when nobody is home.

*Deutsche Kurzbeschreibung weiter unten.*

## What it does

One action, `presence_notify.send`, replaces your notification scripts:

- **Someone is home:** push to every person who is home, and announce on the speakers of rooms where someone is detected. Rooms without sensors always get announcements. If nobody is detected anywhere, all speakers are used. No announcements during quiet hours.
- **Nobody is home:** the notification is **stored** (it survives restarts). Identical notifications are merged and counted ("3 times, first at 09:10"). Up to 20 notifications are kept by default (adjustable from 1 to 100 in the general settings). Identical ones take a single slot, notifications with an image take one slot each, and when the store is full the oldest one is dropped.
- **Coming home:** The service waits until motion is detected in a **return room** (e.g. living room or kitchen) rather than using a fixed delay. Then the briefing is announced there, **as one briefing**, even during quiet hours. With an AI task entity (e.g. Google Gemini), several notifications are summarized into a natural announcement. Without one, a short list is read out.
- The push with the briefing goes out **immediately on arrival** (optional: wait for motion instead).
- **Pet mode** (optional): motion only counts after an entry door was opened or unlocked, so pets or a robot vacuum don't trigger the briefing before you are in the room.
- If everybody leaves again before reaching a return room, notifications stay stored.
- **Priorities** (`priority`): *emergency* (all channels, also at night and when nobody is home, repeated until acknowledged), *urgent*, *normal* (default, as described above) and *low*. See [Priorities](#priorities).
- **Remove when done:** send with a `tag`, and `presence_notify.clear` with the same tag removes the push from all phones and from the stored notifications (e.g. "Balcony door open" → door closed).

Speakers: Alexa Media Player devices are announced directly via `notify.alexa_media` (announce). Any other `media_player` is announced via `tts.speak` with a TTS engine you choose.

## Installation

**Home Assistant 2026.11 or newer (Marketplace):**

1. *Settings → Marketplace* → **Add from link** (top right).
2. Enter `deladus/ha-presence-notify`.
3. Install **Domestic Intelligence Service**. While there is only a beta, enable pre-releases for it. Then restart Home Assistant.
4. *Settings → Devices & services → Add integration → Domestic Intelligence Service*.

**Older versions:** add the repository as a custom repository (type *Integration*) in HACS, install and restart.

## Setup

1. **General:** quiet hours, optional **home source**, optional AI task entity, optional TTS engine.
   The home source can be a house mode select (e.g. `Home / Away / Vacation`), an "anyone home" sensor or an alarm panel. You pick which states mean "home". If set, it decides whether notifications are stored. The persons then only define who gets push notifications (if none of them is tracked as home, all of them get it).
2. **Persons:** pick persons, then the notify service for each of them (tip: a notify group with all of a person's devices).
3. **Rooms:** name, speaker, presence entities, whether it is a return room, and an optional **presence cooldown**. Presence entities can be any `binary_sensor`, `light`, `switch`, `media_player`, `remote`, `input_boolean` or `device_tracker`. `on`, `home` or `playing` counts as someone being there, so a TV, a Harmony Hub activity or a hobby room light can count too.
   With a presence cooldown (0 = off), the room still counts as occupied for that many minutes after its presence entities went off – for announcements and questions only, your other automations are not affected. It is added to the sensor's own cooldown (sensor 10 min + 5 min here = 15 min) and cannot shorten it – if your sensor's cooldown already fits, leave it at 0. Useful for motion sensors that only send short pulses and have no adjustable cooldown. Questions go to the room with the most recent detection.

Everything can be changed later via *Configure*.

## Testing with helpers

You can try everything without touching your real setup:

1. Create on/off helpers, e.g. `input_boolean.dis_test_person` (on = at home) and `input_boolean.dis_test_motion`.
2. In the setup, pick the person helper as "person" and the motion helper as presence entity of a return room.
3. Switch the person helper off, send a few notifications, switch it on (push arrives), then switch the motion helper on (announcement plays).

## Actions

| Action | Purpose |
|---|---|
| `presence_notify.send` | `title`, `message`, optional `priority` (`emergency`/`urgent`/`normal`/`low`), `tag`, `store` (normal only), `remove_after` (minutes), `push_to` (`all`/`present`/`absent`), `recipients` (persons), `announcement` (own text for the speakers), `reminder` + `remind_every` (minutes), `data` (push extras such as `image`), `actions` (buttons, see below), `speakers` (limit to these), `ignore_quiet_hours` |
| `presence_notify.clear` | `tag`: remove a tagged notification from all phones and from the stored notifications; ends an emergency or reminder with this tag |
| `presence_notify.deliver_pending` | Deliver stored notifications now as one briefing |
| `presence_notify.clear_pending` | Delete stored notifications |
| `presence_notify.ask` | Question by push (optionally also by Alexa): yes/no, a choice, a number or free text (`answer_type`, `options`, `text_answer`). Returns `answer` (`yes`/`no`/`answered`/`timeout`), `value` and `by`. See [Questions](#questions-presence_notifyask) |

```yaml
action: presence_notify.send
data:
  title: Washing machine
  message: The laundry is done.
```

### Action buttons

`actions` lets you add buttons in the action editor, no YAML needed: one entry per button with a **title**, an optional **ID** and an optional **link**.

- Without a link, pressing the button fires the event `mobile_app_notification_action` with the ID. Leave the ID empty to have it generated from the title (`Close garage` → `PN_CLOSE_GARAGE`). React to it with an automation using an event trigger.
- With a link (e.g. `/lovelace/cameras` or a web address), the button opens it.

```yaml
action: presence_notify.send
data:
  title: Garage
  message: The garage door is still open.
  actions:
    - title: Close garage
    - title: Camera
      uri: /lovelace/cameras
```

### Priorities

| Priority | Push | Announcement | Nobody home |
|---|---|---|---|
| `emergency` | everyone, Android alarm channel (`channel: alarm_stream`), iOS critical alert, button **Seen** | **all** speakers, emphasized, also during quiet hours, volume raised per room | push to everyone + announcement anyway |
| `urgent` | everyone, high priority (iOS `time-sensitive`) | in earshot, title emphasized on Alexa, **not** during quiet hours | push to everyone, not stored |
| `normal` (default) | persons at home | in earshot, not during quiet hours | stored, delivered on arrival |
| `low` | persons at home, normal priority (iOS `passive`) | none | dropped |

**Emergency** (e.g. a water leak):

- **Volume:** before the announcement each speaker is turned up by the room's *Emergency volume boost* (Alexa scale 0–10, default 3, never above 10) and set back afterwards – unless someone changed the volume in the meantime. Speakers differ a lot (a large one may be very loud at 7, a small one still moderate at 10), so set the boost per room. Alexa speakers are turned up and down with a relative voice command ("volume up by 3"), because Alexa Media only reports the volume while a device is playing – so it works whatever the current volume is. If the volume is unknown and the speaker hits 10, it may end up slightly quieter than before. Other speakers must report their volume to be raised.
- **Repetition:** push and announcement are repeated every *X minutes* up to a maximum number of repetitions (general settings, default every 2 minutes, 5 times).
- **Acknowledge** – any of these ends it: the **Seen** button in the push (removes the push for everyone, the others get "X acknowledged the emergency"), answering **yes** to Alexa's "Did you hear that?" (only with Alexa questions enabled, asked in the room where someone is detected), the button entity **Acknowledge emergency** (dashboard, Alexa routine), or `presence_notify.clear` with the same tag (e.g. the leak sensor is dry again).
- If someone answers Alexa's question after the emergency was already acknowledged or solved, Alexa says so ("… already acknowledged by Dennis", "the problem is already solved"). "No" counts as no answer.
- iOS critical alerts need the critical alerts permission in the Companion app.

```yaml
action: presence_notify.send
data:
  title: Water leak
  message: The leak sensor in the basement reports water.
  priority: emergency
  tag: leak_basement
```

With **Send push notifications with high priority** (general settings, on by default) *normal* pushes get `priority: high`, `ttl: 0` and `importance: high` for Android, and `interruption-level: time-sensitive` for iOS. Values you pass in `data` win; the iOS `push` block is merged.

### Remove a notification when it is done

```yaml
# balcony door opened
action: presence_notify.send
data:
  title: Balcony door
  message: The balcony door is open.
  tag: balcony_door
---
# balcony door closed again
action: presence_notify.clear
data:
  tag: balcony_door
```

A new notification with the same tag replaces the stored one (identical ones are still counted).

### Only relevant right now: `store` and `remove_after`

- **`store: false`** – *only for priority normal.* When nobody is home, the notification is dropped instead of stored, so it does not come with the briefing after coming home. Useful for things that only matter at that moment, e.g. a dryer recommendation. Urgent, emergency and low notifications are never stored anyway, so the field has no effect there.
- **`remove_after: 15`** – after 15 minutes the push is removed from all phones and the notification from the stored notifications. Sending again with the same tag starts the time again; without a tag one is generated. It survives a restart. Not for emergencies – they end only when acknowledged, cleared or after the last repetition.

```yaml
action: presence_notify.send
data:
  title: Dryer
  message: Plenty of sun right now – start the dryer?
  store: false
  remove_after: 15
```

### Who gets the push: `push_to` and `recipients`

- **`push_to`** – `all`, `present` (only persons at home) or `absent` (only persons away). Without it, the priority decides as before (urgent: everyone, normal/low: persons at home).
- **`recipients`** – only these persons (person entities set up in the integration). Combined with `push_to`, e.g. only Dennis and only if he is away.
- Announcements are not affected – they still depend on the rooms. Emergencies ignore both fields and always reach everyone.
- Normal priority with `push_to: absent` or `all` while nobody is home: everyone gets the push; it is stored for the briefing only if `store` is on.
- Not part of the briefing: stored notifications are delivered to whoever comes home, regardless of these fields.

### Separate text for the speakers: `announcement`

Speakers say `announcement` instead of "Title: Message" – e.g. short for the speaker, detailed in the push. With urgent and emergency the whole text is emphasized on Alexa. The briefing of stored notifications keeps using title and message.

Example doorbell – announcement for those at home, push for those away, later update of the same push without a new announcement:

```yaml
action: presence_notify.send
data:
  title: Front door
  message: Someone is at the door – analysis running …
  announcement: Someone rang the doorbell
  push_to: absent
  store: false
  tag: doorbell
---
# update: same tag, no speakers = no announcement, Android does not ring again
action: presence_notify.send
data:
  title: Front door
  message: The parcel carrier is at the door.
  push_to: absent
  store: false
  tag: doorbell
  speakers: []
  data:
    alert_once: true
```

### Reminders: `reminder` and `remind_every`

With `reminder: true` the push gets two buttons, **Done** and **Remind me later**:

- **Remind me later** removes the push from all phones and sends the reminder again after `remind_every` minutes (default 60) – push and announcement, with a counter ("The laundry is done (snoozed 2 times)").
- If nobody is home when it is due, it is stored and comes with the briefing after coming home.
- **Done** – pressed by anyone – ends the reminder for everyone. `presence_notify.clear` with the same tag ends it as well, e.g. when the washing machine door is opened.
- A reminder is always handled as priority **normal** (quiet hours, storing, `push_to` and `recipients` work as usual).

```yaml
action: presence_notify.send
data:
  title: Washing machine
  message: The laundry is done.
  reminder: true
  remind_every: 60
  tag: laundry
```

## Questions: `presence_notify.ask`

The question goes by push to everyone at home (nobody home: to the first person, with a button to pass it on) and, with Alexa questions enabled, to the speaker in the room with the most recent detection. The first answer wins; the other pushes are removed and the others are told who answered.

| `answer_type` | Push | Alexa | `value` |
|---|---|---|---|
| `yes_no` (default) | buttons Yes / No | yes / no | `yes` / `no` |
| `choice` + `options` | one button per option (up to three); more options → text input, options listed in the message | the spoken answer is matched to an option | the option |
| `number` | text input | spoken number | the number |
| `text` | text input | what was said | the text |

- Typed or spoken answers for `choice` are matched to the closest option (spelling, umlauts, partial words); a number picks the option at that position (1 = first).
- An answer that does not fit (no number, no option): the push asks again with a hint, Alexa asks once more.
- `text_answer`: what Alexa says after answering her question, `{value}` is replaced (default "All right: {value}."). For yes/no use `text_yes` / `text_no` as before.
- Response: `answer` is `yes`/`no` (yes/no), `answered` (other types) or `timeout`; `value` holds the answer; `by` is the person or `Alexa`.
- Text input in the push needs the Home Assistant Companion app (Android and iOS). With the Alexa Actionable Notifications skill, numbers and free text sometimes arrive as a different response type – the integration accepts both.

```yaml
action: presence_notify.ask
data:
  title: Gaming
  question: Projector or TV?
  answer_type: choice
  options: [Projector, TV]
  text_answer: All right, starting on the {value}.
response_variable: reply
# reply.value == "Projector" / "TV", reply.answer == "timeout" without answer
```

## Alexa questions (experts only)

`presence_notify.ask` always works by push. With the switch **Alexa questions (experts only)** in the general settings, Alexa also asks in the room where someone is detected. This needs the [Alexa Actionable Notifications](https://github.com/keatontaylor/alexa-actions) skill and its script – see the **[guide](docs/alexa-rueckfragen.md)** (German/English).

## Entities

- Entity IDs follow your language (e.g. `sensor.heimischer_nachrichtendienst_…` in German)
- `sensor.domestic_intelligence_service_stored_notifications`: number of stored notifications (attribute `items`)
- `sensor.domestic_intelligence_service_last_delivery`
- `binary_sensor.domestic_intelligence_service_waiting_for_return`
- Buttons: *Deliver now*, *Clear stored notifications*, *Acknowledge emergency*
- Event `presence_notify_delivered` (`count`, `speakers`) after each delivery

## Known limitations

- Pets can trigger presence sensors in a return room – use pet mode. A pet running ahead of you right after the door opens can still trigger it.
- Camera images: when a notification with `image: /api/camera_proxy/camera.x` is stored, a snapshot is saved to the media folder (`/media/presence_notify`, requires login) so it shows the right moment. One picture is attached to the briefing push; several are pushed one by one, grouped. Snapshots are deleted 15 minutes after delivery.
- Other push extras (e.g. actions) of individual notifications are dropped in a summarized briefing.

---

## Deutsch

Der Heimische Nachrichtendienst schickt Benachrichtigungen an alle, die zu Hause sind (Push), und sagt sie auf den Lautsprechern in Hörweite an. Ist niemand da, werden sie gespeichert. Gleiche Meldungen werden dabei gezählt statt doppelt abgelegt. Standardmäßig bleiben bis zu 20 Meldungen erhalten (einstellbar von 1 bis 100); gleiche Meldungen belegen nur einen Platz, Meldungen mit Bild je einen eigenen, und bei vollem Speicher fällt die älteste weg. Nach der Heimkehr wartet die Integration auf die erste Bewegung in einem Heimkehr-Raum und spielt dort **ein** Briefing ab (der Push kommt schon bei der Ankunft), auf Wunsch per KI zusammengefasst und auch während der Ruhezeit. Einrichtung komplett über die Oberfläche, Oberfläche auf Deutsch und Englisch.

**Prioritäten** (`priority`): *Notfall* kommt immer – Push an alle (Android-Alarmkanal, iOS kritisch), Ansage auf allen Lautsprechern auch nachts und ohne Anwesenheit, vorher pro Raum um einstellbar viele Stufen lauter (danach zurück), Wiederholung bis jemand quittiert (Knopf „Gesehen“, Alexa-Frage „Hast du das gehört?“, Schaltfläche „Notfall quittieren“ oder `presence_notify.clear`). *Dringend*: sofort Push an alle, betonte Ansage, aber nicht in der Ruhezeit. *Normal*: wie bisher. *Niedrig*: nur Push und nur wenn jemand zu Hause ist, sonst verworfen.

**Nur im Moment wichtig:** `store: false` (gilt **nur für die Priorität Normal**) verwirft eine Nachricht, wenn niemand zu Hause ist, statt sie fürs Briefing zu speichern – z. B. für eine Trocknerempfehlung. `remove_after: 15` entfernt Push und gespeicherte Nachricht nach 15 Minuten automatisch (nicht bei Notfällen).

**Wer den Push bekommt:** `push_to` (`all` = alle, `present` = nur Anwesende, `absent` = nur Abwesende; ohne Angabe wie bisher je nach Priorität) und `recipients` (nur diese Personen, kombinierbar). Ansagen richten sich weiter nach den Räumen; Notfälle gehen immer an alle. Beispiel Klingel: Ansage für die Anwesenden, Push nur für die Abwesenden.

**Eigener Ansagetext:** `announcement` wird statt „Titel: Nachricht“ angesagt – z. B. kurz „Es hat geklingelt“, im Push ausführlicher. Das Briefing gespeicherter Nachrichten nutzt weiter Titel und Nachricht.

**Erinnerungen:** Mit `reminder: true` bekommt der Push die Knöpfe „Erledigt“ und „Später erinnern“. „Später erinnern“ nimmt den Push von allen Handys und sendet die Erinnerung nach `remind_every` Minuten (Standard 60) erneut – Push und Ansage, mit Zähler („2-mal verschoben“). Ist dann niemand zu Hause, wird sie gespeichert und kommt mit dem Briefing. „Erledigt“ (von irgendwem) oder `presence_notify.clear` mit der Kennung beendet sie für alle. Erinnerungen laufen immer als Priorität Normal.

**Fragen (`presence_notify.ask`):** Ja/Nein (Standard), Auswahl (`answer_type: choice` mit `options`, im Push als Knöpfe, bei mehr als drei als Texteingabe), Zahl oder freier Text (Texteingabe im Push). Alexa fragt auf Wunsch im Raum mit der jüngsten Erkennung und ordnet die gesprochene Antwort zu. Passt eine Antwort nicht, wird mit Hinweis nachgefragt. Rückgabe: `answer` (`yes`/`no`/`answered`/`timeout`), `value` (die Antwort) und `by`. `text_answer` legt fest, was Alexa danach sagt (`{value}` = Antwort).

**Automatisch entfernen:** Mit `tag` senden, später `presence_notify.clear` mit derselben Kennung – der Push verschwindet von allen Handys und die Meldung aus dem Speicher (z. B. „Balkontür offen“ → Tür zu).

## License

MIT

*Developed with AI assistance. / Mit KI-Unterstützung entwickelt.*

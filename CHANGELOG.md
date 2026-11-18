# Changelog

## 0.3.2b1 (beta)
- Rooms: the hold time field is now called "Presence cooldown (minutes)" and its description explains that 0 means off and that it adds to the sensor's own cooldown
- General settings: "Maximum stored notifications" now explains the range (1–100, default 20), that identical notifications share one slot, that notifications with an image take one slot each and that the oldest is dropped when the store is full

## 0.3.1b1 (beta)
- Rooms: optional presence cooldown – a room still counts as occupied for X minutes after its presence entities went off (announcements and questions only). Questions go to the room with the most recent detection
- Rooms: `remote` entities (e.g. Harmony Hub) can be used as presence entities
- `presence_notify.send`: new field `actions` to add push buttons in the editor (title, optional ID, optional link) without writing YAML
- Fix iOS: high priority now uses `interruption-level: time-sensitive` (the previous key had no effect on iOS); a custom `push` block in `data` is merged instead of replacing it
- Fix: removing an answered question from the phones and the "X decided" info are now also sent with high priority, so they are not delayed on Android

## 0.3.0b1 (beta)
- New action `presence_notify.ask`: yes/no question by push with buttons to everyone at home (or the first person with a "Pass on" button when nobody is home). First answer wins, returns `answer` and `by`
- Pet mode (optional): after coming home, motion in a return room only counts once an entry door was opened or a lock unlocked (a door opened up to X minutes before the arrival counts too) – pets or a robot vacuum no longer trigger the briefing early
- Optional Alexa questions (experts only): switch in the general settings plus script selection, guide in `docs/alexa-rueckfragen.md`

## 0.2.0b2 (beta)
- Notifications with a camera image (e.g. doorbell) get their own snapshot when stored, so the picture shows the right moment
- They are not merged/counted, except an identical one within 30 s (configurable): the same person ringing twice
- One picture: attached to the briefing push (one push only). Several: one grouped push per picture
- Snapshots are stored in the media folder (needs login) and deleted 15 minutes after delivery
- Push service list hides Alexa Media announce services
- Room setup hides speakers and presence entities already used by another room

## 0.2.0b1 (beta)
- Renamed to Domestic Intelligence Service / Heimischer Nachrichtendienst
- Briefing push is sent right away on arrival (option), announcement waits for motion
- On/off helpers and device trackers can be used as persons (for testing)
- Own icon (shown in Home Assistant 2026.3+)
- Optional home source (house mode select, anyone-home sensor, alarm panel) with selectable "home" states

## 0.1.0
- First internal version

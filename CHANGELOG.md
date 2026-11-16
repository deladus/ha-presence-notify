# Changelog

## 0.3.0b1 (beta)
- New action `presence_notify.ask`: yes/no question by push with buttons to everyone at home (or the first person with a "Pass on" button when nobody is home). First answer wins, returns `answer` and `by`
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

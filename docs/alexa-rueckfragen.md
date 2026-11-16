# Alexa-Rückfragen / Alexa questions

> [!CAUTION]
> **Nur für Experten.** Diese Funktion ist optional und braucht Vorarbeit außerhalb der Integration: einen eigenen Alexa-Skill in der Amazon-Entwicklerkonsole sowie Helfer und ein Skript in Home Assistant. Ohne diese Vorarbeit bleibt der Schalter wirkungslos – Rückfragen kommen dann nur als Push mit Knöpfen.
>
> **Experts only.** This feature is optional and needs work outside the integration: your own Alexa skill in the Amazon developer console plus a helper and a script in Home Assistant. Without it the switch has no effect – questions are sent as push notifications with buttons only.

## Was die Funktion macht

Die Aktion `presence_notify.ask` stellt eine Ja/Nein-Frage:

- **Push mit Knöpfen** „Ja“ / „Nein“ an alle, die zu Hause sind. Ist niemand da, wird die **erste eingetragene Person** gefragt, mit dem zusätzlichen Knopf „Weitergeben“ an die anderen.
- **Alexa fragt** (nur mit eingeschaltetem Schalter) auf dem Lautsprecher des Raums, in dem gerade jemand erkannt wird – nicht während der Ruhezeit und nicht, wenn niemand zu Hause ist.
- **Die erste Antwort gewinnt.** Die übrigen Pushes werden entfernt, Alexa bestätigt ihre eigene Frage kurz. Wurden mehrere gefragt, erfahren die anderen, wer entschieden hat.
- Rückgabe für die Automation: `answer` (`yes`, `no` oder `timeout`) und `by` (Name, `Alexa` oder leer).

```yaml
- action: presence_notify.ask
  data:
    title: Trockner
    question: Der Trockner ist bereit. Soll ich starten?
    timeout: 15
  response_variable: rueckfrage
- if:
    - condition: template
      value_template: "{{ rueckfrage.answer == 'yes' }}"
  then:
    - action: switch.turn_on
      target:
        entity_id: switch.trockner
```

## Voraussetzungen für den Alexa-Teil

Die Integration nutzt das verbreitete Projekt **Alexa Actionable Notifications**. Dessen Anleitung beschreibt die Einrichtung Schritt für Schritt:

1. Alexa-Skill in der Amazon-Entwicklerkonsole anlegen (Code aus dem Projekt, Verknüpfung mit Home Assistant).
2. In Home Assistant den Helfer `input_text.alexa_actionable_notification` anlegen.
3. Das Skript `script.activate_alexa_actionable_notification` anlegen.
4. Prüfen: Das Skript ausführen – Alexa stellt die Frage, und bei einer Antwort erscheint das Ereignis `alexa_actionable_notification` in den Entwicklerwerkzeugen.

Projekt und Anleitung: <https://github.com/keatontaylor/alexa-actions>

### Anforderungen an das Skript

Der Heimische Nachrichtendienst startet das in den Einstellungen gewählte Skript mit diesen Variablen:

| Variable | Inhalt |
|---|---|
| `text` | die Frage |
| `event_id` | eindeutige Kennung der Frage |
| `alexa_device` | der Lautsprecher, z. B. `media_player.echo_kueche` |
| `suppress_confirmation` | `"true"` |

Ein eigenes Skript (z. B. ein Wrapper) funktioniert ebenso, solange es diese Variablen annimmt und Alexa die Antwort als Ereignis `alexa_actionable_notification` mit `event_id` und `event_response_type` (`ResponseYes` / `ResponseNo`) meldet.

## Einschalten

*Einstellungen → Geräte & Dienste → Heimischer Nachrichtendienst → Konfigurieren → Allgemeine Einstellungen* → **Alexa-Rückfragen (nur für Experten)** einschalten → im nächsten Schritt das Skript wählen.

---

## English summary

`presence_notify.ask` asks a yes/no question by push (with buttons) to everyone at home – or to the first configured person (with a "Pass on" button) if nobody is home – and, when the switch is on, by Alexa in the room where someone is detected. The first answer wins; the response contains `answer` (`yes`/`no`/`timeout`) and `by`. The Alexa part requires the [Alexa Actionable Notifications](https://github.com/keatontaylor/alexa-actions) skill, the helper `input_text.alexa_actionable_notification` and a script that accepts `text`, `event_id`, `alexa_device` and `suppress_confirmation`. Recommended for experts only.

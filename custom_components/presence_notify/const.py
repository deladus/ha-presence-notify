"""Constants for Domestic Intelligence Service."""

from __future__ import annotations

DOMAIN = "presence_notify"
PLATFORMS = ["sensor", "binary_sensor", "button"]

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.pending"

# Options keys
CONF_PERSONS = "persons"
CONF_PERSON = "person"
CONF_NOTIFY = "notify"
CONF_ROOMS = "rooms"
CONF_ROOM_NAME = "name"
CONF_SPEAKER = "speaker"
CONF_PRESENCE = "presence"
CONF_RETURN_ROOM = "return_room"
CONF_HOLD = "hold_minutes"
DEFAULT_HOLD = 0
CONF_EMERGENCY_STEP = "emergency_volume_step"
DEFAULT_EMERGENCY_STEP = 3
CONF_EMERGENCY_INTERVAL = "emergency_repeat_minutes"
DEFAULT_EMERGENCY_INTERVAL = 2
CONF_EMERGENCY_REPEATS = "emergency_repeat_max"
DEFAULT_EMERGENCY_REPEATS = 5
CONF_QUIET_START = "quiet_start"
CONF_QUIET_END = "quiet_end"
CONF_AI_TASK = "ai_task_entity"
CONF_TTS_ENTITY = "tts_entity"
CONF_MAX_PENDING = "max_pending"
CONF_HIGH_PRIORITY = "high_priority_push"
CONF_IMAGES_SEPARATE = "push_images_separately"
CONF_PUSH_ON_ARRIVAL = "push_on_arrival"
CONF_HOME_ENTITY = "home_entity"
CONF_IMAGE_MERGE_SECONDS = "image_merge_seconds"
CONF_ASK_ALEXA = "ask_alexa"
CONF_PET_MODE = "pet_mode"
CONF_ENTRY_DOORS = "entry_doors"
CONF_DOOR_WINDOW = "door_window"
DEFAULT_DOOR_WINDOW = 10
CONF_ASK_SCRIPT = "ask_alexa_script"
DOCS_ALEXA_URL = "https://github.com/deladus/ha-presence-notify/blob/main/docs/alexa-rueckfragen.md"
DEFAULT_IMAGE_MERGE_SECONDS = 30
CONF_HOME_STATES = "home_states"
HOME_ENTITY_DOMAINS = ["input_select", "select", "input_boolean", "binary_sensor", "sensor", "alarm_control_panel", "group"]

DEFAULT_QUIET_START = "22:30:00"
DEFAULT_QUIET_END = "08:00:00"
DEFAULT_MAX_PENDING = 20

# Person can also be a device_tracker or an input_boolean (on = home, handy for testing)
PERSON_DOMAINS = ["person", "device_tracker", "input_boolean", "binary_sensor"]
PERSON_HOME_STATES = {"home", "on"}

# States that count as "someone is here" for presence entities of any domain
PRESENCE_ON_STATES = {"on", "home", "playing", "detected", "occupied"}

# Service names / fields
SERVICE_SEND = "send"
SERVICE_DELIVER = "deliver_pending"
SERVICE_CLEAR = "clear_pending"
SERVICE_ASK = "ask"
SERVICE_REMOVE = "clear"
ATTR_QUESTION = "question"
ATTR_TIMEOUT = "timeout"
ATTR_TEXT_YES = "text_yes"
ATTR_TEXT_NO = "text_no"
ATTR_TITLE = "title"
ATTR_MESSAGE = "message"
ATTR_DATA = "data"
ATTR_SPEAKERS = "speakers"
ATTR_IGNORE_QUIET = "ignore_quiet_hours"
ATTR_ACTIONS = "actions"
ATTR_PRIORITY = "priority"
ATTR_TAG = "tag"
ATTR_STORE = "store"
ATTR_REMOVE_AFTER = "remove_after"
ATTR_PUSH_TO = "push_to"
ATTR_RECIPIENTS = "recipients"
ATTR_ANNOUNCEMENT = "announcement"

PRIORITY_EMERGENCY = "emergency"
PRIORITY_URGENT = "urgent"
PRIORITY_NORMAL = "normal"
PRIORITY_LOW = "low"
PRIORITIES = [PRIORITY_EMERGENCY, PRIORITY_URGENT, PRIORITY_NORMAL, PRIORITY_LOW]
ACTION_PREFIX = "PN_"

# Who gets the push (send): default depends on the priority
PUSH_TO_ALL = "all"
PUSH_TO_PRESENT = "present"
PUSH_TO_ABSENT = "absent"
PUSH_TO_OPTIONS = [PUSH_TO_ALL, PUSH_TO_PRESENT, PUSH_TO_ABSENT]

EVENT_DELIVERED = f"{DOMAIN}_delivered"
SIGNAL_UPDATE = f"{DOMAIN}_update"

# Android: priority/ttl (FCM high priority, no batching), importance (channel)
# iOS: interruption-level time-sensitive (breaks through Focus modes)
HIGH_PRIORITY_DATA = {
    "priority": "high",
    "ttl": 0,
    "importance": "high",
    "push": {"interruption-level": "time-sensitive"},
}

# Emergency: Android alarm channel (plays like an alarm, breaks through Do Not
# Disturb), iOS critical alert (needs the critical alerts permission in the app)
EMERGENCY_DATA = {
    "priority": "high",
    "ttl": 0,
    "importance": "high",
    "channel": "alarm_stream",
    "push": {
        "interruption-level": "critical",
        "sound": {"name": "default", "critical": 1, "volume": 1.0},
    },
}

# Low: normal Android priority, iOS passive (no sound, no screen wake-up)
LOW_PRIORITY_DATA = {"push": {"interruption-level": "passive"}}

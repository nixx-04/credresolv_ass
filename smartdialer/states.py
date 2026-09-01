class AgentState:
    OFFLINE = "OFFLINE"
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    DIALING = "DIALING"
    CONNECTED = "CONNECTED"
    WRAP_UP = "WRAP_UP"
    PAUSED = "PAUSED"


class BorrowerState:
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    CALLED = "CALLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CallState:
    QUEUED = "QUEUED"
    RESERVED = "RESERVED"
    INITIATED = "INITIATED"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    CONNECTED = "CONNECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ACTIVE_CALL_STATES = [
    CallState.RESERVED,
    CallState.INITIATED,
    CallState.RINGING,
    CallState.ANSWERED,
    CallState.CONNECTED,
]

CONNECTED_CALL_STATES = [
    CallState.ANSWERED,
    CallState.CONNECTED,
]

VALID_CALL_TRANSITIONS = {
    CallState.QUEUED: set(),
    CallState.RESERVED: {CallState.QUEUED},
    CallState.INITIATED: {CallState.RESERVED},
    CallState.RINGING: {CallState.INITIATED},
    CallState.ANSWERED: {
        CallState.RINGING,
        CallState.INITIATED,
    },
    CallState.CONNECTED: {
        CallState.ANSWERED,
        CallState.RINGING,
        CallState.INITIATED,
    },
    CallState.COMPLETED: {
        CallState.CONNECTED,
        CallState.ANSWERED,
        CallState.RINGING,
        CallState.INITIATED,
    },
    CallState.FAILED: {
        CallState.RESERVED,
        CallState.INITIATED,
        CallState.RINGING,
        CallState.ANSWERED,
        CallState.CONNECTED,
    },
    CallState.CANCELLED: {
        CallState.QUEUED,
        CallState.RESERVED,
        CallState.INITIATED,
        CallState.RINGING,
    },
}
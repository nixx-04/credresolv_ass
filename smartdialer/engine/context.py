from dataclasses import dataclass


@dataclass
class DialerContext:
    campaign_id: str
    mode: str

    available_agents: int = 0
    active_calls: int = 0
    active_agent_calls: int = 0
    active_connections: int = 0
    ringing_calls: int = 0
    queued_borrowers: int = 0

    answer_rate: float = 0.2
    avg_talk_time_sec: int = 120
    avg_wrap_time_sec: int = 10
    overdial_factor: float = 1.0

    provider_error_rate: float = 0.0
    recent_abandon_rate: float = 0.0
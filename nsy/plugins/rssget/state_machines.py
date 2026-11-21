"""Pure RSS business decisions; persistence, fetching and sending stay at the edges."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


@dataclass(frozen=True, slots=True)
class SourceHealthTransition:
    available: bool
    observed_at: datetime
    retry_at: datetime | None
    changed: bool
    enqueue_notice: bool


def source_health_transition(previous: bool | None, available: bool, now: datetime,
                             *, notify: bool, cooldown: float = 0) -> SourceHealthTransition:
    return SourceHealthTransition(
        available=available,
        observed_at=now,
        retry_at=now + timedelta(seconds=cooldown) if not available and cooldown else None,
        changed=previous != available if previous is not None else not available,
        enqueue_notice=notify,
    )


class SourceOutcome(Enum):
    AVAILABLE = "available"
    ACCOUNT_FAILURE = "account_failure"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"


class SourceObservation(Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class SourceRoundStatus(Enum):
    UNOBSERVED = "unobserved"
    AVAILABLE = "available"
    FAILING = "failing"
    PAUSED = "paused"


@dataclass(frozen=True, slots=True)
class SourceRound:
    status: SourceRoundStatus = SourceRoundStatus.UNOBSERVED
    consecutive_failures: int = 0
    retry_after: float = 0

    @property
    def paused(self) -> bool:
        return self.status is SourceRoundStatus.PAUSED


@dataclass(frozen=True, slots=True)
class SourceRoundTransition:
    state: SourceRound
    observation: SourceObservation | None = None
    cooldown: float = 0


def source_round_transition(state: SourceRound, outcome: SourceOutcome, *, threshold: int,
                            cooldown: float, retry_after: float = 0) -> SourceRoundTransition:
    if state.paused:
        return SourceRoundTransition(state)
    longest = max(state.retry_after, retry_after)
    if outcome is SourceOutcome.AVAILABLE:
        observation = None if state.status is SourceRoundStatus.AVAILABLE else SourceObservation.AVAILABLE
        return SourceRoundTransition(SourceRound(SourceRoundStatus.AVAILABLE, 0, longest), observation)
    if outcome is SourceOutcome.ACCOUNT_FAILURE:
        return SourceRoundTransition(SourceRound(state.status, 0, longest))
    failures = state.consecutive_failures + 1
    if outcome is SourceOutcome.RATE_LIMITED or failures >= threshold:
        return SourceRoundTransition(
            SourceRound(SourceRoundStatus.PAUSED, failures, longest),
            SourceObservation.UNAVAILABLE, max(cooldown, longest),
        )
    status = SourceRoundStatus.AVAILABLE if state.status is SourceRoundStatus.AVAILABLE else SourceRoundStatus.FAILING
    return SourceRoundTransition(SourceRound(status, failures, longest))


def finish_source_round(state: SourceRound, *, cooldown: float) -> SourceRoundTransition:
    if state.status is SourceRoundStatus.FAILING:
        return SourceRoundTransition(state, SourceObservation.UNAVAILABLE, max(cooldown, state.retry_after))
    return SourceRoundTransition(state)


class WriteOutcome(Enum):
    COMMITTED = "committed"
    SUPERSEDED = "superseded"
    RETRY_PENDING = "retry_pending"

    @property
    def success(self) -> bool:
        return self is not WriteOutcome.RETRY_PENDING

    def __bool__(self) -> bool:
        return self.success


@dataclass(frozen=True, slots=True)
class RetryDecision:
    attempts: int
    next_retry_at: datetime


def ingest_retry(attempts: int, now: datetime) -> RetryDecision:
    """Keep retrying durable work, with bounded delay and exponent even after many failures."""
    delay = min(3600, 30 * 2 ** min(attempts, 7))
    return RetryDecision(attempts + 1, now + timedelta(seconds=delay))


class DeliveryDecision(Enum):
    SEND = "send"
    FILTERED = "filtered"
    ALREADY_DELIVERED = "already_delivered"
    STARTUP = "startup"
    WINDOW = "window"


def delivery_decision(*, already_delivered: bool = False, startup_baseline: bool = False,
                      in_window: bool = True, is_self_repost: bool = False,
                      is_repost: bool = False, allow_self_reposts: bool = True,
                      allow_reposts: bool = True) -> DeliveryDecision:
    if already_delivered:
        return DeliveryDecision.ALREADY_DELIVERED
    if startup_baseline:
        return DeliveryDecision.STARTUP
    if not in_window:
        return DeliveryDecision.WINDOW
    allowed = allow_self_reposts if is_self_repost else allow_reposts if is_repost else True
    return DeliveryDecision.SEND if allowed else DeliveryDecision.FILTERED

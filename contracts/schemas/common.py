"""Shared enums and type aliases for the TfL contracts."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class TransportMode(StrEnum):
    """TfL transport modes served by this platform."""

    TUBE = "tube"
    ELIZABETH_LINE = "elizabeth-line"
    OVERGROUND = "overground"
    DLR = "dlr"
    BUS = "bus"
    NATIONAL_RAIL = "national-rail"
    RIVER_BUS = "river-bus"
    CABLE_CAR = "cable-car"
    TRAM = "tram"


class StatusSeverity(IntEnum):
    """TfL line status severity codes (0 = worst, 10 = good service, 20 = closed)."""

    SPECIAL_SERVICE = 0
    CLOSED = 1
    SUSPENDED = 2
    PART_SUSPENDED = 3
    PLANNED_CLOSURE = 4
    PART_CLOSURE = 5
    SEVERE_DELAYS = 6
    REDUCED_SERVICE = 7
    BUS_SERVICE = 8
    MINOR_DELAYS = 9
    GOOD_SERVICE = 10
    PART_CLOSED = 11
    EXIT_ONLY = 12
    NO_STEP_FREE_ACCESS = 13
    CHANGE_OF_FREQUENCY = 14
    DIVERTED = 15
    NOT_RUNNING = 16
    ISSUES_REPORTED = 17
    NO_ISSUES = 18
    INFORMATION = 19
    SERVICE_CLOSED = 20


class DisruptionCategory(StrEnum):
    """Top-level category for a TfL disruption record."""

    REAL_TIME = "RealTime"
    PLANNED_WORK = "PlannedWork"
    INFORMATION = "Information"
    INCIDENT = "Incident"
    UNDEFINED = "Undefined"


LineId = str
StationId = str

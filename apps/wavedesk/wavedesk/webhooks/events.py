# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Outbound webhook event catalog (master doc §Phase 5 feature 2).

The canonical list of event types a WD Webhook Endpoint may subscribe to. Only a
subset is wired to emit() so far (see dispatch.py call sites); the rest are valid
subscriptions whose emit() call sites land in follow-ups — the delivery machinery
is identical for all of them."""

EVENT_TYPES = (
    "message.received",
    "message.sent",
    "message.failed",
    "chat.assigned",
    "chat.resolved",
    "ticket.created",
    "group.member_joined",
    "group.member_left",
    "broadcast.completed",
    "number.disconnected",
    "number.banned",
)

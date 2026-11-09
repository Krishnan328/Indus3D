"""Approval must use fresh job state and the same filters as automatic corrections."""
from types import SimpleNamespace

import pytest

from core import command_pipeline
from core.plugin_hooks import HookRegistry
from plugins.approval import Approval
from plugins.arbiter import Arbiter
from plugins.esp_bed_hub import EspHub


@pytest.fixture
def approval_cycle(monkeypatch):
    reg = HookRegistry()
    monkeypatch.setattr(command_pipeline, "hooks", reg)
    a = Approval(enabled=True)
    reg.on("commands.filter", a.filter, priority=30)
    sent, events = [], []
    reg.on("commands.sent", lambda res, ctx: events.extend(res))
    controller = SimpleNamespace(auto_pilot=True)
    ctx = {"now": 100.0, "source": "live", "send": lambda c: sent.append(c) or True,
           "controller": controller, "autopilot": True,
           "snap": {"print_state": "printing", "filename": "a.gcode", "print_duration": 100},
           "vetoes": [], "corrections": []}
    assert reg.apply("commands.filter", ["M104 S210"], ctx) == []
    return a, reg, ctx, sent, events


def test_approved_command_rechecks_crash_hold(approval_cycle):
    a, reg, ctx, sent, events = approval_cycle
    hub = EspHub(url="http://unused.invalid")
    hub.crash_latched = True
    reg.on("commands.filter", hub.filter_commands, priority=5)
    item, err = a.decide(1, True, now=101)
    assert item is None and "safety" in err and sent == [] and events == []


def test_approved_command_respects_a_new_manual_override(approval_cycle):
    a, reg, ctx, sent, _ = approval_cycle
    arbiter = Arbiter()
    arbiter.yield_until["nozzle_temp"] = 130
    reg.on("commands.filter", arbiter.filter, priority=10)
    assert a.decide(1, True, now=101)[1] is not None
    assert sent == []


@pytest.mark.parametrize("change", ["paused", "cancelled", "autopilot_off", "old_telemetry",
                                   "different_file", "restarted_file", "different_source", "disabled"])
def test_approval_refuses_changed_or_stale_context(approval_cycle, change):
    a, reg, ctx, sent, _ = approval_cycle
    if change in ("paused", "cancelled"):
        ctx["snap"] = dict(ctx["snap"], print_state=change)
    elif change == "autopilot_off":
        ctx["controller"].auto_pilot = False
    elif change == "old_telemetry":
        ctx["now"] = 95
    elif change == "different_file":
        ctx["snap"] = dict(ctx["snap"], filename="b.gcode")
    elif change == "restarted_file":
        ctx["snap"] = dict(ctx["snap"], print_duration=0)
    elif change == "different_source":
        ctx["source"] = "sim"
    else:
        a.enabled = False
    reg.apply("commands.filter", [], ctx)
    assert a.decide(1, True, now=101)[1] is not None
    assert sent == []


def test_approval_sends_once_and_audits_after_revalidation(approval_cycle):
    a, reg, ctx, sent, events = approval_cycle
    item, err = a.decide(1, True, now=101)
    assert err is None and item["ok"]
    assert sent == ["M104 S210"] and len(events) == 1
    assert a.decide(1, True, now=101)[1] is not None


def test_empty_quality_cycles_refresh_approval_state(monkeypatch):
    reg = HookRegistry()
    monkeypatch.setattr(command_pipeline, "hooks", reg)
    a = Approval(enabled=True)
    reg.on("commands.filter", a.filter)
    sent = []
    controller = SimpleNamespace(auto_pilot=True, update=lambda *args: ["M104 S210"])
    send = lambda c: sent.append(c) or True
    command_pipeline.run_quality_cycle(controller, {"print_state": "printing"}, {}, {}, {}, send)
    controller.update = lambda *args: []
    command_pipeline.run_quality_cycle(controller, {"print_state": "paused"}, {}, {}, {}, send)
    assert a.decide(1, True)[1] is not None and sent == []


def test_paused_tick_invalidates_approval_without_a_quality_cycle(approval_cycle):
    a, reg, ctx, sent, _ = approval_cycle
    a.tick(dict(ctx["snap"], print_state="paused"), {"now": 100.5, "source": "live"})
    assert a.decide(1, True, now=101)[1] is not None
    assert sent == []

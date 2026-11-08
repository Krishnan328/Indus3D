import pytest
from core.alert_actions import execute_alert_action, clear_all_actioned, _actioned
import core.alert_actions as aa

@pytest.fixture(autouse=True)
def setup_teardown():
    clear_all_actioned()
    yield
    clear_all_actioned()

def test_unknown_alert():
    res = execute_alert_action("fake_alert", "printing")
    assert res["status"] == "no_action_defined"

def test_informational_alert(monkeypatch):
    res = execute_alert_action("stress_X", "printing")
    assert res["status"] == "informational_only"

def test_critical_alert_executes_any_state(monkeypatch):
    sent_gcode = None
    def mock_send(gcode):
        nonlocal sent_gcode
        sent_gcode = gcode
        return True
    
    # Mock MoonrakerClient singleton instance
    monkeypatch.setattr(aa._client, "send_gcode", mock_send)
    monkeypatch.setattr(aa, "_log_action", lambda x: None)
    
    # Should execute even if idle
    res = execute_alert_action("ext_runaway", "idle")
    assert res["status"] == "executed"
    assert sent_gcode == "M112"
    assert "ext_runaway" in _actioned

def test_warn_alert_only_when_printing(monkeypatch):
    sent_gcode = None
    def mock_send(gcode):
        nonlocal sent_gcode
        sent_gcode = gcode
        return True
        
    monkeypatch.setattr(aa._client, "send_gcode", mock_send)
    monkeypatch.setattr(aa, "_log_action", lambda x: None)
    
    res = execute_alert_action("lag", "idle")
    assert res["status"] == "skipped_not_printing"
    assert sent_gcode is None
    
    res = execute_alert_action("lag", "printing")
    assert res["status"] == "executed"
    assert sent_gcode == "M220 S80"

def test_deduplication(monkeypatch):
    count = 0
    def mock_send(gcode):
        nonlocal count
        count += 1
        return True
        
    monkeypatch.setattr(aa._client, "send_gcode", mock_send)
    monkeypatch.setattr(aa, "_log_action", lambda x: None)
    
    res1 = execute_alert_action("ext_runaway", "printing")
    res2 = execute_alert_action("ext_runaway", "printing")
    
    assert res1["status"] == "executed"
    assert res2["status"] == "already_actioned"
    assert count == 1

def test_power_cutoff(monkeypatch):
    def mock_send(gcode): return True
    
    cut_device = None
    cut_action = None
    def mock_set_power(device, action):
        nonlocal cut_device, cut_action
        cut_device = device
        cut_action = action
        return True
        
    monkeypatch.setattr(aa._client, "send_gcode", mock_send)
    monkeypatch.setattr(aa._client, "set_power", mock_set_power)
    monkeypatch.setattr(aa, "_log_action", lambda x: None)
    
    # Mock get_power_cfg
    monkeypatch.setattr(aa, "get_power_cfg", lambda: {"cutoff_enabled": True, "cutoff_device": "my_plug"})
    
    res = execute_alert_action("bed_runaway", "printing")
    
    assert cut_device == "my_plug"
    assert cut_action == "off"
    assert "power cutoff to 'my_plug' succeeded" in res["description"]

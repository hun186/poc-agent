from requirement_scheduler.models import MaterializedRun, TriggerIdentity


def test_materialized_models_preserve_version_number_and_order():
    trigger = TriggerIdentity("scheduled", __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    item = {"requirement_version_id": "rv3", "requirement_version_number": 3, "source_order": 8}
    result = MaterializedRun({"snapshot_id": "snap"}, (item,))
    assert trigger.trigger_type == "scheduled"
    assert result.items[0]["requirement_version_number"] == 3
    assert result.items[0]["source_order"] == 8

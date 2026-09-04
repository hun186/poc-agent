import pytest

from requirement_scheduler.policy import Checkpoint


def test_checkpoint_requires_complete_id_number_pairs():
    assert Checkpoint(last_seen_requirement_version_id="rv2", last_seen_requirement_version_number=2).last_seen_requirement_version_number == 2
    with pytest.raises(ValueError, match="checkpoint_version_pair_invalid"):
        Checkpoint(last_seen_requirement_version_id="rv2")
    with pytest.raises(ValueError, match="checkpoint_version_pair_invalid"):
        Checkpoint(last_successful_requirement_version_number=2)

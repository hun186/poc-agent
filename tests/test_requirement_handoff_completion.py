import pytest
from requirement_scheduler.execution import ExecutionFailure
from requirement_scheduler.handoff import checkpoint_outcome
@pytest.mark.parametrize("stored_n,stored_id,in_n,in_id,want",[(None,None,1,"a","advance"),(1,"a",2,"b","advance"),(2,"b",1,"a","noop"),(1,"a",1,"a","noop")])
def test_checkpoint_cases_a_to_d(stored_n,stored_id,in_n,in_id,want): assert checkpoint_outcome(stored_n,stored_id,in_n,in_id)==want
def test_same_version_same_identity_different_item_is_not_a_conflict(): assert checkpoint_outcome(4,"rv",4,"rv")=="noop"
def test_equal_number_different_immutable_identity_fails_closed():
    with pytest.raises(ExecutionFailure): checkpoint_outcome(4,"rv-a",4,"rv-b")

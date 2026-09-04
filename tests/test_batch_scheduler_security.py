from pathlib import Path
from batch_scheduler.config import BatchSchedulerConfig

def test_phase0_harness_has_no_raw_key_literal():
 text=Path('tests_code/test_phase0_api_routing_evidence.py').read_text()
 assert 'sra_sk_' not in text.replace('sra_sk_invalid_key',''), 'raw-looking key in operator harness'
def test_key_not_repr_or_error():
 c=BatchSchedulerConfig('http://x','supersecret');assert 'supersecret' not in repr(c)

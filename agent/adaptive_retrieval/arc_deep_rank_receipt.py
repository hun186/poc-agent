"""One-shot private rank observation from a verified deep PIT round."""
from __future__ import annotations

from agent.arc_mode import arc_shadow_enabled

from dataclasses import dataclass, field
from threading import Lock

from agent.es.arc_native_rank_receipt import DeepNativeRankFrequency
from .round_query_execution import FrozenSingleQueryPlan, CompletedSingleQueryRound
from .worker_scope_binding import WorkerScopeBinding


@dataclass(repr=False)
class DeepRoundRankReceipt:
    plan: FrozenSingleQueryPlan = field(repr=False)
    binding: WorkerScopeBinding = field(repr=False)
    hits: tuple[dict, ...] = field(repr=False)
    frequency: DeepNativeRankFrequency = field(repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _used: bool = field(default=False, init=False, repr=False)

    def consume(self, *, plan, binding, fetched):
        """Consume only once, after exact canonical owner attestation."""
        with self._lock:
            if self._used:
                return None
            self._used = True
            if (not arc_shadow_enabled("SRAF_ARC_RANK_DEEP")
                    or plan is not self.plan or binding is not self.binding
                    or type(fetched) is not CompletedSingleQueryRound
                    or fetched._execution_token is not plan._execution_token
                    or fetched.round_number != plan.round_number
                    or fetched.query_plan_complete is not True
                    or len(self.hits) != len(fetched.hits)
                    or any(a is not b for a, b in zip(self.hits, fetched.hits))
                    or self.frequency.groups != tuple(frozenset(g) for g in plan.coordinator._groups)
                    or not binding.recheck_optional_frequency(plan, after_attest=True)):
                return None
            return self.frequency

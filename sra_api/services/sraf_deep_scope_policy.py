"""Server-owned authenticated admission for the first explicit deep query contract.

An actual verified SRAF user and a separately configured per-account index
grant are mandatory. This deliberately supports only an explicit, complete,
single-branch question contract. General natural-language scope derivation,
HTTP activation and startup configuration are separate gates.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from agent.adaptive_retrieval.contracts import DateWindow, QueryConstraints, _original_question
from api.security.models import AuthPrincipal
from api.security.scopes import (
    DOCUMENT_READ, MODEL_INVOKE, REPORT_JOB_CREATE, REPORT_JOB_READ,
    REPORT_JOB_DOWNLOAD, scopes_for_user_role,
)
import api.services.auth_store as auth_store_module
from api.services.auth_support import VALID_ROLES, normalize_role
from api.services.report_job_store import ADAPTIVE_JOB_OPTION, ReportJob, ReportJobStore
from api.services.sraf_adaptive_job_runtime import (
    ADAPTIVE_OWNER_BINDING, AdaptiveJobIntent, create_adaptive_job,
)


class DeepScopeDenied(ValueError):
    """Fixed authorization denial, no private information."""


class DeepQuestionUnsupported(ValueError):
    """Fixed unsupported scope, not an invitation to silently broaden it."""


_REQUIRED = frozenset({DOCUMENT_READ, MODEL_INVOKE, REPORT_JOB_CREATE,
                       REPORT_JOB_READ, REPORT_JOB_DOWNLOAD})
_INDEX = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}\Z")
_LABEL = re.compile(r"[^\W_]+(?:[ -][^\W_]+)*\Z", re.UNICODE)
_RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})\Z")
_UNSUPPORTED = re.compile(r"排除|不含|不得|只限|除了|\b(?:except|exclude|without|only)\b", re.I)


def _labels(raw: str) -> tuple[str, ...]:
    values = tuple(raw.split("、"))
    if (not 1 <= len(values) <= 8
            or any(not 1 <= len(v) <= 100 or not _LABEL.fullmatch(v)
                   or _UNSUPPORTED.search(v) for v in values)
            or len({v.casefold() for v in values}) != len(values)):
        raise DeepQuestionUnsupported("deep_question_unsupported")
    return values


def compile_explicit_deep_question(prompt: str, indexes: tuple[str, ...]) -> AdaptiveJobIntent:
    """The entire three-line question is a documented literal-field grammar.

    It is not a free-text classifier. Topic terms are flexible search labels,
    not exclusion or Boolean expressions. Every analysis aspect is a coverage
    target. No unsupported prose/branches, analysis-time, fields or relative
    date are inferred or ignored. Original whitespace remains in the digest.
    """
    try:
        _original_question(prompt)
        lines = prompt.strip().splitlines()
        labels = ("主題詞：", "事件期間：", "分析面向：")
        if len(lines) != 3 or any(not line.startswith(prefix)
                                  for line, prefix in zip(lines, labels)):
            raise ValueError
        terms, time_text, aspects = (line[len(prefix):]
                                     for line, prefix in zip(lines, labels))
        topic_terms = _labels(terms)
        target_aspects = _labels(aspects)
        if time_text == "不限":
            window = DateWindow()
        else:
            match = _RANGE.fullmatch(time_text)
            if match is None:
                raise ValueError
            window = DateWindow(match[1], match[2], "day", "explicit_user", time_text)
        constraints = QueryConstraints(
            question=prompt, event_date=window, analysis_date=DateWindow(),
            allowed_indexes=indexes, original_core_terms=topic_terms,
        )
        return AdaptiveJobIntent(constraints, tuple((t,) for t in topic_terms),
                                 topic_terms, target_aspects)
    except Exception:
        raise DeepQuestionUnsupported("deep_question_unsupported") from None


@dataclass(frozen=True, repr=False)
class DeepOwnerGrant:
    owner_id: str
    account_created_at: str
    indexes: tuple[str, ...]

    def __post_init__(self):
        if (type(self.owner_id) is not str or not 1 <= len(self.owner_id) <= 64
                or self.owner_id != self.owner_id.strip()
                or type(self.account_created_at) is not str
                or not 1 <= len(self.account_created_at) <= 80
                or self.account_created_at != self.account_created_at.strip()
                or type(self.indexes) is not tuple or not 1 <= len(self.indexes) <= 8
                or any(type(i) is not str or not _INDEX.fullmatch(i)
                       or ".." in i for i in self.indexes)
                or len(set(self.indexes)) != len(self.indexes)):
            raise DeepScopeDenied("deep_owner_grant_invalid")


def active_account_binding(owner_id: str) -> str | None:
    """Bind an account generation, not a browser session or a credential.

    Closing a browser or ordinary logout must not interrupt a durable job.
    Account disable/delete/recreate cannot inherit a prior admission.
    """
    try:
        row = auth_store_module.AUTH_STORE.get_user(owner_id)
        if type(row) is not dict or row.get("status") != "active":
            return None
        created = row.get("created_at")
        if type(created) is not str or not 1 <= len(created) <= 80:
            return None
        return hashlib.sha256(json.dumps([owner_id, created], ensure_ascii=False,
                                         separators=(",", ":")).encode()).hexdigest()
    except Exception:
        return None


@dataclass(frozen=True, repr=False)
class DeepScopePolicy:
    grants: tuple[DeepOwnerGrant, ...]
    max_active_jobs: int

    def __post_init__(self):
        if (type(self.grants) is not tuple or not 1 <= len(self.grants) <= 256
                or any(type(g) is not DeepOwnerGrant for g in self.grants)
                or len({g.owner_id for g in self.grants}) != len(self.grants)
                or type(self.max_active_jobs) is not int
                or not 1 <= self.max_active_jobs <= 1000):
            raise DeepScopeDenied("deep_policy_invalid")

    def _live(self, owner: str) -> tuple[DeepOwnerGrant, str, str]:
        grant = next((g for g in self.grants if g.owner_id == owner), None)
        if grant is None:
            raise DeepScopeDenied("deep_owner_denied")
        row = auth_store_module.AUTH_STORE.get_user(owner)
        if (type(row) is not dict or row.get("status") != "active"
                or row.get("created_at") != grant.account_created_at
                or row.get("role") not in VALID_ROLES):
            raise DeepScopeDenied("deep_owner_denied")
        role = normalize_role(row["role"])
        binding = active_account_binding(owner)
        if binding is None or not _REQUIRED.issubset(scopes_for_user_role(role)):
            raise DeepScopeDenied("deep_owner_denied")
        # Avoid binding a different account if the AuthStore changed between reads.
        expected = hashlib.sha256(json.dumps([owner, grant.account_created_at],
                                  ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        if binding != expected:
            raise DeepScopeDenied("deep_owner_denied")
        return grant, binding, role

    def _verified_principal(self, principal: AuthPrincipal):
        if (type(principal) is not AuthPrincipal or principal.kind != "user"
                or not _REQUIRED.issubset(principal.scopes)
                or not principal.credential_id
                or auth_store_module.AUTH_STORE.is_token_denied(principal.credential_id)):
            raise DeepScopeDenied("deep_owner_denied")
        grant, binding, role = self._live(principal.subject)
        if principal.role != role:
            raise DeepScopeDenied("deep_owner_denied")
        return grant, binding

    def admit(self, store: ReportJobStore, *, principal: AuthPrincipal, prompt: str,
              idempotency_key: str, filename: str | None = None):
        """Call only with a server-authenticated AuthPrincipal, never request JSON."""
        if (type(store) is not ReportJobStore or type(idempotency_key) is not str
                or not 1 <= len(idempotency_key) <= 128
                or idempotency_key != idempotency_key.strip()
                or any(ord(c) < 32 or ord(c) == 127 for c in idempotency_key)):
            raise DeepScopeDenied("deep_admission_invalid")
        grant, binding = self._verified_principal(principal)
        intent = compile_explicit_deep_question(prompt, grant.indexes)
        if self._verified_principal(principal) != (grant, binding):
            raise DeepScopeDenied("deep_owner_denied")
        return create_adaptive_job(
            store, intent=intent, owner_id=principal.subject,
            idempotency_key="deep-v1:" + idempotency_key,
            max_active_jobs=self.max_active_jobs, filename=filename,
            owner_binding=binding,
        )

    def _job_grant(self, job: ReportJob) -> DeepOwnerGrant:
        if type(job) is not ReportJob or job.owner_kind != "user":
            raise DeepScopeDenied("deep_owner_denied")
        grant, binding, _ = self._live(job.owner_id)
        if job.metadata != {ADAPTIVE_OWNER_BINDING: binding}:
            raise DeepScopeDenied("deep_owner_denied")
        return grant

    def check_owner_index(self, job: ReportJob, index: str) -> bool:
        try:
            return index in self._job_grant(job).indexes
        except Exception:
            return False

    def check_question_branches(self, job: ReportJob, constraints: QueryConstraints,
                                branches: tuple[str, ...]) -> bool:
        try:
            grant = self._job_grant(job)
            expected = compile_explicit_deep_question(job.prompt, grant.indexes)
            return (branches == ("CANONICAL_MAIN",)
                    and expected.constraints == constraints
                    and expected.options() == job.options)
        except Exception:
            return False


def binding_for_principal(principal: AuthPrincipal) -> str | None:
    """Only use a principal already authenticated by the server dependency."""
    if type(principal) is not AuthPrincipal or principal.kind != "user":
        return None
    return active_account_binding(principal.subject)


def bound_deep_owner_matches(job: ReportJob, principal: AuthPrincipal) -> bool:
    """Deep results have no cross-owner admin bypass or username reuse grant."""
    if (type(job) is not ReportJob or type(principal) is not AuthPrincipal
            or ADAPTIVE_JOB_OPTION not in job.options
            or job.owner_kind != "user" or principal.kind != "user"
            or job.owner_id != principal.subject):
        return False
    binding = binding_for_principal(principal)
    return binding is not None and job.metadata == {ADAPTIVE_OWNER_BINDING: binding}

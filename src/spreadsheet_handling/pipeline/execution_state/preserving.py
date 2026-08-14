"""Optional ordinary-preserving certificates (FTR section 5; section 12, Alt. C).

A preserving certificate is a redundant-check *optimization*: it lets a
caller skip re-running ordinary re-establishment after an exact reviewed
invocation whose ordinary-state postcondition is already closed. It is never
controlled-role authority (FTR section 5's semantic rule:
"preserving certificate = redundant-check optimization NOT preserving
certificate = controlled-role authority") and it is not required for E4 to be
complete -- the accepted architecture proves all twelve maintained flows
close with *zero* ordinary preserving certificates (Independent Follow-up
Review 005, "Twelve-flow zero-preserving proof").

The initial set here is therefore empty. Later family hardening may append an
entry as a pure optimization without changing this contract (FTR section 12,
"Bounded E4 migration rule"); that audit is explicitly out of E4's scope
(FTR section 28).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreservingCertificate:
    """One exact reviewed bound invocation whose ordinary postcondition is closed.

    ``target`` is the exact dotted ``module:qualname`` this certificate
    covers (matching ``BoundStep.config["target"]``); ``closed_options``
    names the exact option keys the review covered as closed (not their
    values -- a certificate is only valid for the reviewed exact
    configuration, never "any value of this option"). ``evidence`` is a short
    pointer to where that review lives (an FTR section, a test module).
    """

    target: str
    closed_options: tuple[str, ...]
    evidence: str


PRESERVING_CERTIFICATES: tuple[PreservingCertificate, ...] = ()
"""The current evidence-backed preserving set.

Deliberately empty; see module docstring. There is no requirement to
certify a built-in merely to demonstrate the mechanism (FTR section 5).
"""


__all__ = ["PreservingCertificate", "PRESERVING_CERTIFICATES"]

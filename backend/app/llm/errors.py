"""Narrow, provider-agnostic error taxonomy for the LLM layer.

`FailoverProvider` (see `failover.py`) catches ONLY `TransientProviderError`
and its subclasses. Per ADR-002, that is a deliberate choice: a missing/
invalid API key, a malformed request, or a genuine bug in our own code must
never be silently reported as "the provider failed over cleanly." Anything
that isn't one of these three shapes propagates unchanged to the caller.
"""


class ProviderError(Exception):
    """Base class for any error raised while calling an LLM provider."""


class TransientProviderError(ProviderError):
    """Timeout / 5xx / rate-limit / connection failure — the only category
    `FailoverProvider` treats as failover-eligible.
    """


class ProviderTimeoutError(TransientProviderError):
    """The provider didn't respond in time, or the connection couldn't be
    established at all (treated as timeout-shaped — see ADR-010).
    """


class ProviderRateLimitError(TransientProviderError):
    """The provider returned a 429."""


class ProviderServerError(TransientProviderError):
    """The provider returned a 5xx."""

"""Provider-agnostic LLM layer (ADR-002, ADR-010).

One `LLMProvider` interface with two concrete implementations (`GeminiProvider`,
`OpenRouterProvider`) and a `FailoverProvider` that composes them. The agent
graph depends only on `LLMProvider` — never on a concrete provider.
"""

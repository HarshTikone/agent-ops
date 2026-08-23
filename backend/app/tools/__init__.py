"""Tool adapters (ARCHITECTURE.md §2): web search, notes store, calculator.

Each adapter shares a uniform interface (`name`, `description`, `args_schema`,
`run`) so the planner's tool-selection logic never special-cases any one
tool, and each adapter raises `ToolError` — never a raw exception — on
failure (ARCHITECTURE.md §6 hard requirement).
"""

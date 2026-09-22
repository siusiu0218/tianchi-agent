# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, or
- **`CONTEXT-MAP.md`** at the repo root if it exists.
- **`docs/adr/`** — read ADRs that touch the area being changed.

If these files don't exist, proceed silently. Domain-modeling skills create them lazily when terms or decisions are resolved.

## File structure

This is a single-context repository:

```
/
├── CONTEXT.md
├── docs/adr/
└── src/
```

## Use the glossary's vocabulary

Use domain terms as defined in `CONTEXT.md`. Avoid synonyms that the glossary explicitly rejects.

## Flag ADR conflicts

If proposed work contradicts an existing ADR, identify that conflict explicitly instead of silently overriding the decision.

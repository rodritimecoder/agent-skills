# Review Hub (`review-hub`)

Unified Code Review, Architecture Audit, and Quality Enforcement Gateway.

`review-hub` is a high-leverage late-binding CLI tool that provides automated code reviews, debt scans, and architectural audits across 8 specialized disciplines. It integrates with Git repositories to review active diffs or specific files while keeping agent context windows compact through output buffering (`--out`) and field projection (`--project`).

## Core Suites

1. **`ponytail`**: Minimalist Engineering & YAGNI. Enforces minimal diffs, deletion over addition, and lean change sets.
2. **`pstack`**: 23 battle-tested engineering playbooks for deep agent autonomy, systematic triage, and runtime forensics.
3. **`poteto`**: Domain modeling, state machines, transition matrices, and type discipline.
4. **`thermonuclear`**: Harsh architectural audit enforcing 1,000-line ceilings, anti-spaghetti conditionals, and structural simplification.
5. **`unslop`**: 31-rule scanner eliminating AI tells, superficial phrasing, and chatbot artifacts.
6. **`typescript`**: Type discipline enforcing discriminated unions, branded types, and eliminating unvalidated `as` / `any` casts.
7. **`no-comments`**: Eliminates trivial comments and AI commentary; pushes constraints into types and runtime assertions.
8. **`verification`**: Grounded verification protocol: Launch, Doctor, Drive, Evidence, Cleanup.

## Quickstart

```bash
# List review suites
review-hub list

# Search suites by intent
review-hub search "harsh audit"

# View suite rubric
review-hub inspect thermonuclear

# Review active git diff
review-hub review ponytail

# Run architectural audit
review-hub audit thermonuclear

# Run all core suites
review-hub all
```

# ⚡ Coding Powerhouse: The Big Five

> A drop-in coding manifesto combining **Ponytail**, **Thermo-Nuclear**, **TS Best Practices**, **No Comments**, and **Unslop**.
> 
> **Trigger Phrase**: Drop `"Powerhouse Mode"`, `"Apply the Big 5"`, or name-drop any of the five skills in your prompt to enforce this standard on any coding task.

---

## 🎯 The 5-Phase Execution Flow

When tackling any code task (bug fix, feature, refactor, or review), run these 5 filters in sequence:

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  1. PONYTAIL │ ──> │  2. THERMO   │ ──> │    3. TS     │ ──> │4. NO-COMMENTS│ ──> │  5. UNSLOP  │
│  Minimal Diff│     │  Clean Arch  │     │ Strict Types │     │ No Apologies │     │ Direct Prose │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

---

## 1. 🪓 Ponytail: The Lazy Senior Dev
> *"The best code is the code you never wrote."*

* **The Smallest Complete Diff**: Solve the exact problem with the least new code.
* **YAGNI (You Aren't Gonna Need It)**: Reject wrappers, future-proofing, config toggles, and abstractions nobody asked for.
* **Platform & Stdlib First**: Use what the runtime or installed dependencies already provide before writing custom helpers.
* **Never Cut**: Security, input validation at boundaries, error handling that prevents data loss, or user requirements.

---

## 2. ☢️ Thermo-Nuclear: Structural Code Judo
> *"Delete complexity rather than rearranging it."*

* **Code Judo**: Find structural reorganizations where entire branches, helpers, or special-case modes disappear completely.
* **1,000-Line Ceiling**: Never let a PR push a file past 1,000 lines without decomposing it into clear helpers or modules first.
* **Zero Spaghetti Conditionals**: Reject ad-hoc `if` statements scattered in unrelated flows. Model state transitions explicitly.
* **Boring over Magic**: Reject clever identity wrappers and brittle generic abstractions that obscure data shapes.

---

## 3. 🛡️ TypeScript Best Practices: Bulletproof Types
> *"Make illegal states unrepresentable."*

* **Discriminated Unions**: Model states with a literal `kind` or `status` tag. No loose optional bags (`{ error?: string, data?: any }`).
* **State Transition Matrix**: For multi-step async/UI flows, tabulate `State x Event -> Next State + Rollback` before coding. Every state variant must exist in the type union.
* **Zero `as` Casts**: Treat `as Type` as a bug. Validate data at the boundary and narrow with `switch`, `in`, or type guards.
* **`unknown` at the Gate**: External/API inputs start as `unknown`. Parse once with schemas (e.g., Zod `z.infer`), then trust internal domain types.
* **Branded Primitives**: Brand IDs (`type UserId = string & { readonly __brand: "UserId" }`) so IDs can never be swapped by accident.
* **Exhaustiveness**: Always enforce `const _exhaustive: never = state;` in default branches.

---

## 4. 🩸 No Comments: The Comment Sicko
> *"A long justification in code is a confession. Fix the code."*

* **Kill Narration**: Delete obvious step-by-step commentary (`// loop over items`, `// Phase 1: fetch data`).
* **Kill Apologies**: If code needs `// too risky to change`, `// fine for now`, or `// fix later`, refactor the code instead of apologizing.
* **Kill Lazy Suppressions**: Delete unjustified `// @ts-ignore` or `eslint-disable` workarounds hiding real bugs.
* **What Survives**: Legal headers, public API docstrings, and workarounds forced by third-party vendor bugs code cannot change.

---

## 5. ✂️ Unslop: Crisp, Factual Prose
> *"Say what it does, not how it feels."*

* **Ban AI Vocabulary**: Strip *crucial, delve, enhance, landscape, pivotal, tapestry, testament, underscore, vibrant*.
* **Ban Sycophancy & Fluff**: Cut *"Great question!"*, *"Certainly!"*, *"I hope this helps!"*, and superficial `-ing` clauses (*highlighting, ensuring*).
* **Format Hygiene**: No em dashes (`—`), no decorative emojis in headings, no mid-sentence colon connectors.
* **Concrete Evidence**: One thought per sentence. State measured numbers and mechanisms, not impressions.

---

## 📋 Copy-Paste Prompt Snippet

Paste this one-liner into any prompt or project rule:

```text
Apply Powerhouse Mode: Ponytail (smallest working diff, YAGNI), Thermo-Nuclear (structural judo, kill spaghetti conditionals, <1k lines), TS Best Practices (discriminated unions, no 'as', parse unknown at boundary), No Comments (kill narration and apology comments), and Unslop (direct declarative prose, zero AI fluff).
```

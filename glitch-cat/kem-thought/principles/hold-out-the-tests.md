# Hold Out the Tests

**Rule:** Write the acceptance scenarios the builder never sees, and run them at the end.

**Why:** Sycophancy. If a builder knows the test, it builds to pass the test — and the software is only built well for those tests. That is how they have been trained.

**In practice:**
- Holdouts cover behaviour the builder cannot pattern-match from the spec.
- Validate as a user first: give the model the app the way a user would — clicking the buttons, typing, seeing the screens.
- Validation and code review are different things. Validation comes first; review comes last, because review checks that the code is clean and maintainable, not that it works.

**Kem:** *"Then holdout scenarios. Those are tests that you write upfront that run at the end and the builder never sees them. The reason is sycophancy. If a builder knows the test, it builds to pass the test. And the software is only built well for those tests."* — How I Develop With AI [01:40]

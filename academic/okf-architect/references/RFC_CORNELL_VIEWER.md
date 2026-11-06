# RFC: Revisit Cornell Notes Viewer Architecture

Tracking Pull Request: [rodritimecoder/university#1](https://github.com/rodritimecoder/university/pull/1)

## Summary of Deferred Task
The current embedded Cornell reader in `viz_template.html` uses a full-screen (`100vw × 100vh`) iframe modal with a topbar.

### Issues Identified:
1. **Simulated Tab Anti-Pattern**: An iframe taking the whole screen mimics a tab without browser history, native search, or URL deep-linking.
2. **Scroll / Keyboard Boundary Trap**: Trackpad inertia and `Esc`/arrow shortcuts occasionally get trapped inside the iframe.
3. **Aesthetic Jarring**: Abrupt switch between dark cosmic canvas (`#0b0c10`) and bright white paper note (`#ffffff`).

### Proposed Redesign Alternatives:
- **Option A (Recommended)**: Collapsible sliding side-drawer (Obsidian/Roam style) occupying ~65% of the right screen while keeping the 3D galaxy interactive on the left.
- **Option B**: Dedicated reader route (`/notes/reader.html?stem=...`) with browser history navigation.
- **Option C**: In-DOM dynamic markdown/HTML injection with unified dark/light theme tokens.

*Status: Open for future revision.*

# Verification Gotchas & Diagnostics (`references/gotchas.md`)

Common edge cases, pitfalls, and failure modes when running or configuring the verification gate.

---

### Environment & Setup
- **`doctor` first, and read it**: `eyes` needs a live CDP target (`:9222`), `pixels` needs ffmpeg, and `states` needs a Storybook answering `/index.json`. A missing dependency exits `3`, which is an environment gap, not a test failure.
- **Observations start when the gate attaches**: CDP sessions record events during and after attachment. Start the gate before triggering the journey.
- **Auth flows are yours**: The gate does not perform login credentials entry for you; configure storage state, pre-seed test sessions, or use token URLs.

### Geometry & Viewports
- **One viewport per answer**: `390x844` is the standard mobile viewport. Testing on desktop proves nothing about mobile. Without `<meta name="viewport">`, Chrome on mobile lays out at 980px and reports false passes while visual viewports are cut off.
- **Cut-off targets are caught before clicking**: The click is dispatched, but `viewport` in `problems` flags that the element center falls outside viewport bounds.
- **Occluded clicks**: Before clicking, the gate calls `elementFromPoint`. If a cookie banner, header, or loading overlay covers the button center, the finding is `occluded` and names the covering element.
- **Responsive shrink-to-fit vs overflow**: When content exceeds declared width, Chrome may expand the layout viewport and shrink-to-fit (`page needs 1150px but viewport is 390px ... read at 34% size`). A plain narrow window reports `horizontal_overflow`. Both are layout bugs; inspect `layout` in `verify.json`.

### Text & DOM
- **`innerText` vs Markup**: CSS `text-transform: uppercase` changes rendered characters. `expect.text` matches case-insensitively by default. Set `case_sensitive: true` only when casing is explicitly under test.
- **Canvas / WebGL apps**: Canvas elements lack DOM text nodes. Use `expect.eval` to assert internal state variables (`nodeCount`, store state), and let the pixel layer handle visual assertions.

### Pixels & Baselines
- **Baselines are deliberate decisions**: `max_changed: 0.0` requires pixel-for-pixel identity (ideal for refactors/bug fixes). UI redesigns require newly committed baselines.
- **Tolerance absorbs anti-aliasing**: Default tolerance `8` handles subpixel font rendering differences across GPU rasterizers without triggering false positives.

### Scaffolding & Control
- **`forge` is dry-run until `--apply`**: Without `--apply`, `forge` only prints findings. If questions remain unanswered, `--apply` exits `4` (partial gate) while still generating scaffolds.
- **`forge` never overwrites existing `SKILL.md`**: Hand modifications in target repos are preserved.
- **`forge` reads routes, not intentions**: It discovers route files and decorators; human engineers still formulate the assertions.
- **`control` requires exact single match**: `--find` must appear exactly once in `--file`. Ambiguous targets abort immediately to prevent corrupting unrelated code.
- **A green `control` is not proof of everything**: It proves a single assertion fails when broken. The feature coverage map must still be maintained.

# `pass.json` Specification (`references/pass-schema.md`)

`pass.json` is the configuration artifact that defines the five answers of the verification gate.

---

## 📋 The Five Questions

`verify-app ask --out .verify` prompts or generates the skeleton:

1. **Surface**: What URL and viewport define the target under test?
2. **Journey**: What trusted actions must be performed to reach the goal state?
3. **Expectation**: What visible text, network requests, and DOM state must be true afterward?
4. **Pixels**: What baseline image should visual regression compare against?
5. **Observability**: What Storybook states and Sentry error thresholds apply?

Unanswered questions remain as `"unanswered"` and evaluate as a **partial gate** (exit code `4`).

---

## 📄 Schema & Example

```json
{
  "name": "cart-mobile",
  "api": {
    "url": "http://localhost:3000/cart",
    "viewport": "390x844",
    "settle_ms": 800
  },
  "journey": [
    {"fill": ["#email", "buyer@example.com"]},
    {"click": "#pay"},
    {"wait": 800}
  ],
  "expect": {
    "text": "Order confirmed",
    "case_sensitive": false,
    "requests": [{"contains": "/api/checkout", "status": 200}],
    "eval": [
      {
        "label": "graph rendered",
        "expression": "document.querySelectorAll('canvas').length > 0"
      }
    ],
    "no_failed_requests": true
  },
  "pixels": {
    "baseline": "baseline/cart-mobile.png",
    "tolerance": 8,
    "max_changed": 0.0
  },
  "states": {
    "storybook": "http://localhost:6006",
    "filter": "Cart",
    "max_stories": 30
  },
  "errors": {
    "sentry": {
      "org": "my-org",
      "project": "web",
      "stats_period": "24h",
      "max_issues": 0
    }
  },
  "artifacts": ".verify/artifacts"
}
```

---

## 🕹️ Journey DSL

Journey actions are dispatched as real CDP events:

| Action | Syntax | Behavior |
| :--- | :--- | :--- |
| `click` | `{"click": "#selector"}` | Checks geometry, confirms element is not occluded, dispatches real CDP mouse events at element center |
| `fill` | `{"fill": ["#selector", "text"]}` | Focuses input, clears existing content, types text via CDP Input |
| `press` | `{"press": "Enter"}` | Dispatches keyboard press via CDP |
| `eval` | `{"eval": "expression"}` | Evaluates JavaScript expression in page context |
| `wait` | `{"wait": 800}` | Pauses execution for `N` milliseconds |

---

## 🎯 Expectation DSL

| Key | Type | Description |
| :--- | :--- | :--- |
| `text` | string | Text expected to be present in page DOM |
| `case_sensitive` | bool | Case-sensitive text matching (default: `false` to respect CSS `text-transform`) |
| `requests` | array | Expected HTTP requests (`{"contains": "/path", "status": 200}`) |
| `no_failed_requests` | bool | Fails if any HTTP request returned status ≥ 400 |
| `eval` | array | Custom JS assertions (`{"label": "...", "expression": "..."}`) |

---

## 📦 Evidence Artifact (`verify.json`)

Running `verify-app run --pass .verify/pass.json` emits `.verify/artifacts/verify.json`:

```json
{
  "name": "cart-mobile",
  "url": "http://localhost:3000/cart",
  "viewport": "390x844",
  "verdict": "pass",
  "gate": "full",
  "exit": 0,
  "failed": [],
  "skipped": ["errors"],
  "layers": {
    "hands": {"status": "pass", "steps": 3},
    "eyes": {"status": "pass", "problems": []},
    "pixels": {"status": "pass", "changed_pixels": 0},
    "states": {"status": "pass", "stories_tested": 12}
  }
}
```

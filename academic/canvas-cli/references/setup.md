## Setup

Requires `CANVAS_API_KEY` and `CANVAS_URL`, read from the environment or from a
`.env` file in the skill directory:

```
CANVAS_API_KEY=your_canvas_api_token
CANVAS_URL=https://your-school.instructure.com
```

Get a token in Canvas → Account → Settings → + New Access Token.
`CANVAS_URL` is the bare host, no `/api/v1` suffix and no trailing slash.

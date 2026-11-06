## Setup

Requires `ED_API_TOKEN` (and optional `ED_BASE_URL`), read from the environment or from a `.env` file in the skill directory (`~/.gemini/config/skills/edstem-cli/.env`):

```bash
# Get your token at:
#   - Australia / Global (UTS, USYD, UNSW, etc.): https://edstem.org/settings/api-tokens
#   - US: https://edstem.org/us/settings/api-tokens
ED_API_TOKEN=your_ed_api_token
```

By default, requests route to `https://edstem.org/api/` (Australia / Global). To use the US endpoint, set:
```bash
ED_BASE_URL=https://us.edstem.org/api/
```

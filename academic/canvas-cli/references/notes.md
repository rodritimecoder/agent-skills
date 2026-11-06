## Notes

- Timestamps are ISO 8601: `2026-03-30T23:59:00Z` for UTC, or with an offset
  such as `2026-03-30T23:59:00-04:00`.
- Rate limits and transient 5xx errors are retried automatically with backoff,
  honouring `Retry-After`. Requests time out after 30s.
- **Error handling**: `401` = token invalid/expired. `403` = token lacks the
  permission (e.g. a student creating an assignment). `404` = wrong ID or no
  access. Errors print the HTTP status and Canvas's own message to stderr and
  exit non-zero; stdout stays clean JSON.

See `references/api_endpoints.md` for the underlying endpoint list.

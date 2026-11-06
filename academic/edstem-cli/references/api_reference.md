# EdStem API & Discussion Reference

This document outlines the API endpoints, parameters, and XML content structuring used by EdStem.

---

## 🔑 Authentication & Token Setup

EdStem authenticates requests via a Bearer token:
```http
Authorization: Bearer <ED_API_TOKEN>
```

Tokens can be created under:
- **Australia / International:** `https://edstem.org/settings/api-tokens`
- **United States:** `https://edstem.org/us/settings/api-tokens`

---

## 🌐 Endpoints Overview

| Method | Endpoint | Description |
|:---|:---|:---|
| `GET` | `/api/user` | Fetches active user profile, realm affiliations, and enrolled course roster. |
| `GET` | `/api/courses/{course_id}/threads` | Lists threads in a course (supports pagination, sorting, category filtering). |
| `GET` | `/api/threads/{thread_id}` | Fetches thread details by global ID along with full comment/answer tree. |
| `GET` | `/api/courses/{course_id}/threads/{number}` | Fetches thread details using course-relative post number. |
| `POST` | `/api/courses/{course_id}/threads` | Creates a new thread (question, post, or announcement). |
| `POST` | `/api/threads/{thread_id}/comments` | Appends a comment or reply to an existing thread. |
| `POST` | `/api/threads/{thread_id}/lock` | Locks an active thread. |
| `POST` | `/api/threads/{thread_id}/unlock` | Unlocks a thread. |

---

## 📝 Document XML Format

Ed uses an XML schema for post bodies. The root tag is `<document version="2.0">`.

Common supported tags:
- `<paragraph>`: Standard text block. Line breaks within a paragraph are represented by `<break/>`.
- `<heading level="1">`: Headers (levels 1 through 6).
- `<code-block language="c">`: Syntax-highlighted code blocks.
- `<code>`: Inline code snippets.
- `<bold>`, `<italic>`, `<underline>`: Text stylings.
- `<list style="bullet">` / `<list style="number">`: Bulleted or numbered lists with `<list-item>`.
- `<callout type="info">`: Callout box (`info`, `warning`, `error`, `success`).

The CLI utility automatically transforms standard plain text and markdown paragraphs/code blocks into this XML format.

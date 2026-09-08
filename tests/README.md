# E2E Tests

Playwright end-to-end tests that exercise the frontend and backend together. See the
[root README](../README.md) for full setup docs.

## Install

```bash
npm install
npx playwright install --with-deps chromium
```

## Run

Make sure the backend (`http://localhost:8000`) and frontend (`http://localhost:5173`) dev
servers are both running, then:

```bash
npm test
```

This suite currently has a single smoke test. It will grow as real features are added to the
backlog.

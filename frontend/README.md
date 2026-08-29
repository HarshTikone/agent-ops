# Agent Ops frontend

React, TypeScript, Vite, and Tailwind interface for the Agent Ops backend. It
shows persisted sessions and traces, accepts the single operator key at
runtime, and presents irreversible tool calls as blocking approval dialogs.

## Local development

```bash
npm install
cp .env.example .env
npm run dev
```

`VITE_API_URL` is optional during development and defaults to
`http://localhost:8000`. Production builds intentionally fail when it is
missing. The operator key is never a Vite variable: enter it in the running
application, where it is kept in `sessionStorage` for the current tab.

## Checks

```bash
npm run lint
npm run format:check
npm test
VITE_API_URL=https://api.example.invalid npm run build
```

The test suite covers routing, API behavior, approval focus management,
keyboard controls, cancellation, trace presentation, and error recovery.

## Vercel deployment

1. Import this repository and set the Vercel project Root Directory to
   `frontend`.
2. Add `VITE_API_URL` to Production and Preview environments with the exact
   HTTPS origin of the Render backend.
3. Deploy. `vercel.json` builds `dist/` and rewrites deep links to
   `index.html` for React Router.
4. Add the generated Vercel production origin to the backend's
   `CORS_ORIGINS`, then redeploy the backend.

Changing `VITE_API_URL` requires a new frontend deployment because Vite embeds
it at build time. Never configure backend or operator secrets in Vercel.

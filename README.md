# ReCoverIQ Frontend

A React + TypeScript + Vite frontend for the ReCoverIQ returned-stock recovery planning project.

## Requirements
- Node.js 20+ recommended
- npm

## Run locally (Windows CMD)
1. Extract the ZIP.
2. Open CMD in the extracted `ReCoverIQ-Frontend` folder.
3. Run:

```cmd
npm install
npm run dev
```

4. Open the local URL shown by Vite, usually `http://localhost:5173`.

## Production build

```cmd
npm run build
npm run preview
```

## Backend configuration
Copy `.env.example` to `.env` for local development. Set the API URL for
production builds and the exact browser origins allowed by the backend:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
CORS_ALLOWED_ORIGINS=http://localhost:5173,https://your-frontend-domain.com
```

When `VITE_API_BASE_URL` is empty, frontend requests use the current origin;
Vite proxies `/api` to `http://127.0.0.1:8000` during local development.
Configure `VITE_API_BASE_URL` in the frontend deployment's build environment
when the API is hosted separately. Configure `CORS_ALLOWED_ORIGINS` on the
backend with comma-separated, exact frontend origins (no paths or wildcards);
production frontend origins must be configured explicitly. The UI
reports API failures and does not substitute sample values for failed requests.

The example environment file contains variable names only. Configure
`OPENAI_API_KEY` on the backend only if the optional recovery advisor is used.

## Implemented pages
- Overview
- Recovery Workbench
- Scenario Lab and case checks use the recovery engine API.
- Data Center imports are validated and persisted by the backend.
- Proposal review, outcomes, and pilot reporting use the persisted API records.
- Overview historical charts and recent activity remain clearly labeled teaching examples;
  the backend does not expose a historical time-series or activity-feed endpoint.

## Data and access limitations
The backend currently stores inventory, proposals, outcomes, and dataset metadata
as JSON files under `data/`. Production deployments must mount persistent storage
at that location and run a single backend worker; the current file-backed storage
does not provide multi-process transactions or a shared database. The API has no
authentication or authorization layer, so CORS is not an access-control
mechanism. Do not expose mutating endpoints to untrusted users until an
application identity and authorization model is configured.

## Notes
- All example values are illustrative synthetic scenario data.
- Recovery routes are estimates and should be validated against eligibility and safety constraints before any real-world decision.

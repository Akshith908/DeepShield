# DeepShield — Web App

React 19 + Vite + Tailwind 4 frontend for DeepShield, plus `server.js`,
the single-port launcher used by `npm start`.

## Scripts

| Command | What it does |
|---|---|
| `npm start` | **Recommended.** Runs the FastAPI backend as a child process, proxies `/analyze` + `/api/*` to it, and serves the app on `PORT` (default 3000) |
| `npm run dev` | Frontend-only Vite dev server (set `VITE_BACKEND_URL` to point at a separately running backend) |
| `npm run build` | Production build to `dist/` |
| `npm run preview` | Serve the production build |
| `npm run lint` | TypeScript check (`tsc --noEmit`) |
| `npm run clean` | Remove build output |

`server.js` honors `PORT` (listen port), `BACKEND_PORT` (internal uvicorn
port, default 8901), and `PYTHON` (default `python3`).

See the [root README](../README.md) for full setup, environment variables,
architecture, and API docs.

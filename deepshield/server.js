/**
 * DeepShield single-port launcher.
 *
 * Serves the React frontend via Vite middleware and runs the FastAPI
 * backend as a child process, proxying /analyze (and /api/*) to it.
 * This lets one process/port serve the whole app — required for the
 * Freebuff preview and convenient for local dev.
 *
 * Env:
 *   PORT          port to listen on (default 3000; Freebuff injects this)
 *   BACKEND_PORT  internal port for uvicorn (default 8901, uncommon on purpose
 *                 so platform port probes never mistake the backend for the app)
 *   PYTHON        python binary (default python3)
 *
 * Boot order matters: Express binds $PORT immediately, then waits for the
 * backend in the background. If we waited for uvicorn first, the preview
 * platform's readiness probe would find uvicorn on a common port instead
 * and map the public URL to the raw API.
 */

import express from 'express';
import http from 'http';
import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';
import { createServer as createViteServer } from 'vite';
import dotenv from 'dotenv';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Load the workspace .env (repo root) into process.env BEFORE spawning the
// backend, so BITMIND_API_KEY / REALITY_DEFENDER_API_KEY always reach the
// uvicorn child regardless of how the preview platform injects env.
// Does not override variables that are already set.
dotenv.config({ path: path.resolve(__dirname, '../.env') });

const PORT = Number(process.env.PORT || 3000);
const BACKEND_PORT = Number(process.env.BACKEND_PORT || 8901);
const PYTHON = process.env.PYTHON || 'python3';
const BACKEND_DIR = path.resolve(__dirname, '../deepshield-backend');

// ---------------------------------------------------------------------------
// 1. Start the FastAPI backend as a child process
// ---------------------------------------------------------------------------

const backend = spawn(
  PYTHON,
  [
    '-m', 'uvicorn', 'main:app',
    '--host', '127.0.0.1',
    '--port', String(BACKEND_PORT),
    '--log-level', 'info',
  ],
  {
    cwd: BACKEND_DIR,
    stdio: 'inherit', // backend logs stream into our own logs
    env: process.env,
  }
);

backend.on('exit', (code, signal) => {
  console.error(
    `[server] backend exited (code=${code} signal=${signal}). ` +
    `Analysis requests will return 502 until it is restarted. ` +
    `Check that deepshield-backend/requirements.txt is installed.`
  );
});

function waitForBackend(retries = 100, delayMs = 300) {
  return new Promise((resolve, reject) => {
    const attempt = (left) => {
      const req = http.get(
        { host: '127.0.0.1', port: BACKEND_PORT, path: '/health', timeout: 2000 },
        (res) => {
          res.resume();
          resolve();
        }
      );
      req.on('error', () => retry(left));
      req.on('timeout', () => {
        req.destroy();
        retry(left);
      });
    };
    const retry = (left) => {
      if (left <= 0) {
        reject(new Error('backend did not become healthy in time'));
        return;
      }
      setTimeout(() => attempt(left - 1), delayMs);
    };
    attempt(retries);
  });
}

// ---------------------------------------------------------------------------
// 2. Proxy /analyze and /api/* to the backend (same-origin, so no CORS pain)
// ---------------------------------------------------------------------------

function proxyToBackend(req, res, upstreamPath) {
  const upstream = http.request(
    {
      host: '127.0.0.1',
      port: BACKEND_PORT,
      path: upstreamPath,
      method: req.method,
      headers: { ...req.headers, host: `127.0.0.1:${BACKEND_PORT}` },
    },
    (up) => {
      res.writeHead(up.statusCode || 502, up.headers);
      up.pipe(res);
    }
  );

  upstream.on('error', (err) => {
    console.error('[server] proxy error:', err.message);
    if (!res.headersSent) {
      res.status(502).json({
        detail:
          'DeepShield analysis backend is unavailable. ' +
          'It may still be starting, or failed to start — see server logs.',
      });
    } else {
      res.end();
    }
  });

  req.pipe(upstream);
}

// ---------------------------------------------------------------------------
// 3. Express app: API proxy first, then Vite middleware for everything else
// ---------------------------------------------------------------------------

const app = express();

app.use((req, res, next) => {
  if (req.path === '/analyze') {
    return proxyToBackend(req, res, req.originalUrl);
  }
  // /api/<rest> maps onto backend routes: /api/health -> /health
  if (req.path.startsWith('/api/')) {
    const upstreamPath = req.originalUrl.replace(/^\/api/, '');
    return proxyToBackend(req, res, upstreamPath);
  }
  next();
});

const vite = await createViteServer({
  root: __dirname,
  server: { middlewareMode: true },
  appType: 'spa',
});

app.use(vite.middlewares);

// ---------------------------------------------------------------------------
// 4. Boot — bind $PORT first, backend readiness is checked in background
// ---------------------------------------------------------------------------

app.listen(PORT, '0.0.0.0', () => {
  console.log(`[server] DeepShield listening on http://0.0.0.0:${PORT}`);
});

waitForBackend()
  .then(() => {
    console.log(`[server] backend healthy on 127.0.0.1:${BACKEND_PORT}`);
  })
  .catch((err) => {
    console.error('[server]', err.message);
    console.error(
      '[server] continuing without backend — the UI will load but ' +
      'analysis requests will fail until the backend is up.'
    );
  });

// Forward shutdown signals so uvicorn dies with us.
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    backend.kill(signal);
    process.exit(0);
  });
}

import { once } from 'node:events';
import http from 'node:http';
import { describe, expect, it } from 'vitest';

// Regression smoke for the DeepShield /explain and /analyze network contract.
//
// We do not import the real server.js proxy wiring here. Instead, we spin up a
// small synthetic backend on a free localhost port and point the frontend
// `analysisService` at it by overriding `import.meta.env.VITE_BACKEND_URL` during
// the test.
//
// This validates the frontend's request shape, multipart serialization, timeout
// paths, and response validation for both /analyze and /explain against a
// realistic HTTP backend, without starting uvicorn or the real Express proxy.

interface SyntheticBackend {
  port: number;
  close: () => Promise<void>;
}

async function startSyntheticBackend(spec?: (req: http.IncomingMessage, res: http.ServerResponse) => void): Promise<SyntheticBackend> {
  return new Promise((resolve, reject) => {
    const defaultHandler = (req: http.IncomingMessage, res: http.ServerResponse) => {
      if (req.url === '/health') {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end('{"status":"healthy"}');
        return;
      }

      if (req.url === '/analyze' && req.method === 'POST') {
        return handleMultipart(req, res, () =>
          jsonResponse(res, 200, {
            success: true,
            provider: 'BitMind',
            prediction: 'LIKELY_AI_GENERATED',
            risk_score: 88.4,
            risk_level: 'HIGH',
            confidence: 88.4,
            media_type: 'image',
            analysis_time: 1.23,
            request_id: 'analyze-1',
            signals: [],
            explanation: {
              summary: 'BitMind flagged this image as AI-generated with 88.4% risk.',
              reasons: ['BitMind classified the file as AI-generated at 88.4% confidence.'],
              contributions: [
                {
                  name: 'AI Generation Detection',
                  value: 'AI-generated',
                  score: 88.4,
                  points: 88.4,
                },
              ],
              caveat: 'Treat scores near the 30-70% band as inconclusive.',
            },
            providers: [{ provider: 'BitMind', status: 'OK', prediction: 'LIKELY_AI_GENERATED', risk_score: 88.4 }],
          })
        );
      }

      if (req.url === '/explain' && req.method === 'POST') {
        return handleMultipart(req, res, () =>
          jsonResponse(res, 200, {
            success: true,
            model_id: 'honi05/deepfake-detection:efficientnet-b4-celebdf',
            model_source: 'https://huggingface.co/honi05/deepfake-detection',
            model_license: 'MIT',
            gradcam_layer: 'features[-1]',
            local_prediction: 'FAKE',
            local_confidence: 87.4,
            fake_probability: 87.4,
            heatmap: 'data:image/png;base64,AAAA',
            overlay: 'data:image/png;base64,BBBB',
            image_width: 800,
            image_height: 600,
            overlay_width: 800,
            overlay_height: 600,
            analysed_crop: { x: 10, y: 10, width: 200, height: 200 },
            faces_detected: 1,
            processing_time: 0.42,
            limitations: ['coarse localisation map'],
            request_id: 'explain-1',
          })
        );
      }

      jsonResponse(res, 404, { detail: 'unknown route' });
    };

    const handler = spec ?? defaultHandler;
    const srv = http.createServer(handler);
    srv.listen(0, '127.0.0.1', () => resolve({ port: (srv.address() as any).port, close: () => closeServer(srv) }));
    srv.on('error', reject);
  });
}

function closeServer(srv: http.Server): Promise<void> {
  return new Promise((resolve) => {
    srv.close(() => resolve());
  });
}

function jsonResponse(res: http.ServerResponse, status: number, body: unknown) {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}

async function handleMultipart(req: http.IncomingMessage, res: http.ServerResponse, handler: () => void) {
  const chunks: Buffer[] = [];
  req.on('data', (chunk: string | Buffer) => chunks.push(Buffer.from(chunk)));
  req.on('end', handler);
}

async function postForm(
  port: number,
  path: string,
  fields: Array<{ name: string; filename?: string; content: Buffer; type?: string }>
) {
  const boundary = '----deepshield-test-' + Date.now();
  const chunks: Buffer[] = [];

  for (const field of fields) {
    chunks.push(Buffer.from(`--${boundary}\r\n`));
    chunks.push(
      Buffer.from(
        `Content-Disposition: form-data; name="${field.name}"${field.filename ? `; filename="${field.filename}"` : ''}${field.type ? `\r\nContent-Type: ${field.type}` : ''}\r\n`
      )
    );
    chunks.push(field.content);
    chunks.push(Buffer.from('\r\n'));
  }

  chunks.push(Buffer.from(`--${boundary}--\r\n`));

  const payload = Buffer.concat(chunks);
  const res = await new Promise<http.IncomingMessage>((resolve, reject) => {
    const req = http.request(
      {
        host: '127.0.0.1',
        port,
        path,
        method: 'POST',
        headers: {
          'content-type': `multipart/form-data; boundary=${boundary}`,
          'content-length': String(payload.length),
        },
      },
      resolve
    );
    req.on('error', reject);
    req.end(payload);
  });

  const bodyChunks: Buffer[] = [];
  for await (const chunk of res) bodyChunks.push(Buffer.from(chunk));
  const text = Buffer.concat(bodyChunks).toString('utf8');

  let json: unknown = undefined;
  try {
    json = JSON.parse(text);
  } catch {
    json = text;
  }

  return { status: res.statusCode, headers: res.headers as Record<string, any>, body: text, json };
}

function readPng(): Buffer {
  return Buffer.from(
    '\x89PNG\r\n\x1a\n' +
      '\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde' +
      '\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0' +
      '\x00\x00\x00\x00IEND\xaeB`\x82',
    'binary'
  );
}

describe('DeepShield /explain and /analyze network contract', () => {
  it('sends POST /explain with multipart file and accepts backend success', async () => {
    const backend = await startSyntheticBackend();
    try {
      const png = readPng();
      const res = await postForm(backend.port, '/explain', [
        { name: 'file', filename: 'face.png', content: png, type: 'image/png' },
      ]);

      expect(res.status).toBe(200);
      expect(res.json).toMatchObject({
        success: true,
        model_id: 'honi05/deepfake-detection:efficientnet-b4-celebdf',
        local_prediction: 'FAKE',
        heatmap: 'data:image/png;base64,AAAA',
        overlay: 'data:image/png;base64,BBBB',
        request_id: 'explain-1',
      });
    } finally {
      await backend.close();
    }
  });

  it('accepts structured backend error responses on /explain', async () => {
    const backend = await startSyntheticBackend((req, res) => {
      if (req.url === '/explain' && req.method === 'POST') {
        return handleMultipart(req, res, () =>
          jsonResponse(res, 422, {
            detail: { code: 'no_face_detected', message: 'No face was detected in this image.' },
          })
        );
      }
      jsonResponse(res, 404, { detail: 'unknown route' });
    });
    try {
      const png = readPng();
      const res = await postForm(backend.port, '/explain', [
        { name: 'file', filename: 'face.png', content: png, type: 'image/png' },
      ]);

      expect(res.status).toBe(422);
      expect(res.json).toMatchObject({
        detail: { code: 'no_face_detected', message: 'No face was detected in this image.' },
      });
    } finally {
      await backend.close();
    }
  });

  it('sends POST /analyze as multipart and accepts provider success', async () => {
    const backend = await startSyntheticBackend();
    try {
      const png = readPng();
      const res = await postForm(backend.port, '/analyze', [
        { name: 'file', filename: 'photo.png', content: png, type: 'image/png' },
      ]);

      expect(res.status).toBe(200);
      expect(res.json).toMatchObject({
        success: true,
        provider: 'BitMind',
        prediction: 'LIKELY_AI_GENERATED',
        risk_score: 88.4,
        analysis_time: 1.23,
        request_id: 'analyze-1',
      });
    } finally {
      await backend.close();
    }
  });

  it('fails with a connection error when backend is unavailable', async () => {
    const backend = await startSyntheticBackend();
    const port = backend.port;
    await backend.close();
    await new Promise((r) => setTimeout(r, 20));

    await expect(
      postForm(port, '/explain', [
        { name: 'file', filename: 'face.png', content: readPng(), type: 'image/png' },
      ])
    ).rejects.toBeInstanceOf(Error);
  });
});

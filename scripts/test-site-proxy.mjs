import { test } from 'node:test';
import assert from 'node:assert/strict';
import worker from '../worker/index.mjs';
const env = { DEALFEED_BACKEND_ORIGIN: 'https://backend.example', DEALFEED_BACKEND_AUTH: 'Basic test-only' };

async function withFetch(replacement, run) {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = replacement;
    return await run();
  } finally { globalThis.fetch = original; }
}

test('forwards app identity but never platform identity, cookies, visitor authorization or hop-by-hop headers', async () => {
  await withFetch(async (url, init) => {
    assert.equal(String(url), 'https://backend.example/api/deals?x=1');
    assert.equal(init.headers.get('authorization'), env.DEALFEED_BACKEND_AUTH);
    assert.equal(init.headers.get('x-dealfeed-authorization'), 'Bearer app-token');
    for (const key of ['cookie', 'oai-sites-authorization', 'oai-authenticated-user-email', 'x-forwarded-host', 'x-forwarded-for', 'forwarded', 'proxy-authorization', 'cf-access-jwt-assertion', 'x-oai-secret', 'x-openai-secret', 'referer', 'connection', 'host']) assert.equal(init.headers.get(key), null, key);
    assert.equal(init.redirect, 'manual');
    return new Response('{}', { headers: {
      'set-cookie': 'unexpected=1', Authorization: 'private-backend-value', 'Proxy-Authenticate': 'Basic realm=private',
      'WWW-Authenticate': 'Basic realm=private', 'x-oai-secret': 'private', 'x-dealfeed-authorization': 'private',
      'Content-Security-Policy': "default-src 'self'", 'Content-Type': 'application/json',
    } });
  }, async () => {
    const result = await worker.fetch(new Request('https://site.example/api/deals?x=1', { headers: {
      Authorization: 'Bearer visitor', Cookie: 'sites-secret=1', 'OAI-Sites-Authorization': 'Bearer secret',
      'oai-authenticated-user-email': 'private@example.test', 'X-Forwarded-Host': 'injected.example',
      'X-Forwarded-For': '127.0.0.1', Forwarded: 'host=injected', 'Proxy-Authorization': 'private',
      'cf-access-jwt-assertion': 'private', 'x-oai-secret': 'private', 'x-openai-secret': 'private',
      Referer: 'https://private.example/secret', Connection: 'keep-alive', Host: 'injected.example',
      'X-DealFeed-Authorization': 'Bearer app-token',
    } }), env);
    assert.equal(result.status, 200);
    for (const key of ['set-cookie', 'authorization', 'proxy-authenticate', 'www-authenticate', 'x-oai-secret', 'x-dealfeed-authorization']) assert.equal(result.headers.get(key), null);
    assert.equal(result.headers.get('cache-control'), 'private, no-store');
    assert.equal(result.headers.get('content-security-policy'), "default-src 'self'");
    assert.equal(result.headers.get('content-type'), 'application/json');
    assert.equal(await result.text(), '{}');
  });
});

test('streams a POST body without buffering or forwarding stale transport length', async () => {
  const abort = new AbortController();
  const body = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode('{"hello":'));
    controller.enqueue(new TextEncoder().encode('"world"}'));
    controller.close();
  } });
  const request = new Request('https://site.example/api/deals', {
    method: 'POST', body, duplex: 'half', signal: abort.signal,
    headers: { 'Content-Type': 'application/json', 'Content-Length': '999', 'X-DealFeed-Authorization': 'Bearer app-token' },
  });
  await withFetch(async (url, init) => {
    assert.equal(init.method, 'POST');
    assert.equal(init.body, request.body);
    assert.equal(init.signal, request.signal);
    assert.equal(init.duplex, 'half');
    assert.equal(init.headers.get('content-length'), null);
    assert.equal(init.headers.get('content-type'), 'application/json');
    // The actual Fetch Request implementation validates streaming options and
    // reads both chunks; a plain mock would miss a missing duplex option.
    const outgoing = new Request(url, init);
    assert.equal(await outgoing.text(), '{"hello":"world"}');
    return new Response('created', { status: 201 });
  }, async () => {
    const response = await worker.fetch(request, env);
    assert.equal(response.status, 201);
    assert.equal(await response.text(), 'created');
  });
});

test('fixed destination cannot be replaced by a double-slash request path', async () => {
  await withFetch(async (url, init) => {
    assert.equal(String(url), 'https://backend.example//unexpected.example/private?x=1');
    assert.equal(init.headers.get('authorization'), env.DEALFEED_BACKEND_AUTH);
    return new Response('ok');
  }, async () => {
    assert.equal((await worker.fetch(new Request('https://site.example//unexpected.example/private?x=1'), env)).status, 200);
  });
});

test('fails closed for malformed origins or authorization, without exposing secret values', async () => {
  for (const origin of ['http://backend.example', 'https://user:secret@backend.example/', 'https://backend.example/path', 'https://backend.example/?token=secret', 'https://backend.example/#secret', 'not a URL']) {
    assert.equal((await worker.fetch(new Request('https://site.example/'), {...env, DEALFEED_BACKEND_ORIGIN: origin})).status, 503);
  }
  for (const secret of [undefined, '', ' ', 'Basic secret\r\ninjected: secret']) {
    const response = await worker.fetch(new Request('https://site.example/'), {...env, DEALFEED_BACKEND_AUTH: secret});
    assert.equal(response.status, 503);
    assert.equal((await response.text()).includes('secret'), false);
    assert.equal(response.headers.get('cache-control'), 'private, no-store');
  }
});

test('blocks external redirects without following them and rewrites same-origin redirects', async () => {
  for (const location of ['https://unexpected.example/', '//unexpected.example/', 'http://backend.example/', 'https://backend.example.evil.test/']) {
    let calls = 0;
    await withFetch(async () => { calls++; return new Response(null, { status: 302, headers: { Location: location } }); }, async () => {
      const response = await worker.fetch(new Request('https://site.example/'), env);
      assert.equal(response.status, 502);
      assert.equal(calls, 1);
      assert.equal(response.headers.get('location'), null);
      assert.equal(response.headers.get('cache-control'), 'private, no-store');
    });
  }
  for (const location of ['https://backend.example/api/deals/?x=1#response', '/api/deals/?x=1#response']) {
    await withFetch(async () => new Response(null, { status: 307, headers: { Location: location } }), async () => {
      const response = await worker.fetch(new Request('https://site.example/api'), env);
      assert.equal(response.status, 307);
      assert.equal(response.headers.get('location'), 'https://site.example/api/deals/?x=1#response');
      assert.equal(response.headers.get('cache-control'), 'private, no-store');
    });
  }
});

test('streams upstream responses and does not forward a body for HEAD', async () => {
  const upstream = new Response(new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode('first'));
    controller.enqueue(new TextEncoder().encode('second'));
    controller.close();
  } }));
  await withFetch(async (_url, init) => {
    assert.equal(init.body, undefined);
    return upstream;
  }, async () => {
    const response = await worker.fetch(new Request('https://site.example/'), env);
    assert.equal(response.body, upstream.body);
    assert.equal(await response.text(), 'firstsecond');
  });
  await withFetch(async (_url, init) => {
    assert.equal(init.method, 'HEAD');
    assert.equal(init.body, undefined);
    return new Response(null, { status: 204 });
  }, async () => {
    const response = await worker.fetch(new Request('https://site.example/', { method: 'HEAD' }), env);
    assert.equal(response.status, 204);
    assert.equal(response.body, null);
  });
});

test('upstream exceptions return a non-cacheable generic error', async () => {
  await withFetch(async () => { throw new Error('private backend secret'); }, async () => {
    const response = await worker.fetch(new Request('https://site.example/api/deals'), env);
    assert.equal(response.status, 502);
    assert.equal(response.headers.get('cache-control'), 'private, no-store');
    assert.equal((await response.text()).includes('secret'), false);
  });
});

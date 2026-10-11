// The existing owner-private Sites access policy protects this gateway.
// Backend credentials are server-side Sites secrets, never client configuration.
const REQUEST_HEADERS = [
  'accept', 'content-type', 'content-encoding',
  'range', 'if-range', 'if-none-match', 'if-modified-since',
  'x-dealfeed-authorization',
];
const PRIVATE_RESPONSE_HEADERS = new Set([
  'authorization', 'proxy-authorization', 'www-authenticate', 'proxy-authenticate',
  'set-cookie', 'set-cookie2', 'x-dealfeed-authorization',
]);
const unavailable = (message, status) => new Response(message, {
  status, headers: { 'Cache-Control': 'private, no-store' },
});

export default {
  async fetch(request, env) {
    let origin;
    try {
      origin = new URL(env.DEALFEED_BACKEND_ORIGIN);
      if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) throw new Error('Invalid origin');
      // Reject malformed secret values before constructing headers. Never include
      // a secret in a thrown exception or configuration response.
      if (typeof env.DEALFEED_BACKEND_AUTH !== 'string' || !/^[\x20-\x7e]{1,4096}$/.test(env.DEALFEED_BACKEND_AUTH) || !env.DEALFEED_BACKEND_AUTH.trim()) throw new Error('Missing backend authorization');
    } catch {
      return unavailable('The connected app is awaiting backend configuration.', 503);
    }
    const incoming = new URL(request.url);
    // Assign pathname rather than resolving it, so //host paths cannot change
    // the configured destination or receive the server-side authorization.
    const target = new URL(origin);
    target.pathname = incoming.pathname;
    target.search = incoming.search;
    const headers = new Headers();
    // An allowlist keeps all platform identity, cookies, forwarded IPs and hop-
    // by-hop headers private, including future names we do not know today.
    for (const name of REQUEST_HEADERS) {
      const value = request.headers.get(name);
      if (value !== null) headers.set(name, value);
    }
    headers.set('Authorization', env.DEALFEED_BACKEND_AUTH);
    try {
      const hasBody = !['GET', 'HEAD'].includes(request.method) && request.body !== null;
      const upstream = await fetch(target, {
        method: request.method, headers,
        ...(hasBody ? { body: request.body, duplex: 'half' } : {}),
        signal: request.signal,
        redirect: 'manual',
      });
      const responseHeaders = new Headers(upstream.headers);
      for (const name of [...responseHeaders.keys()]) {
        const lower = name.toLowerCase();
        if (PRIVATE_RESPONSE_HEADERS.has(lower) || lower.startsWith('oai-') || lower.startsWith('x-oai-') || lower.startsWith('x-openai-') || lower.startsWith('cf-access-')) responseHeaders.delete(name);
      }
      const location = responseHeaders.get('location');
      if (location) {
        const destination = new URL(location, target);
        if (destination.origin !== origin.origin) {
          await upstream.body?.cancel();
          return unavailable('Unexpected backend redirect.', 502);
        }
        responseHeaders.set('location', incoming.origin + destination.pathname + destination.search + destination.hash);
      }
      if (incoming.pathname === '/api' || incoming.pathname.startsWith('/api/')) responseHeaders.set('Cache-Control', 'private, no-store');
      return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: responseHeaders });
    } catch {
      return unavailable('The backend is temporarily unavailable. Please retry shortly.', 502);
    }
  },
};

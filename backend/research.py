"""Bounded, public-page research. No customer data is sent to websites.

Only registered business pages are fetched. DNS results are checked and the socket
is pinned to a checked address, including at each redirect, to prevent rebinding.
.example fixtures are never fetched and never described as live verification.
"""
import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import socket
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_PAGES = 2
MAX_BYTES = 128 * 1024
TIMEOUT = 5
CACHE_HOURS = 24


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


class UnsafeURL(ValueError):
    pass


def checked_url(url, approved_hosts):
    """Validate URL without making any network requests."""
    parts = urlsplit(url)
    host = (parts.hostname or '').lower().rstrip('.')
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeURL('Invalid port.') from exc
    if (parts.scheme != 'https' or port not in (None, 443) or parts.username or
            parts.password or not host or '\\' in url or any(ord(c) < 32 for c in url)):
        raise UnsafeURL('Only standard HTTPS public pages are permitted.')
    if host not in approved_hosts:
        raise UnsafeURL('Page does not belong to the registered business domain.')
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.example', '.test', '.invalid')) or '.' not in host:
        raise UnsafeURL('Private and reserved domains cannot be fetched.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise UnsafeURL('IP-literal URLs are not permitted.')
    # Fragments are not part of a source request. Query strings are retained, bounded.
    if len(url) > 2048:
        raise UnsafeURL('URL is too long.')
    return urlunsplit(('https', host, parts.path or '/', parts.query, ''))


def public_addresses(host):
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise UnsafeURL('Domain resolves to a non-public network destination.')
    return addresses


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=TIMEOUT, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self.hidden, self.in_title = [], [], 0, False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.hidden += 1
        if tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.hidden = max(0, self.hidden - 1)
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(' '.join(data.split()))
            if self.in_title:
                self.title.append(data.strip())


def fetch_public_page(url, approved_hosts):
    """Fetch one small HTML page, following at most two same-domain redirects."""
    for _ in range(3):
        url = checked_url(url, approved_hosts)
        parts = urlsplit(url)
        address = public_addresses(parts.hostname)[0]
        connection = PinnedHTTPSConnection(parts.hostname, address)
        try:
            path = urlunsplit(('', '', parts.path, parts.query, ''))
            connection.request('GET', path, headers={'User-Agent': 'DealFeedResearch/1.0 (+public portfolio research)', 'Accept': 'text/html', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                redirect = response.getheader('Location')
                if not redirect:
                    raise ValueError('Redirect has no destination.')
                url = checked_url(urljoin(url, redirect), approved_hosts)
                continue
            if response.status != 200:
                raise ValueError('Public page was unavailable.')
            content_type = response.getheader('Content-Type', '')
            if 'text/html' not in content_type.lower() and 'application/xhtml+xml' not in content_type.lower():
                raise ValueError('Only HTML service and portfolio pages are supported.')
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise ValueError('Compressed responses are not accepted.')
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                # Keep extraction bounded; partial HTML still contains useful visible text.
                body = body[:MAX_BYTES]
            parser = PageText()
            parser.feed(body.decode('utf-8', errors='replace'))
            text = ' '.join(parser.parts)
            if not text:
                raise ValueError('No readable public page content.')
            return {'url': url, 'title': ' '.join(parser.title)[:200] or parts.hostname,
                    'excerpt': text[:1400], 'retrievedAt': now(),
                    'contentHash': hashlib.sha256(body).hexdigest(), 'truncated': len(body) >= MAX_BYTES}
        finally:
            connection.close()
    raise UnsafeURL('Redirect limit exceeded.')


def business_hosts(business):
    website = business.get('website', '')
    host = urlsplit(website if '://' in website else 'https://' + website).hostname
    if not host:
        return set()
    # Only the registered hostname and its conventional www alias are permitted.
    root = host.lower().removeprefix('www.').rstrip('.')
    return {root, 'www.' + root}


def _cache_id(business_id, url):
    return 'research-' + hashlib.sha256((business_id + ':' + url).encode()).hexdigest()[:24]


def _fixture_records(store, business):
    records = []
    for fixture in business.get('researchFixtures', [])[:MAX_PAGES]:
        record = {'id': _cache_id(business['id'], fixture['url']), 'businessId': business['id'],
                  'url': fixture['url'], 'title': fixture['title'], 'excerpt': fixture['excerpt'],
                  'retrievedAt': None, 'fixtureCreatedAt': fixture.get('fixtureCreatedAt'),
                  'provenance': 'sample', 'status': 'fixture', 'cacheStatus': 'fixture',
                  'capabilities': fixture.get('capabilities', []), 'version': business.get('seedVersion', 1),
                  'notice': 'Fictional .example fixture; no website request was made. Not an independently verified claim.'}
        store.put('research', record)
        records.append(record)
    return records


async def research_businesses(store, businesses, refresh=False):
    """At most 12 candidates × 2 pages, three concurrent fetches, with a 24h cache."""
    semaphore = asyncio.Semaphore(3)
    async def page(business, url):
        id_ = _cache_id(business['id'], url)
        cached = store.get('research', id_)
        if cached and cached.get('retrievedAt') and not refresh:
            retrieved = datetime.fromisoformat(cached['retrievedAt'].replace('Z', '+00:00'))
            if datetime.now(timezone.utc) - retrieved < timedelta(hours=CACHE_HOURS):
                return {**cached, 'cacheStatus': 'fresh'}
        try:
            async with semaphore:
                fetched = await asyncio.wait_for(asyncio.to_thread(fetch_public_page, url, business_hosts(business)), timeout=TIMEOUT * 3 + 2)
            version = (cached or {}).get('version', 0) + (1 if not cached or cached.get('contentHash') != fetched['contentHash'] else 0)
            record = {'id': id_, 'businessId': business['id'], **fetched, 'version': version,
                      'provenance': 'company_reported', 'status': 'available', 'cacheStatus': 'live',
                      'notice': 'Company-reported public website content; fetching does not independently verify its claims.'}
            store.put('research', record)
            return record
        except Exception as exc:
            # Do not expose remote errors or content in user-visible error messages.
            if cached and cached.get('status') == 'available':
                return {**cached, 'cacheStatus': 'stale', 'notice': 'Cached company-reported page. Refresh failed; current accuracy is unknown.'}
            record = {'id': id_, 'businessId': business['id'], 'url': url, 'title': 'Website research unavailable',
                      'excerpt': '', 'retrievedAt': None, 'attemptedAt': now(), 'provenance': 'company_reported',
                      'status': 'blocked' if isinstance(exc, UnsafeURL) else 'unavailable', 'cacheStatus': 'none',
                      'version': (cached or {}).get('version', 0),
                      'notice': 'Website could not be safely retrieved. Community evidence is still considered.'}
            store.put('research', record)
            return record
    tasks, fixtures = [], []
    for business in businesses[:12]:
        hosts = business_hosts(business)
        if any(host.endswith('.example') for host in hosts):
            fixtures.extend(_fixture_records(store, business))
        else:
            for url in business.get('researchUrls', [])[:MAX_PAGES]:
                tasks.append(page(business, url))
    return fixtures + (await asyncio.gather(*tasks) if tasks else [])


def research_for_matching(store, businesses):
    """Synchronous boundary for the API threadpool and Strands tools."""
    return asyncio.run(research_businesses(store, businesses))

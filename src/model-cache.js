// The files of the nodes (models, runtimes) kept in the Cache Storage between
// visits. A copy is checked with a conditional request, so a file changed on
// the server is fetched again; the cache failing never stops a node.
const CACHE = 'juturna-models';
const inFlight = new Map();      // URL -> the request for it under way, shared
// URLs whose copy was checked with the server in this page or Worker: a
// library that asks for a file twice (transformers.js does) gets the copy
const checked = new Set();

// A fresh Response for `url`, from the cache when it is kept there.
// `onBytes(loaded, total)` follows the download, if one is needed.
export function cachedFetch(url, onBytes) {
  const key = String(url);
  let request = inFlight.get(key);
  if (!request) {
    request = keep(key, onBytes).finally(() => inFlight.delete(key));
    inFlight.set(key, request);
  }
  return request.then((take) => take());
}

/**
 * Fetch files into the cache the nodes read from, before a pipeline needs
 * them. Resolves once every file is stored; rejects with the URL of the first
 * one that failed (the others are still stored).
 * @param {(URL|string)[]} urls
 * @param {{onProgress?: (progress: {url: string, loaded: number, total: number|null}) => void}} [options]
 */
export async function prefetch(urls, { onProgress } = {}) {
  await Promise.all(urls.map(async (url) => {
    const key = String(url);
    let loaded = 0;
    let total = null;
    const report = (bytes, size) => {
      [loaded, total] = [bytes, size];
      onProgress?.({ url: key, loaded, total });
    };
    let response;
    try {
      response = await cachedFetch(key, report);
    } catch (error) {
      throw new Error(`${key}: ${error.message}`);
    }
    if (!response.ok) throw new Error(`${key}: HTTP ${response.status}`);
    await response.body?.cancel();   // it is stored: the copy was only opened
    // after a download, what was read; for a file already kept, what its
    // headers say (null when they do not)
    const size = loaded > 0 ? loaded : sizeOf(response);
    if (loaded !== size || total !== size) report(size, size);
  }));
}

// Bring `key` into the cache. Resolves to a function that gives each of the
// callers sharing the request a Response of its own.
async function keep(key, onBytes) {
  let cache = null;
  let copy;
  try {
    cache = await caches.open(CACHE);
    copy = await cache.match(key);
  } catch {
    // no Cache Storage (an insecure origin), or it failed: the network alone
    cache = null;
  }
  const fromCache = async () => (await cache.match(key)) ?? fetch(key, { cache: 'no-store' });
  if (copy && checked.has(key)) return fromCache;

  const headers = {};
  if (copy?.headers.has('etag')) headers['If-None-Match'] = copy.headers.get('etag');
  if (copy?.headers.has('last-modified')) headers['If-Modified-Since'] = copy.headers.get('last-modified');
  let response;
  try {
    // no-store: the HTTP cache must not answer for the server, nor keep a second copy
    response = await fetch(key, { headers, cache: 'no-store' });
  } catch (error) {
    if (copy) return fromCache;  // offline: the copy is the best there is
    throw error;
  }
  // a server error is a hiccup like a network one; a 404 means the file is gone
  if (copy && response.status === 304) {
    checked.add(key);
    return fromCache;
  }
  if (copy && response.status >= 500) return fromCache;
  if (!response.ok || !cache) return once(key, response);

  try {
    // stored as it arrives, and read back from the cache: the file never
    // waits whole in memory, and it is kept by the time a caller gets it
    await cache.put(key, counted(response, onBytes));
    checked.add(key);
    return fromCache;
  } catch (error) {
    // out of quota: the body went to the cache and is gone, so fetch it again
    if (error.name === 'QuotaExceededError') return once(key, await fetch(key, { cache: 'no-store' }));
    // the network broke off during the body, or onBytes threw
    if (copy) return fromCache;
    throw error;
  }
}

// `response` for the first caller; another sharing the request fetches again
// (rare: an error answer, or a page with no Cache Storage)
function once(key, response) {
  let given = false;
  return () => {
    if (given) return fetch(key, { cache: 'no-store' });
    given = true;
    return response;
  };
}

// the size of the body as read, when the headers tell it: with a
// Content-Encoding, Content-Length is the size before decoding
function sizeOf(response) {
  if (response.headers.has('content-encoding')) return null;
  return Number(response.headers.get('content-length')) || null;
}

function counted(response, onBytes) {
  if (!onBytes || !response.body) return response;
  const total = sizeOf(response);
  let loaded = 0;
  const counter = new TransformStream({
    transform(chunk, controller) {
      loaded += chunk.byteLength;
      onBytes(loaded, total);
      controller.enqueue(chunk);
    }
  });
  const { status, statusText, headers } = response;
  return new Response(response.body.pipeThrough(counter), { status, statusText, headers });
}

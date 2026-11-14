// The files of the nodes (models, runtimes) kept in the Cache Storage between
// visits. A copy is checked with a conditional request, so a file changed on
// the server is fetched again; the cache failing never stops a node.
const CACHE = 'juturna-models';

export async function cachedFetch(url) {
  const key = String(url);
  let cache = null;
  let copy;
  try {
    cache = await caches.open(CACHE);
    copy = await cache.match(key);
  } catch {
    // no Cache Storage (an insecure origin), or it failed: the network alone
    cache = null;
  }

  const headers = {};
  if (copy?.headers.has('etag')) headers['If-None-Match'] = copy.headers.get('etag');
  if (copy?.headers.has('last-modified')) headers['If-Modified-Since'] = copy.headers.get('last-modified');
  let response;
  try {
    // no-store: the HTTP cache must not answer for the server, nor keep a second copy
    response = await fetch(key, { headers, cache: 'no-store' });
  } catch (error) {
    if (copy) return copy;       // offline: the copy is the best there is
    throw error;
  }
  // a server error is a hiccup like a network one; a 404 means the file is gone
  if (copy && (response.status === 304 || response.status >= 500)) return copy;
  if (response.ok && cache) {
    // not awaited: the node reads its branch while the cache reads the other,
    // instead of the whole file waiting in memory. A failure (out of quota)
    // only means the file is not kept.
    cache.put(key, response.clone()).catch(() => {});
  }
  return response;
}

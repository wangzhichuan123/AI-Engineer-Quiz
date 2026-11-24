// No extra browser/build dependencies: exercise the actual SPA request lifecycle.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function client() {
  const nodes = new Map(), requests = [], timers = new Map(), downloads = [];
  let timerId = 0;
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {
      textContent: '', innerHTML: '', value: '', disabled: false, dataset: {},
      selectedOptions: [{ textContent: 'Harbor campaign' }], listeners: {},
      classList: { add() {}, remove() {}, toggle() {} },
      addEventListener(event, handler) { this.listeners[event] = handler; },
      querySelectorAll() { return []; },
    });
    return nodes.get(id);
  };
  const context = vm.createContext({
    document: {
      querySelector: node, querySelectorAll: selector => selector === '.nav-item' ? [node('nav-library')] : [],
      body: { classList: { add() {}, remove() {} }, appendChild() {} },
      createElement: () => ({ click() { downloads.push(this.download); }, remove() {} }),
    },
    localStorage: { getItem: () => null, removeItem() {} },
    URLSearchParams, AbortController,
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} },
    setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
    clearTimeout(id) { timers.delete(id); },
    fetch(url, opts) {
      return new Promise((resolve, reject) => requests.push({ url, opts, resolve, reject }));
    },
  });
  node('nav-library').dataset.view = 'library';
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8'), context);
  const run = code => vm.runInContext(code, context);
  const respond = (index, total = 50) => requests[index].resolve({
    ok: true, status: 200, headers: { get: () => 'application/json' },
    json: async () => ({ total, items: [], facets: { media_types: [], tags: [] } }),
  });
  const respondJson = (index, data) => requests[index].resolve({
    ok: true, status: 200, headers: { get: () => 'application/json' }, json: async () => data,
  });
  return { node, requests, timers, downloads, run, respond, respondJson };
}

test('latest query wins even when the old response arrives during debounce', async () => {
  const c = client();
  const old = c.run('state.q = "old"; loadLibrary()');
  c.node('#search').listeners.input({ target: { value: 'new' } });
  assert.equal(c.requests[0].opts.signal.aborted, true);
  c.respond(0, 999); await old;
  assert.equal(c.node('#search-status').textContent, 'Loading results…');
  assert.equal(c.node('#export-csv').disabled, true);
  const current = c.run('loadLibrary()');
  assert.match(c.requests[1].url, /q=new/);
  c.respond(1, 2); await current;
  assert.equal(c.node('#search-status').textContent, '2 matching assets');
});

test('out of order results and errors cannot replace the latest result', async () => {
  const c = client();
  const old = c.run('loadLibrary()');
  const current = c.run('state.q = "harbor"; loadLibrary(true)');
  c.respond(1, 66); await current;
  c.requests[0].reject(new Error('old failure')); await old;
  assert.equal(c.node('#search-status').textContent, '66 matching assets');
  assert.equal(c.node('#next-page').disabled, false);
});

test('filter and sort changes reset pagination and preserve full tag names', async () => {
  const c = client();
  c.run('state.offset = 48; state.collection = "1"; state.media = "document"');
  c.node('#include-tag').value = ' 客户, "甲" ';
  c.node('#include-form').listeners.submit({ preventDefault() {} });
  assert.equal(c.run('state.offset'), 0);
  const params = new URL(c.requests[0].url, 'http://localhost').searchParams;
  assert.deepEqual(params.getAll('include_tags'), ['客户, "甲"']);
  assert.equal(params.get('collection_id'), '1');
  assert.equal(params.get('media_type'), 'document');
  c.run('state.offset = 24');
  c.node('#sort').listeners.change({ target: { value: 'oldest' } });
  assert.equal(c.run('state.offset'), 0);
  assert.match(c.requests[1].url, /sort=oldest/);
  c.respond(0); c.respond(1);
});

test('download uses same filters without pagination, authenticates, and reports failure', async () => {
  const c = client();
  c.run('state.token="test-token"; state.offset=48; state.includeTags=["approved", "campaign"]; state.excludeTags=["internal"]; state.collection="1"; state.media="document"');
  const downloading = c.node('#export-csv').listeners.click();
  const p = new URL(c.requests[0].url, 'http://localhost').searchParams;
  assert.deepEqual(p.getAll('include_tags'), ['approved', 'campaign']);
  assert.equal(p.get('exclude_tags'), 'internal');
  assert.equal(p.has('offset'), false); assert.equal(p.has('limit'), false);
  assert.equal(c.requests[0].opts.headers.Authorization, 'Bearer test-token');
  c.requests[0].resolve({ ok: true, headers: { get: () => 'text/csv' }, blob: async () => new Blob(['csv']) });
  // Blob is created in this host callback; the VM only consumes it.
  await downloading;
  assert.deepEqual(c.downloads, ['keepstack-assets.csv']);
  const failed = c.node('#export-csv').listeners.click();
  c.requests[1].reject(new Error('network down')); await failed;
  assert.match(c.node('#toast').textContent, /download failed/);
  assert.equal(c.node('#export-csv').disabled, false);
});

test('empty results, failed search, and retry leave clear usable states', async () => {
  const c = client();
  const failing = c.run('loadLibrary()');
  c.requests[0].reject(new Error('offline')); await failing;
  assert.match(c.node('#search-status').textContent, /Could not load/);
  assert.equal(c.node('#export-csv').disabled, true);
  const retry = c.node('#retry-search').listeners.click();
  c.respond(1, 0); await retry;
  assert.equal(c.node('#search-status').textContent, '0 matching assets');
  assert.equal(c.node('#prev-page').disabled, true);
  assert.equal(c.node('#next-page').disabled, true);
  assert.equal(c.node('#export-csv').disabled, false);
});

test('JSON requests default to POST so login and tag editing work in the browser', async () => {
  const c = client();
  const login = c.run('api("/api/auth/login", {json: {username: "admin", password: "admin"}})');
  assert.equal(c.requests[0].opts.method, 'POST');
  assert.equal(c.requests[0].opts.headers['Content-Type'], 'application/json');
  c.respond(0); await login;
  const patch = c.run('api("/api/assets/example", {method:"PATCH", json: {title:"new"}})');
  assert.equal(c.requests[1].opts.method, 'PATCH');
  c.respond(1); await patch;
});

test('opening Collections refreshes the search options with newly created collections', async () => {
  const c = client();
  const loading = c.run('loadCollections()');
  c.respondJson(0, { collections: [{ id: 7, name: 'New campaign', asset_count: 0 }] });
  await loading;
  assert.match(c.node('#filter-collection').innerHTML, /New campaign/);
  c.run('state.collection="7"; renderFilters()');
  assert.match(c.node('#active-filter').textContent, /Collection: New campaign/);
});

test('returning to Library retries collection options and rejects stale collection responses', async () => {
  const c = client();
  const old = c.run('loadFilterCollections()');
  c.node('nav-library').listeners.click();
  const options = c.requests.findIndex((r, index) => index > 0 && r.url === '/api/collections');
  assert.notEqual(options, -1);
  c.respondJson(options, { collections: [{ id: 2, name: 'Latest collection' }] });
  await new Promise(resolve => setImmediate(resolve));
  c.respondJson(0, { collections: [{ id: 1, name: 'Stale collection' }] }); await old;
  assert.match(c.node('#filter-collection').innerHTML, /Latest collection/);
  assert.doesNotMatch(c.node('#filter-collection').innerHTML, /Stale collection/);
  const listing = c.requests.findIndex(r => r.url.startsWith('/api/assets?'));
  c.respond(listing);
});

function assetDetail(uuid, title) {
  return { asset: { uuid, title, media_type: 'document' }, tags: [], versions: [] };
}
function respondDetail(c, offset, uuid, title) {
  c.respondJson(offset, assetDetail(uuid, title));
  c.respondJson(offset + 1, {});
  c.respondJson(offset + 2, { items: [] });
}

test('slow asset detail cannot overwrite a more recently opened asset', async () => {
  const c = client();
  c.run('state.user={role:"admin"}');
  const old = c.run('openAsset("old")');
  const current = c.run('openAsset("new")');
  respondDetail(c, 3, 'new', 'Latest asset'); await current;
  respondDetail(c, 0, 'old', 'Stale asset'); await old;
  assert.match(c.node('#drawer-body').innerHTML, /Latest asset/);
  assert.doesNotMatch(c.node('#drawer-body').innerHTML, /Stale asset/);
});

test('failed detail loads offer a retry and failed edits preserve user input', async () => {
  const c = client();
  c.run('state.user={role:"admin"}');
  const failed = c.run('openAsset("example")');
  c.requests[0].reject(new Error('offline')); await failed;
  assert.match(c.node('#drawer-body').innerHTML, /Could not load/);
  assert.ok(c.node('#retry-detail').listeners.click);
  const retry = c.node('#retry-detail').listeners.click();
  respondDetail(c, 3, 'example', 'Editable asset'); await retry;
  c.node('#e-title').value = 'Unsaved title';
  const save = c.node('#d-save').listeners.click();
  c.requests[6].reject(new Error('offline')); await save;
  assert.match(c.node('#toast').textContent, /Could not save/);
  assert.equal(c.node('#e-title').value, 'Unsaved title');
  assert.equal(c.node('#d-save').disabled, false);
});

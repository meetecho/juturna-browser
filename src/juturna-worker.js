// Worker side of juturna.js: bootstraps Pyodide and Juturna, owns the
// Pipeline. Commands arrive as {id, cmd, ...} and are answered with
// {id, ok, result|error}; outputs and feed errors are unsolicited events.
import { bootstrapJuturna, fetchAssets } from './bootstrap.js';

let pyodide = null;
let py = null;                       // the Python functions below
let feedChain = Promise.resolve();   // feed() one at a time: concurrent
                                     // callPromising() calls may reorder

const PY_RUNTIME = `
import json
from juturna.components import Pipeline
from juturna.components._dag import DAG

pipe = None

def plan(config_json):
    config = json.loads(config_json)['pipeline']
    dag = DAG()
    for node in config['nodes']:
        dag.add_node(node['name'])
    for link in config['links']:
        dag.add_edge(link['from'], link['to'])
    return json.dumps({'layers': dag.BFS(), 'cycle': dag.has_cycle()})

def create(config_json, worker):
    global pipe
    pipe = Pipeline(json.loads(config_json), worker=worker)
    pipe.warmup()

def inbox(name):
    return pipe._transport.queue_handle(pipe._nodes[name]._queue)

def connect(name, handle):
    pipe._transport.connect(name, handle)

def feed(name, message):
    pipe._nodes[name].feed(message)

def start():
    pipe.start()

def stop_layer(names):
    names = [name for name in names if name in pipe._nodes]
    for name in names:
        pipe._nodes[name].stop()
    for name in names:
        pipe._nodes[name].join()

def stop():
    pipe.stop()

def destroy():
    pipe.destroy()

def status():
    return json.dumps({
        'pipeline': str(pipe._status),
        'nodes': {name: {'status': str(node.status), 'health': node.health}
                  for name, node in pipe._nodes.items()},
    }, default=str)
`;

const COMMANDS = {
  ping() { return 'pong'; },
  async init({ base, pyodide: source }) {
    // a version number (CDN) or the URL of a folder served by the page
    const folder = /^v\d/.test(source) ? `https://cdn.jsdelivr.net/pyodide/${source}/full/` : source.replace(/\/?$/, '/');
    const { loadPyodide } = await import(`${folder}pyodide.mjs`);
    // the wheel and the plugins come in while Pyodide loads
    const assets = fetchAssets(new URL(base));
    assets.catch(() => {});                       // reported when bootstrapJuturna awaits it
    pyodide = await loadPyodide();
    await bootstrapJuturna(pyodide, { base: new URL(base), assets });
    await pyodide.runPythonAsync(PY_RUNTIME);
    py = Object.fromEntries(['plan', 'create', 'inbox', 'connect', 'feed', 'start', 'stop_layer', 'stop', 'destroy', 'status']
      .map((name) => [name, pyodide.globals.get(name)]));
  },
  async plan({ config }) { return JSON.parse(await py.plan.callPromising(config)); },
  async pipeline({ config, worker }) { await py.create.callPromising(config, worker); },
  inbox({ node }) { return py.inbox(node); },
  connect({ node, handle }) { py.connect(node, handle); },
  async start() { await py.start.callPromising(); },
  // stopping waits for the feed() calls already received: they must reach the
  // node before its STOP, or they would be discarded as it drains
  async stop_layer({ nodes }) { await feedChain; await py.stop_layer.callPromising(nodes); },
  async stop() { await feedChain; await py.stop.callPromising(); },
  async destroy() { await feedChain; await py.destroy.callPromising(); },
  async status() { return JSON.parse(await py.status.callPromising()); },
};

function feed(node, message) {
  feedChain = feedChain
    .then(() => py.feed.callPromising(node, message))
    .catch((err) => self.postMessage({ type: 'error', error: `feed(${node}): ${describe(err)}` }));
}

self.onmessage = async (event) => {
  const { id, cmd, node, message } = event.data;

  if (cmd === 'feed') { feed(node, message); return; }

  if (cmd === 'port') {
    // shares feedChain with feed(): one ordering for every way in
    event.data.port.onmessage = (e) => feed(node, e.data);
    return;
  }

  try {
    const result = await COMMANDS[cmd](event.data);
    self.postMessage({ id, ok: true, result });
  } catch (err) {
    self.postMessage({ id, ok: false, error: describe(err) });
  }
};

function describe(err) {
  return String((err && err.message) || err).trim().split('\n').slice(-3).join(' | ');
}

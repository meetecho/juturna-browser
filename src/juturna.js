// Juturna in a browser tab: a Pipeline built from the same JSON configuration
// used on desktop, running in one Pyodide Worker or, when nodes carry a
// "worker" key, spread over several.
//
//   const jt   = await Juturna.create();
//   const pipe = await jt.pipeline(config);
//   pipe.output('out').on('message', (msg) => ...);   // {kind, payload, meta}
//   const inp  = pipe.input('in');                    // a BrowserInput node
//   await pipe.start();
//   inp.feed({ kind: 'audio', payload: { audio, sampling_rate: 16000 } });
//   await pipe.stop();  await pipe.destroy();  jt.terminate();
//
// A node runs in the Worker named by its optional "worker" key ("main" when
// missing); nodes of different Workers are linked as any other, the
// messages travel through shared-memory queues. Everything about the data
// (sampling rate, chunking, timestamps) travels in the messages handed to
// feed(): the nodes have no configuration about the page. Capturing the data
// (getUserMedia, files, canvas...) is up to the page.

import { poisonRing, repairRing } from './ring.js';

export { prefetch } from './model-cache.js';

// the bundle of a checkout: a page built with a bundler passes its own base
const DEFAULT_BASE = new URL(/* @vite-ignore */ '../dist/', import.meta.url);
const DEFAULT_SUPERVISE = {
  pingMs: 1000, timeoutMs: 5000, poisonRings: true, buildTimeoutMs: 300000,
  restart: { maxRestarts: 0, delayMs: 500, timeoutMs: 30000 }
};
const DEFAULT_WORKER = 'main';

const workerOf = (node) => node.worker ?? DEFAULT_WORKER;

// `promise`, or a rejection once `ms` have passed (then `onTimeout()`):
// nobody pings a Worker before its nodes run, so one that vanished silently
// would never be noticed
function bounded(promise, ms, message, onTimeout = () => {}) {
  let timer;
  const overdue = new Promise((resolve, reject) => {
    timer = setTimeout(() => {
      reject(new Error(`${message} within ${ms} ms`));
      onTimeout();               // after: what it rejects must not win the race
    }, ms);
  });
  return Promise.race([promise, overdue]).finally(() => clearTimeout(timer));
}

export class Juturna {
  #base;
  #pyodide;
  #supervise;
  #links = new Map();            // Worker name -> WorkerLink
  #pipeline = null;
  #monitor = null;
  #attempts = new Map();         // Worker name -> restarts so far
  #restarting = new Map();       // Worker name -> promise of its restart
  #stopping = false;

  constructor(base, pyodide, supervise) {
    this.#base = new URL(base, location.href).href;
    this.#pyodide = pyodide;
    this.#supervise = {
      ...DEFAULT_SUPERVISE, ...supervise, restart: { ...DEFAULT_SUPERVISE.restart, ...supervise?.restart }
    };
  }

  /**
   * Start the Workers, load Pyodide and install Juturna in each, in parallel.
   * @param {{base?: URL|string, pyodide?: string, pyodideBase?: URL|string, workers?: string[],
   *   supervise?: {pingMs?: number, timeoutMs?: number, poisonRings?: boolean, buildTimeoutMs?: number,
   *   restart?: {maxRestarts?: number, delayMs?: number, timeoutMs?: number}}}} options
   *   `base` is the folder with the artifacts of build/build.py; `pyodide` is
   *   the version loaded from the jsDelivr CDN, which cannot be checked with an
   *   integrity hash: `pyodideBase`, the URL of a folder with a copy of that
   *   release served by the page, loads it from there instead; `workers`
   *   are the names to start now (the ones a pipeline needs but are missing
   *   are started by `pipeline()`). Once the pipeline runs, each Worker is
   *   pinged every `pingMs`; one that fails, or that does not answer for
   *   `timeoutMs`, is lost (a node that keeps the CPU busy for longer than
   *   that needs a higher value). `poisonRings: false` leaves the queues of
   *   a lost Worker as they are (only useful to test what that changes).
   *   `buildTimeoutMs` is the time each of `create()`, `pipeline()` and
   *   `start()` has, before anything pings the Workers.
   *   With `restart.maxRestarts` above 0 (it is 0), a lost Worker is rebuilt
   *   after `delayMs`, up to that many times: its nodes start again from
   *   scratch, and what was in the queues that led to them is gone. A
   *   restart that takes longer than `restart.timeoutMs` has failed.
   */
  static async create({ base = DEFAULT_BASE, pyodide = 'v314.0.6', pyodideBase, workers = [DEFAULT_WORKER], supervise } = {}) {
    if (!/^v\d+\.\d+\.\d+$/.test(pyodide)) throw new Error(`not a Pyodide version: ${pyodide}`);
    const jt = new Juturna(base, pyodideBase ? new URL(pyodideBase, location.href).href : pyodide, supervise);
    try {
      const spawned = Promise.all(workers.map((name) => jt.#spawn(name)));
      await bounded(spawned, jt.#supervise.buildTimeoutMs, 'Workers not started');
    } catch (error) {
      jt.terminate();            // the caller gets no instance to do it with
      throw error;
    }
    return jt;
  }

  /** Build and warm up a pipeline. Only one at a time per instance. */
  async pipeline(config) {
    if (this.#pipeline) throw new Error('this Juturna instance already has a pipeline');
    if (this.#stopping) throw new Error('this Juturna instance was terminated');
    // a Worker that does not answer cannot be used again, and a slow one must
    // not finish building after the rejection: the instance ends
    return bounded(this.#build(config), this.#supervise.buildTimeoutMs, 'pipeline not built', () => this.terminate());
  }

  async #build(config) {
    const nodes = config.pipeline.nodes;
    const names = [...new Set(nodes.map(workerOf))];
    await Promise.all(names.map((name) => this.#spawn(name)));
    const links = names.map((name) => this.#links.get(name));

    const configJson = JSON.stringify(config);
    const { layers, cycle } = await links[0].call('plan', { config: configJson });
    if (cycle) throw new Error('the pipeline contains a cycle');

    await Promise.all(links.map((link) => link.call('pipeline', { config: configJson, worker: link.name })));

    // Each node written to from another Worker exports its inbound queue;
    // the Workers that write to it connect to it.
    const owner = new Map(nodes.map((node) => [node.name, workerOf(node)]));
    const wiring = new Map();    // node -> Set of the Workers writing to it
    for (const { from, to } of config.pipeline.links) {
      if (owner.get(from) === owner.get(to)) continue;
      if (!wiring.has(to)) wiring.set(to, new Set());
      wiring.get(to).add(owner.get(from));
    }
    const inboxes = new Map();   // node -> handle of its inbound queue
    await Promise.all([...wiring].map(async ([node, writers]) => {
      const handle = await this.#links.get(owner.get(node)).call('inbox', { node });
      inboxes.set(node, handle);
      await Promise.all([...writers].map((name) => this.#links.get(name).call('connect', { node, handle })));
    }));

    this.#pipeline = new Pipeline(this, configJson, owner, layers, names, inboxes, wiring);
    return this.#pipeline;
  }

  /** Stop every Worker. The pipeline is lost. */
  terminate() {
    this.#stopping = true;       // a restart that is waiting must not bring a Worker back
    clearInterval(this.#monitor);
    this.#monitor = null;
    for (const link of this.#links.values()) link.terminate();
    this.#links.clear();
  }

  // -- internals, used by Pipeline -----------------------------------------

  _link(name) { return this.#links.get(name); }

  // start the nodes of a Worker; one that does not answer in time is lost, as
  // the monitor would do once it pinged it
  _start(name) {
    const link = this.#links.get(name);
    const { buildTimeoutMs } = this.#supervise;
    const reason = `not started within ${buildTimeoutMs} ms`;
    return bounded(link.call('start'), buildTimeoutMs, 'not started', () => this.#lost(link, reason));
  }

  // stop() or destroy() begins: no restart from now on, and one under way
  // must finish first
  async _beginStop() {
    this.#stopping = true;
    await Promise.allSettled([...this.#restarting.values()]);
  }

  // Ping every Worker from now on: they must be answering to be alive.
  _supervise() {
    if (this.#monitor) return;
    let lastTick = performance.now();
    for (const link of this.#links.values()) link.lastPong = lastTick;
    this.#monitor = setInterval(() => {
      const now = performance.now();
      // The time this timer was late (a hidden tab runs it once a minute) is
      // time no Worker was asked anything: it does not count against them.
      const late = Math.max(0, now - lastTick - this.#supervise.pingMs);
      lastTick = now;
      for (const link of this.#links.values()) {
        // a Worker being rebuilt is judged once its nodes run again: until
        // then it warms them up, and that may take longer than the timeout
        if (link.state !== 'ok' || !link.booted || this.#restarting.has(link.name)) continue;
        link.lastPong = Math.min(now, link.lastPong + late);
        if (now - link.lastPong > this.#supervise.timeoutMs) this.#lost(link, `no answer for ${this.#supervise.timeoutMs} ms`);
        else link.ping();
      }
    }, this.#supervise.pingMs);
  }

  async #spawn(name) {
    if (this.#links.has(name)) return this.#links.get(name).ready;
    const link = new WorkerLink(name, (data) => this.#route(data), (reason) => this.#lost(link, reason));
    this.#links.set(name, link);
    link.ready = link.call('init', { base: this.#base, pyodide: this.#pyodide }).then(() => { link.booted = true; });
    return link.ready;
  }

  // A Worker is gone: make sure nothing stays blocked on it, tell, and maybe
  // build it again.
  async #lost(link, reason) {
    if (!link || link.state === 'lost') return;
    link.lose(reason);

    const attempts = this.#attempts.get(link.name) ?? 0;
    const willRestart = !!this.#pipeline && !this.#stopping && attempts < this.#supervise.restart.maxRestarts;

    // what waits for room in the queues to its nodes must not wait any more
    if (this.#supervise.poisonRings) this.#pipeline?._poisonRingsOf(link.name);
    this.#pipeline?._workerLost(link.name, reason, willRestart);

    // and what it wrote may be half done: the reader must not wait for it
    await this.#pipeline?._repairRingsWrittenBy(link.name);

    if (willRestart) {
      const restart = this.#restart(link.name, attempts + 1);
      this.#restarting.set(link.name, restart);
      // a restart that failed has already put the next one in its place
      restart.finally(() => { if (this.#restarting.get(link.name) === restart) this.#restarting.delete(link.name); });
    }
  }

  async #restart(name, attempt) {
    this.#attempts.set(name, attempt);
    await new Promise((resolve) => setTimeout(resolve, this.#supervise.restart.delayMs));
    if (this.#stopping) return this.#pipeline._restartCancelled(name);

    this.#links.delete(name);
    const { timeoutMs } = this.#supervise.restart;
    try {
      await bounded(this.#spawn(name).then(() => this.#pipeline._rebuild(name)), timeoutMs, 'not rebuilt');
      this.#links.get(name).lastPong = performance.now();
      this.#pipeline._workerRestarted(name, attempt);
    } catch (error) {
      // it did not come back: lost again, and maybe one more try
      await this.#lost(this.#links.get(name), `restart failed: ${error.message}`);
    }
  }

  #route(data) {
    if (data.type === 'output') this.#pipeline?._deliver(data.node, data.message);
    else if (data.type === 'error') this.#pipeline?._error(new Error(data.error));
    else if (data.type === 'telemetry') this.#pipeline?._deliverTelemetry(data);
  }
}

// same order as the records of the Python side (BrowserTelemetry)
const TELEMETRY_FIELDS = ['ts', 'evt', 'node', 'origin', 'msg_id', 'src_id', 'size', 'worker'];
const telemetryRecord = (record) => Object.fromEntries(TELEMETRY_FIELDS.map((field, i) => [field, record[i]]));

class WorkerLink {
  #worker;
  #pending = new Map();
  #nextId = 1;

  constructor(name, onEvent, onLost) {
    this.name = name;
    this.state = 'ok';           // 'ok' or 'lost'
    this.reason = null;
    this.lastPong = performance.now();
    this.#worker = new Worker(new URL('./juturna-worker.js', import.meta.url), { type: 'module', name });
    this.#worker.onmessage = ({ data }) => {
      if (data.id === undefined) return onEvent(data);
      const entry = this.#pending.get(data.id);
      this.#pending.delete(data.id);
      if (!entry) return;
      if (data.ok) entry.resolve(data.result);
      else entry.reject(new Error(`[${name}] ${data.error}`));
    };
    this.#worker.onerror = (event) => {
      this.#failAll(new Error(`worker ${name}: ${event.message}`));
      onLost(`error in the Worker: ${event.message}`);
    };
  }

  call(cmd, args = {}) {
    return new Promise((resolve, reject) => {
      if (this.state === 'lost') return reject(new Error(`Worker ${this.name} was lost: ${this.reason}`));
      const id = this.#nextId++;
      this.#pending.set(id, { resolve, reject });
      this.#worker.postMessage({ id, cmd, ...args });
    });
  }

  post(message, transfer) {
    if (this.state === 'lost') throw new Error(`Worker ${this.name} was lost: ${this.reason}`);
    this.#worker.postMessage(message, transfer);
  }

  ping() { this.call('ping').then(() => { this.lastPong = performance.now(); }, () => {}); }

  lose(reason) {
    this.state = 'lost';
    this.reason = reason;
    this.terminate();
  }

  terminate() {
    this.#worker.terminate();
    this.#failAll(new Error('terminated'));
  }

  #failAll(error) {
    for (const { reject } of this.#pending.values()) reject(error);
    this.#pending.clear();
  }
}

class Pipeline {
  #jt;
  #nodes;                        // node name -> type (node class)
  #owner;                        // node name -> Worker name
  #layers;                       // whole-graph layers, upstream first
  #workers;
  #configJson;
  #inboxes;                      // node name -> handle of its inbound queue
  #writers;                      // node name -> Set of the Workers that write to it
  #restarting = new Set();       // Workers being rebuilt
  #lost = new Map();             // Worker name -> why
  #listeners = new Map();        // node name -> Set of callbacks
  #errorListeners = new Set();
  #lostListeners = new Set();
  #restartedListeners = new Set();
  #telemetryListeners = new Set();

  constructor(jt, configJson, owner, layers, workers, inboxes, writers) {
    const config = JSON.parse(configJson);
    this.#configJson = configJson;
    this.#writers = writers;
    this.#inboxes = inboxes;
    this.#jt = jt;
    this.#nodes = new Map(config.pipeline.nodes.map((n) => [n.name, n.type]));
    this.#owner = owner;
    this.#layers = layers;
    this.#workers = workers;
  }

  /**
   * Handle to a `BrowserInput` node.
   * @returns {{feed: (message: object, options?: {copy?: boolean}) => void,
   *   port: () => MessagePort}}
   */
  input(name) {
    this.#require(name, 'BrowserInput');
    const link = () => this.#linkOf(name);   // a Worker that was rebuilt has a new one
    return {
      // By default the buffers in `payload` are transferred (zero copy) and
      // detach in the caller; pass {copy: true} to keep using them. A view
      // over a part of a larger buffer is copied first, so that the rest of
      // that buffer stays usable.
      feed: (message, { copy = false } = {}) => {
        const [sent, transfer] = copy ? [message, []] : detachable(message);
        link().post({ cmd: 'feed', node: name, message: sent }, transfer);
      },
      // A MessagePort that feeds this node: transfer it to whatever produces
      // the data (an AudioWorklet, another Worker) and it posts messages
      // {kind, payload, meta} straight to the Worker of the node, without
      // going through the page. Each call returns a new port.
      port: () => {
        const { port1, port2 } = new MessageChannel();
        link().post({ cmd: 'port', node: name, port: port2 }, [port2]);
        return port1;
      }
    };
  }

  /**
   * Handle to a `BrowserOutput` node.
   * @returns {{on: (event: 'message', callback: Function) => Function}}
   *   `on` returns the function that removes the listener.
   */
  output(name) {
    this.#require(name, 'BrowserOutput');
    return {
      on: (event, callback) => {
        if (event !== 'message') throw new Error(`unknown output event: ${event}`);
        if (!this.#listeners.has(name)) this.#listeners.set(name, new Set());
        this.#listeners.get(name).add(callback);
        return () => this.#listeners.get(name).delete(callback);
      }
    };
  }

  /** Listen to errors raised while feeding data. Returns an unsubscribe. */
  onError(callback) {
    this.#errorListeners.add(callback);
    return () => this.#errorListeners.delete(callback);
  }

  /**
   * Listen to the loss of a Worker: `callback({worker, reason, willRestart})`.
   * The nodes of a lost Worker are gone and what was sent to them is dropped;
   * the others keep running, and `stop()` and `destroy()` work on them.
   * Returns an unsubscribe.
   */
  onWorkerLost(callback) {
    this.#lostListeners.add(callback);
    return () => this.#lostListeners.delete(callback);
  }

  /**
   * Listen to a Worker that was rebuilt after it was lost:
   * `callback({worker, attempt})`. Its nodes are new, and the `MessagePort`s
   * it had been given are dead: ask for new ones with `input(name).port()`.
   * Returns an unsubscribe.
   */
  onWorkerRestarted(callback) {
    this.#restartedListeners.add(callback);
    return () => this.#restartedListeners.delete(callback);
  }

  /**
   * Listen to the telemetry of the Workers: `callback({worker, records})`, a
   * batch at a time as it is produced. The pipeline needs a `telemetry` key in
   * its configuration. Returns an unsubscribe.
   */
  onTelemetry(callback) {
    this.#telemetryListeners.add(callback);
    return () => this.#telemetryListeners.delete(callback);
  }

  /** Every Worker starts at once: what a node sends to one still to start
   *  waits in the queue. */
  async start() {
    const alive = this.#workers.filter((name) => !this.#lost.has(name));
    await this.#settle(alive.map((name) => [name, this.#jt._start(name)]));
    this.#jt._supervise();
  }

  /**
   * Same order as on desktop, across Workers: the nodes of each layer of the
   * graph are sent a STOP and joined before the next layer, so the messages
   * an upstream node sent last are still consumed downstream.
   */
  async stop() {
    await this.#jt._beginStop();
    if (this.#workers.length > 1) {
      for (const layer of this.#layers) {
        const byWorker = new Map();
        for (const node of layer) {
          const name = this.#owner.get(node);
          if (!byWorker.has(name)) byWorker.set(name, []);
          byWorker.get(name).push(node);
        }
        await this.#settle([...byWorker].map(([name, nodes]) => [name, this.#jt._link(name).call('stop_layer', { nodes })]));
      }
    }
    await this.#all('stop');
  }

  async destroy() {
    await this.#jt._beginStop();
    await this.#all('destroy');
  }

  /** Status and health of the pipeline and of each node, all Workers merged. */
  async status() {
    const asked = this.#workers.filter((name) => !this.#lost.has(name) && !this.#restarting.has(name));
    const answers = await Promise.all(asked.map((name) => this.#jt._link(name).call('status').catch((error) => {
      if (!this.#lost.has(name)) throw error;
      return null;               // lost while we ask: reported like the ones lost before
    })));
    const liveAnswers = asked.map((name, i) => [name, answers[i]])
      .filter(([name, answer]) => answer && !this.#lost.has(name) && !this.#restarting.has(name));
    const alive = liveAnswers.map(([name]) => name);
    const parts = liveAnswers.map(([, answer]) => answer);
    return {
      pipeline: [...new Set(parts.map((p) => p.pipeline))].join('/'),
      nodes: Object.assign({}, ...parts.map((p) => p.nodes)),
      workers: {
        ...Object.fromEntries(alive.map((name, i) => [name, parts[i].pipeline])),
        ...Object.fromEntries([...this.#restarting].map((name) => [name, 'restarting'])),
        ...Object.fromEntries([...this.#lost].filter(([name]) => !this.#restarting.has(name)).map(([name]) => [name, 'lost']))
      },
      lost: Object.fromEntries(this.#lost)
    };
  }

  /**
   * The latest telemetry records (10000 per Worker by default), all Workers
   * merged and ordered by time. Empty when the pipeline has no `telemetry` key.
   * @returns {Promise<{ts: number, evt: string, node: string, origin: string,
   *   msg_id: number, src_id: number|null, size: number, worker: string}[]>}
   */
  async telemetry() {
    const alive = this.#workers.filter((name) => !this.#lost.has(name) && !this.#restarting.has(name));
    // a Worker lost while we ask is skipped like the ones lost before
    const parts = await Promise.all(alive.map((name) => this.#jt._link(name).call('telemetry').catch(() => [])));
    return parts.flat().map(telemetryRecord).sort((a, b) => a.ts - b.ts);
  }

  _deliverTelemetry({ worker, records }) {
    const batch = { worker, records: records.map(telemetryRecord) };
    for (const callback of this.#telemetryListeners) {
      try { callback(batch); } catch (error) { this._error(error); }
    }
  }

  // a listener that throws must not keep the others from the message
  _deliver(node, message) {
    for (const callback of this.#listeners.get(node) ?? []) {
      try { callback(message); } catch (error) { this._error(error); }
    }
  }

  _error(error) {
    if (!this.#errorListeners.size) console.error(error);
    for (const callback of this.#errorListeners) {
      try { callback(error); } catch (thrown) { console.error(thrown); }
    }
  }

  _workerLost(worker, reason, willRestart = false) {
    this.#lost.set(worker, reason);
    if (willRestart) this.#restarting.add(worker);
    else this.#restarting.delete(worker);   // lost for good after a restart that failed
    this._error(new Error(`Worker ${worker} was lost: ${reason}${willRestart ? ' (restarting)' : ''}`));
    // a listener that throws must not stop the recovery that follows
    for (const callback of this.#lostListeners) {
      try { callback({ worker, reason, willRestart }); } catch (error) { this._error(error); }
    }
  }

  _workerRestarted(worker, attempt) {
    this.#lost.delete(worker);
    this.#restarting.delete(worker);
    // a listener that throws must not make a Worker that came back look like a failed restart
    for (const callback of this.#restartedListeners) {
      try { callback({ worker, attempt }); } catch (error) { this._error(error); }
    }
  }

  // stop(), destroy() or terminate() came first: the Worker stays lost
  _restartCancelled(worker) { this.#restarting.delete(worker); }

  // A Worker was built again: its nodes, and the queues to and from them.
  async _rebuild(name) {
    const link = this.#jt._link(name);
    await link.call('pipeline', { config: this.#configJson, worker: name });

    for (const [node, writers] of this.#writers) {
      if (this.#owner.get(node) === name) {
        // its node has a new queue: whoever writes to it connects to that one
        const handle = await link.call('inbox', { node });
        this.#inboxes.set(node, handle);
        await Promise.all([...writers].filter((w) => !this.#lost.has(w)).map((w) => this.#jt._link(w).call('connect', { node, handle })));
      } else if (writers.has(name)) {
        // it writes to a node of another Worker, whose queue is still there
        await link.call('connect', { node, handle: this.#inboxes.get(node) });
      }
    }
    await link.call('start');
  }

  // the queues a lost Worker wrote to, whose reader could be left waiting for
  // a slot it claimed and never filled
  async _repairRingsWrittenBy(worker) {
    const rings = [];
    for (const [node, writers] of this.#writers) {
      if (writers.has(worker) && !this.#lost.has(this.#owner.get(node))) rings.push(this.#inboxes.get(node));
    }
    await Promise.all(rings.map((handle) => repairRing(handle)));
  }

  // the queues that lead to the nodes of a lost Worker: nobody reads them
  // any more, so whoever writes to them must not wait
  _poisonRingsOf(worker) {
    for (const [node, handle] of this.#inboxes) {
      if (this.#owner.get(node) === worker) poisonRing(handle);
    }
  }

  _inboxHandle(node) { return this.#inboxes.get(node); }        // for the tests

  #linkOf(node) {
    const worker = this.#owner.get(node);
    if (this.#restarting.has(worker)) throw new Error(`Worker ${worker} is restarting`);
    return this.#jt._link(worker);
  }

  #all(cmd) {
    const alive = this.#workers.filter((name) => !this.#lost.has(name));
    return this.#settle(alive.map((name) => [name, this.#jt._link(name).call(cmd)]));
  }

  // wait for all the calls; one that fails matters only if its Worker is
  // still alive: a lost Worker cannot answer
  async #settle(calls) {
    const results = await Promise.allSettled(calls.map(([, call]) => call));
    const failed = results.findIndex((r, i) => r.status === 'rejected' && !this.#lost.has(calls[i][0]));
    if (failed >= 0) throw results[failed].reason;
  }

  #require(name, type) {
    if (this.#nodes.get(name) !== type) {
      throw new Error(`'${name}' is not a ${type} node of this pipeline`);
    }
  }
}

// The message to post and the buffers to transfer with it.
function detachable(message) {
  if (!message.payload) return [message, []];
  const payload = { ...message.payload };
  const buffers = new Set();
  for (const [key, value] of Object.entries(payload)) {
    if (!ArrayBuffer.isView(value) || !(value.buffer instanceof ArrayBuffer)) continue;
    const whole = value.byteOffset === 0 && value.byteLength === value.buffer.byteLength;
    const view = whole
      ? value : new value.constructor(value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength));
    payload[key] = view;
    buffers.add(view.buffer);
  }
  return [{ ...message, payload }, [...buffers]];
}

// Live telemetry for the example pages: add `?telemetry` to the URL.

const enabled = new URLSearchParams(globalThis.location?.search ?? '').has('telemetry');

export const withTelemetry = (config) => {
  if (enabled) config.pipeline.telemetry = { name: 'browser' };
  return config;
};

// Adds the records of a batch to the per-node counters.
export const tally = (stats, records) => {
  for (const { node, worker, evt, size } of records) {
    const s = (stats[node] ??= { worker, rx: 0, tx: 0, bytes: 0 });
    if (evt === 'rx') s.rx += 1;
    else {
      s.tx += 1;
      s.bytes += size;
    }
  }
};

export const formatTable = (stats, rates) => {
  const row = (...cells) => cells.map((c, i) => String(c)[i < 2 ? 'padEnd' : 'padStart'](i < 2 ? 14 : 10)).join('');
  const lines = [row('node', 'worker', 'rx', 'tx', 'sent KB', 'tx/s')];
  for (const [node, s] of Object.entries(stats)) {
    lines.push(row(node, s.worker, s.rx, s.tx, (s.bytes / 1024).toFixed(1), (rates[node] ?? 0).toFixed(1)));
  }
  return lines.join('\n');
};

let stop = () => {};

// Shows a table of the messages each node received and sent, refreshed every second.
export const showTelemetry = (pipe) => {
  stop();
  if (!enabled) return;

  const panel = document.getElementById('telemetry') ?? document.body.appendChild(document.createElement('pre'));
  panel.id = 'telemetry';

  const stats = {};
  const unsubscribe = pipe.onTelemetry(({ records }) => tally(stats, records));
  let previous = {};
  let at = performance.now();
  const timer = setInterval(() => {
    const now = performance.now();
    const rates = {};
    for (const [node, s] of Object.entries(stats)) rates[node] = ((s.tx - (previous[node] ?? 0)) * 1000) / (now - at);
    previous = Object.fromEntries(Object.entries(stats).map(([node, s]) => [node, s.tx]));
    at = now;
    panel.textContent = formatTable(stats, rates);
  }, 1000);

  stop = () => {
    unsubscribe();
    clearInterval(timer);
  };
};

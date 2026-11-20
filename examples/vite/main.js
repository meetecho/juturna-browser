import { Juturna } from 'juturna-browser';

const checks = {};
const check = (name, ok, detail) => {
  checks[name] = ok ? 'ok' : `FAIL: ${JSON.stringify(detail)}`;
};
const config = {
  pipeline: {
    name: 'vite', id: 'vite-1', folder: '/tmp/juturna/vite', transport: 'browser',
    nodes: [
      { name: 'in', type: 'BrowserInput', configuration: {} },
      { name: 'out', type: 'BrowserOutput', configuration: {} }
    ],
    links: [{ from: 'in', to: 'out' }]
  }
};
window.__result = null;

let jt;
try {
  // public/juturna is served at /juturna/
  jt = await Juturna.create({ base: '/juturna/' });
  const pipe = await jt.pipeline(config);
  const received = new Promise((resolve) => pipe.output('out').on('message', resolve));
  await pipe.start();
  pipe.input('in').feed({
    kind: 'audio', payload: { audio: new Float32Array(1600).fill(0.5), sampling_rate: 16000 }, meta: { i: 1 }
  });
  const message = await Promise.race([received, new Promise((resolve) => setTimeout(resolve, 10000))]);
  check('round_trip', message?.meta.i === 1 && message.payload.audio[0] === 0.5, message ?? 'no message in 10 s');
  await pipe.stop();
  await pipe.destroy();
  window.__result = { checks };
} catch (error) {
  window.__result = { checks, fatal: String(error?.stack ?? error) };
} finally {
  jt?.terminate();
}
document.getElementById('out').textContent = JSON.stringify(window.__result, null, 2);

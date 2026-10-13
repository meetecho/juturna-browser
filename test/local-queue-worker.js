import { bootstrapJuturna } from '../src/bootstrap.js';

const PY = `
import asyncio, json, time
from juturna.transport._base import Full
from pyodide.ffi import run_sync
import juturna.transport as jt
from juturna.transport._base import Empty
from juturna.transport.browser._queue import QueueClosed
from juturna.components import Node

transport = jt.BrowserTransport(queue_capacity=4)
checks = {}

def check(name, ok, detail=None):
    checks[name] = 'ok' if ok else 'FAIL: ' + repr(detail)

def sleep(seconds):
    run_sync(asyncio.sleep(seconds))

def run_tasks(*targets):
    handles = [transport.spawn(t, f'task{i}') for i, t in enumerate(targets)]
    for h in handles: h.start()
    for h in handles: h.join(timeout=10)

def run():
    # -- order, capacity and backpressure with a slow consumer
    q = transport.new_queue(local=True)
    got, sizes, done = [], [], []
    def producer():
        t0 = time.time()
        for i in range(30): q.put(i)
        done.append(time.time() - t0)
    def consumer():
        for _ in range(30):
            sizes.append(q.qsize())
            got.append(q.get(timeout=5))
            sleep(0.005)
    run_tasks(producer, consumer)
    check('order_is_kept', got == list(range(30)), got)
    check('never_holds_more_than_its_capacity', max(sizes) <= 4, max(sizes))
    check('a_full_queue_makes_put_wait', done and done[0] > 0.09, done)

    # -- it is the same object, not a copy
    q = transport.new_queue(local=True)
    thing = object()
    q.put(thing)
    check('the_object_is_not_copied', q.get() is thing)

    # -- timeouts
    q = transport.new_queue(local=True)
    t0 = time.time()
    try: q.get(timeout=0.05); ok = False
    except Empty: ok = 0.04 < time.time() - t0 < 0.5
    check('get_times_out_with_Empty', ok)
    try: q.get_nowait(); ok = False
    except Empty: ok = True
    check('get_nowait_on_an_empty_queue', ok)
    for i in range(4): q.put(i)
    check('a_full_queue_reports_full', q.full() and q.qsize() == 4 and not q.empty())
    t0 = time.time()
    try: q.put(9, timeout=0.05); ok = False
    except Full: ok = 0.04 < time.time() - t0 < 0.5
    check('put_times_out_with_Full', ok)

    # -- close wakes whoever waits, and refuses new writes
    q = transport.new_queue(local=True)
    outcome = []
    def getter():
        try: q.get(); outcome.append('item')
        except Empty: outcome.append('Empty')
    def closer():
        sleep(0.05); q.close()
    run_tasks(getter, closer)
    check('close_wakes_a_waiting_get', outcome == ['Empty'], outcome)
    q = transport.new_queue(local=True)
    for i in range(4): q.put(i)
    outcome = []
    def putter():
        try: q.put(9); outcome.append('put')
        except QueueClosed: outcome.append('QueueClosed')
    run_tasks(putter, closer)
    check('close_wakes_a_waiting_put', outcome == ['QueueClosed'], outcome)
    try: q.put(1); ok = False
    except QueueClosed: ok = True
    check('a_closed_queue_refuses_writes', ok)
    check('a_closed_queue_still_gives_what_it_holds', q.get() == 0)

    # -- which queues are local and which are rings
    kind = lambda queue: type(queue).__name__
    check('a_queue_is_a_ring_by_default', kind(transport.new_queue()) == '_BrowserQueue')
    with transport.node_scope(False):
        check('unshared_scope_gives_local', kind(transport.new_queue()) == '_BrowserLocalQueue')
    with transport.node_scope(True):
        check('shared_scope_gives_a_ring', kind(transport.new_queue()) == '_BrowserQueue')
        check('local_hint_wins_in_a_shared_scope', kind(transport.new_queue(local=True)) == '_BrowserLocalQueue')
    check('scope_ends_with_its_block', kind(transport.new_queue()) == '_BrowserQueue')
    try: transport.queue_handle(transport.new_queue(local=True)); ok = False
    except RuntimeError: ok = True
    check('a_local_queue_cannot_be_shared', ok)

    # -- a node: its buffer is always local, its inbound queue follows the scope
    with transport.node_scope(False):
        node = Node(node_name='a', pipe_name='p', transport=transport)
    check('node_alone_is_all_local', kind(node._queue) == '_BrowserLocalQueue' and kind(node._buffer._out_queue) == '_BrowserLocalQueue', [kind(node._queue), kind(node._buffer._out_queue)])
    with transport.node_scope(True):
        node = Node(node_name='b', pipe_name='p', transport=transport)
    check('node_written_from_afar_has_a_ring_in', kind(node._queue) == '_BrowserQueue' and kind(node._buffer._out_queue) == '_BrowserLocalQueue', [kind(node._queue), kind(node._buffer._out_queue)])
    return json.dumps(checks)
`;

self.onmessage = async ({ data: { dist } }) => {
  try {
    const { loadPyodide } = await import('https://cdn.jsdelivr.net/pyodide/v314.0.6/full/pyodide.mjs');
    const pyodide = await loadPyodide();
    await bootstrapJuturna(pyodide, { base: new URL(dist ?? '../dist/', import.meta.url) });
    await pyodide.runPythonAsync(PY);
    const checks = JSON.parse(await pyodide.globals.get('run').callPromising());
    self.postMessage({ checks });
  } catch (e) {
    self.postMessage({ fatal: String((e && e.message) || e).split('\n').slice(-4).join(' | '), checks: {} });
  }
};

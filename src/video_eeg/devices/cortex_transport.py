"""Bounded, single-reader local Cortex transport; never silently discard EEG.

API flow reviewed against the supplied emotiv-cortex-sdk 0.2.3 and Cortex docs.
Credentials and tokens are deliberately excluded from diagnostics.
"""
import json
import os
from pathlib import Path
import queue
import ssl
import threading
import time


class CortexTransport:
    def __init__(self, *, connection=None, capacity=10000):
        from websockets.sync.client import connect
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # Cortex local self-signed endpoint only.
        self.ws = connection or connect('wss://127.0.0.1:6868', ssl=context,
            open_timeout=5, close_timeout=2, max_queue=32, proxy=None)
        self.samples = queue.Queue(capacity)
        self.pending = {}
        self.lock = threading.Lock()
        self.sequence = 0
        self.error = None
        self.closed = False
        self.closing_session = False
        self.warning_codes = []
        self.token = None
        self.session = None
        self.thread = threading.Thread(target=self._read, daemon=True, name='cortex-reader')
        self.thread.start()

    def _read(self):
        try:
            while not self.closed:
                try:
                    raw = self.ws.recv(timeout=1)
                except TimeoutError:
                    continue
                if not raw:
                    raise RuntimeError('Cortex connection closed')
                msg = json.loads(raw)
                if 'id' in msg:
                    with self.lock:
                        response = self.pending.get(msg['id'])
                    if response is not None:
                        response.put_nowait(msg)
                elif 'eeg' in msg:
                    self.samples.put_nowait((time.perf_counter_ns(), msg))
                elif 'warning' in msg:
                    code = msg['warning'].get('code')
                    self.warning_codes = (self.warning_codes + [code])[-100:]
                    # Warnings also report successful login, authorization and saves.
                    if code in {2, 9, 13, 14, 15, 17, 18, 21, 22, 30, 32, 104, 142}:
                        continue
                    details = msg['warning'].get('message')
                    if code in {0, 1}:
                        if self.closing_session:
                            continue
                        if isinstance(details, dict) and details.get('sessionId') not in {None, self.session}:
                            continue
                    self.error = RuntimeError(f'Cortex warning {code}; check device/session in EMOTIV Launcher')
                    return
        except queue.Full:
            self.error = RuntimeError('Cortex queue overflow; acquisition stopped, no silent drop')
        except Exception as exc:
            if not self.closed:
                self.error = RuntimeError('Cortex reader failed: ' + type(exc).__name__)

    def check(self):
        if self.error:
            raise self.error
        if self.closed:
            raise RuntimeError('Cortex transport is closed')

    def call(self, method, params=None, timeout=10):
        self.check()
        response = queue.Queue(1)
        with self.lock:
            self.sequence += 1
            rid = self.sequence
            self.pending[rid] = response
        try:
            self.ws.send(json.dumps(dict(jsonrpc='2.0', id=rid, method=method, params=params or {})))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                self.check()
                try:
                    msg = response.get(timeout=min(.05, max(.001, deadline-time.monotonic())))
                except queue.Empty:
                    continue
                if 'error' in msg:
                    raise RuntimeError(f"Cortex {method} rejected (code {msg['error'].get('code')}); check access/license/session")
                return msg.get('result')
            raise RuntimeError(f'Cortex {method} timed out')
        finally:
            with self.lock:
                self.pending.pop(rid, None)

    def login(self):
        path = os.environ.get('EMOTIV_CREDS')
        candidates = [Path(path)] if path else [Path('credentials.json'), Path.home()/'.emotiv/credentials.json']
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            raise RuntimeError('Set EMOTIV_CREDS to your local Cortex credentials JSON')
        creds = json.loads(path.read_text(encoding='utf-8-sig'))
        auth = {key: creds[key] for key in ('clientId', 'clientSecret')}
        access = self.call('requestAccess', auth)
        if not access.get('accessGranted'):
            raise RuntimeError('Approve this application in EMOTIV Launcher, then retry')
        self.token = self.call('authorize', dict(auth, debit=1))['cortexToken']

    def close(self):
        if self.closed:
            return
        failure = None
        try:
            if self.session and not self.error:
                self.closing_session = True
                self.call('updateSession', dict(cortexToken=self.token, session=self.session, status='close'), timeout=3)
        except Exception as exc:
            failure = exc
        finally:
            self.closed = True
            self.ws.close()
            self.thread.join(timeout=2)
        if failure:
            raise failure

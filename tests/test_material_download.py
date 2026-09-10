import hashlib
import importlib.util
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import zipfile

import pytest

spec = importlib.util.spec_from_file_location('materials', Path(__file__).resolve().parents[1] / 'scripts/download_materials.py')
materials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(materials)


@pytest.mark.parametrize('supports_range', [True, False])
def test_interrupted_download_resumes_or_restarts_when_server_ignores_range(tmp_path, supports_range):
    payload = b'video-data' * 100
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get('Range'))
            offset = int(self.headers['Range'].split('=')[1].split('-')[0]) if supports_range else 0
            self.send_response(206 if supports_range else 200)
            if supports_range:
                self.send_header('Content-Range', f'bytes {offset}-{len(payload)-1}/{len(payload)}')
            self.end_headers()
            self.wfile.write(payload[offset:])
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    target = tmp_path / 'archive.zip'
    target.with_suffix('.zip.part').write_bytes(payload[:123])
    try:
        materials.download(f'http://127.0.0.1:{server.server_port}/asset', target,
                           hashlib.sha256(payload).hexdigest(), len(payload))
    finally:
        server.shutdown(); server.server_close(); thread.join()
    assert target.read_bytes() == payload
    assert seen == ['bytes=123-']


def test_extraction_validates_and_never_overwrites_different_video(tmp_path):
    payload = b'original-video'
    archive = tmp_path / 'videos.zip'
    rows = [dict(path='videos/0001.mp4', bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())]
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('videos/0001.mp4', payload)
    destination = tmp_path / 'stimuli'
    materials.install_archive(archive, destination, rows)
    target = destination / 'videos/0001.mp4'
    assert target.read_bytes() == payload
    materials.install_archive(archive, destination, rows)
    target.write_bytes(b'keep-local-file')
    with pytest.raises(ValueError, match='Existing video differs'):
        materials.install_archive(archive, destination, rows)
    assert target.read_bytes() == b'keep-local-file'


def test_archive_cannot_extract_unlisted_paths(tmp_path):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('../data/record.json', b'bad')
    with pytest.raises(ValueError, match='Archive contents differ'):
        materials.install_archive(archive, tmp_path / 'stimuli', [])

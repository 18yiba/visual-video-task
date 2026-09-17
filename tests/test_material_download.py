import hashlib
import json
import importlib.util
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import zipfile

import pytest

spec = importlib.util.spec_from_file_location('materials', Path(__file__).resolve().parents[1] / 'scripts/download_materials.py')
materials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(materials)


def test_published_source_metadata_is_complete_and_preserves_release_pins():
    manifest = json.loads((materials.ROOT / 'video_eeg/config/materials_manifest.json').read_text(encoding='utf-8'))
    materials.validate_source_metadata()
    assert manifest['metadata']['session_manifest_34.csv']
    current = json.loads((materials.ROOT / 'video_eeg/config/materials_source_metadata.json').read_text(encoding='utf-8'))
    assert current['formal_manifest'] == 'session_manifest.csv'
    assert len(manifest['files']) == 7996


def test_changed_source_metadata_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(materials, 'ROOT', tmp_path)
    p = tmp_path / 'video_eeg/config/test.csv'
    p.parent.mkdir(parents=True)
    p.write_bytes(b'changed')
    (p.parent/'materials_manifest.json').write_bytes(b'{}')
    (p.parent/'materials_source_metadata.json').write_text(json.dumps({
        'release_manifest_sha256':hashlib.sha256(b'{}').hexdigest(),
        'metadata':{'test.csv':hashlib.sha256(b'original').hexdigest()}}),encoding='utf-8')
    with pytest.raises(ValueError, match='test.csv'):
        materials.validate_source_metadata()


def test_modified_release_manifest_is_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(materials,'ROOT',tmp_path)
    folder=tmp_path/'video_eeg/config';folder.mkdir(parents=True)
    (folder/'materials_manifest.json').write_bytes(b'{"tampered":true}')
    (folder/'materials_source_metadata.json').write_text(json.dumps({
        'release_manifest_sha256':hashlib.sha256(b'{}').hexdigest(),'metadata':{}}),encoding='utf-8')
    with pytest.raises(ValueError,match='release manifest checksum'):
        materials.validate_source_metadata()


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

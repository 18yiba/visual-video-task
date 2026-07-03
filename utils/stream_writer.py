"""Background streamed writer for chunks of data."""
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

LOGGER = logging.getLogger(__name__)


@dataclass
class RecordItem:
    window: np.ndarray
    y_true: int
    y_pred: int
    confidence: float


class StreamWriter:
    """Writes chunks of recordings to avoid keeping all data in memory."""

    def __init__(self, output_dir: Path, chunk_size: int = 500, max_queue: int = 2000):
        self._output_dir = output_dir
        self._chunks_dir = output_dir / "chunks"
        self._chunk_size = chunk_size
        self._queue: queue.Queue[RecordItem | None] = queue.Queue(maxsize=max_queue)
        self._dropped_records = 0
        self._total_windows = 0
        self._chunk_count = 0
        self._files: list[str] = []

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self, metadata: dict) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._chunks_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self._output_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            while True:
                try:
                    self._queue.put(None, timeout=0.1)
                    break
                except queue.Full:
                    continue
            self._thread.join()
            self._thread = None
            
    def put(self, window: np.ndarray, y_true: int, y_pred: int, confidence: float) -> None:
        item = RecordItem(window, y_true, y_pred, confidence)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self._dropped_records += 1
            LOGGER.warning("StreamWriter queue full! Dropped record.")

    def update_manifest(self, extra: dict) -> None:
        manifest_path = self._output_dir / "manifest.json"
        
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except FileNotFoundError:
            metadata = {}
            
        metadata.update({
            "chunk_size": self._chunk_size,
            "chunk_count": self._chunk_count,
            "total_windows": self._total_windows,
            "dropped_records": self._dropped_records,
            "files": self._files,
            "end_time": time.time(),
        })
        metadata.update(extra)
        
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    def _writer_loop(self) -> None:
        buffer = []
        
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                item = self._queue.get(timeout=0.1)
                
                if item is None:
                    continue
                    
                buffer.append(item)
                
                if len(buffer) >= self._chunk_size:
                    self._flush_buffer(buffer)
                    buffer = []
                    
            except queue.Empty:
                continue
                
        if buffer:
            self._flush_buffer(buffer)

    def _flush_buffer(self, buffer: list[RecordItem]) -> None:
        if not buffer:
            return
            
        windows = np.stack([item.window for item in buffer])
        y_trues = np.array([item.y_true for item in buffer])
        y_preds = np.array([item.y_pred for item in buffer])
        confidences = np.array([item.confidence for item in buffer])
        
        chunk_name = f"chunk_{self._chunk_count:06d}.npz"
        chunk_path = self._chunks_dir / chunk_name
        
        np.savez_compressed(
            chunk_path,
            eeg_windows=windows,
            labels_true=y_trues,
            labels_pred=y_preds,
            confidences=confidences
        )
        
        self._files.append(chunk_name)
        self._chunk_count += 1
        self._total_windows += len(buffer)

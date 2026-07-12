"""Task module for image paradigm B."""

from __future__ import annotations

from tasks.task_visual import Task as _VisualTask


class Task(_VisualTask):
    task_mode = "image_b"
    label = "图片范式二"

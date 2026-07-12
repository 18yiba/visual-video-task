"""Task module for image paradigm A."""

from __future__ import annotations

from tasks.task_visual import Task as _VisualTask


class Task(_VisualTask):
    task_mode = "image_a"
    label = "图片范式一"

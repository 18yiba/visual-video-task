"""Task module registry for video-EEG experiments."""

from tasks.task_factory import Task, load_task, load_task_from_config, resolve_task_mode

__all__ = ["Task", "load_task", "load_task_from_config", "resolve_task_mode"]

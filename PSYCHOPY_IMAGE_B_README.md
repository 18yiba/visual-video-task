# PsychoPy Image_B EEG Runner

This runner implements the current `image_b` image EEG paradigm in a standalone
PsychoPy script:

```powershell
python psychopy_image_b_experiment.py
```

Recommended use on Windows is to open `psychopy_image_b_experiment.py` from
PsychoPy Standalone/Runner, then install this project's hardware dependencies
into that PsychoPy environment if you need real BrainCo or Neuracle acquisition.
For a separate Python environment, install `requirements-psychopy.txt`.

The script reads `config.yaml` by default. At startup it asks for:

- `subject_id`
- `session_id`
- `device_type`: `brainco` or `neuracle`
- `hardware_dummy_mode`
- fullscreen/windowed mode
- optional max trial count for short tests

Practice screens do not start EEG. The formal experiment starts continuous EEG
through the existing `EegSessionManager`, sends existing marker codes, and saves:

- `continuous_eeg.npy`
- `events.json`
- `metadata.json`
- `behavioral_ratings.csv`
- `trial_log.csv`
- `image_playlist.json`

Useful short dummy test:

```powershell
python psychopy_image_b_experiment.py --max-trials 4 --windowed
```

Press `Escape` to abort and export whatever has already been collected.

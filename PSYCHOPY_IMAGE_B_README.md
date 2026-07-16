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

## BrainCo BCIGo over LSL

The default BrainCo transport is now BCIGo external EDF recording. BCIGo owns
the EEG hardware connection; the experiment publishes the LSL Marker stream.
BCIGo does not publish an EEG LSL Outlet in this workflow.

1. Connect the cap in BCIGo and enable `LSL 实时数据流`.
2. Run the command-line preflight below. It keeps the Marker stream alive while
   waiting up to 60 seconds for BCIGo to subscribe.
3. When the command says the Marker stream is published, scan for it in
   BCIGo and select `visual-video-task-Markers` (source ID
   `visual-video-task-marker`).
4. Start recording once before the first session. Keep that recording running
   across subsequent sessions, and stop it only after all sessions are complete.
   The experiment never stops or copies BCIGo's EDF. Each local session stores
   behavioral files and the event timeline, while `session_start` and
   `session_end` markers delimit sessions in the shared EDF.

```powershell
D:\ProgramData\miniconda3\envs\psychopy_env\python.exe psychopy_image_b_experiment.py --preflight-eeg --real-eeg --device-type brainco --brainco-transport bcigo --brainco-lsl-timeout 60
```

Set `device.brainco_transport: lsl` only when another tool truly publishes an
EEG LSL Outlet. Set it to `sdk` only for direct device access without BCIGo.

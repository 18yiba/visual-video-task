# PsychoPy Image_B behavioral rating and EEG runners

The current design uses two standalone PsychoPy entry points. Behavioral rating
does not connect to EEG hardware or publish external markers:

```powershell
python psychopy_image_b_rating.py
```

EEG repeated viewing is run separately:

```powershell
python psychopy_image_b_experiment.py
```

Recommended use on Windows is to open `psychopy_image_b_experiment.py` from
PsychoPy Standalone/Runner, then install this project's hardware dependencies
into that PsychoPy environment if you need real BrainCo or Neuracle acquisition.
For a separate Python environment, install `requirements-psychopy.txt`.

Both scripts read `config.yaml`. The rating program fixes `session_id=1`. The
EEG program accepts only formal500 sessions 2 through 6.

- `subject_id`
- `experiment_protocol`: `formal500` or `pilot105`
- `session_id`
- `device_type`: `brainco` or `neuracle`
- `hardware_dummy_mode`
- fullscreen/windowed mode
- optional max trial count for short tests

## Image experiment protocols

`formal500` contains six program runs:

- session 1: rate all 500 images once without EEG;
- sessions 2-6: view the same 500 images five times with EEG;
- every session contains five blocks of 100 images;
- rating block breaks are 60 seconds; repeated-viewing breaks allow continuation
  after 30 seconds and auto-continue at 45 seconds;
- the repeated-viewing blank/ITI is fixed at 0.1 seconds; rating-session blank
  and rating timing are unchanged;
- each image therefore has one behavioral rating and five independent EEG
  image-onset events.

Every formal rating item is untimed. The participant changes the default value
with F/J and presses Space to confirm when ready. Reaction time is still saved.

`pilot105` is the one-session feasibility pilot. It contains 105 rated images
in one block. The two protocols use separate fixed subject-set labels by
default (`image_b_500_v2` and `image_b_pilot105_v1`), so a saved 105-image set
cannot accidentally become the formal participant's 500-image set.

The source libraries are also physically separated:

```text
image_library/
├── pilot/       # 105 real photographs + its manifest.json
└── formal/      # 500+ AIGC images + its own manifest.json
```

`pilot105` never scans `formal`, and `formal500` never scans `pilot`.

The first program run for a subject creates the fixed subject image set
atomically. Rating-first and EEG-first workflows therefore reuse the same
image identities.

```powershell
python psychopy_image_b_experiment.py --experiment-protocol formal500
```

The rating program saves behavioral ratings, trial logs, events, metadata, and
the session playlist without creating an EEG file. Each EEG session saves its
own event timeline, metadata, actual order, and local EEG or external-recorder
reference.

After every completed run, `subject_completion_status_<image_set_label>.json`
reports per-image rating completion and valid EEG sessions.

Useful short dummy test:

```powershell
python psychopy_image_b_rating.py --max-trials 4 --windowed
python psychopy_image_b_experiment.py --dummy-eeg --max-trials 4 --windowed
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

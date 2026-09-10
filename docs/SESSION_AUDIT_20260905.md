# Video EEG Session audit — 2026-09-05

## Status and limits

The manifest was not regenerated. Its 7,949 eligible assignments all exist in the
real pool. Formal and Demo now resolve `../video_materials/formal_v1/videos`
relative to the project, not `stimuli/videos`.

The latter contained only ten temporary smoke-test copies. This caused both the
Formal missing-file error and repeated Demo membership despite randomized order.
Those ten copies were hash-checked against originals and removed (13.98 MiB).
No source videos, checkpoints, EEG records or rating data were removed.

F: is exFAT. Rating formal/practice still depend on the common pool. Therefore
moving the pool would break another application, while hardlinks cannot be made
on this filesystem. Session folder materialization is **not completed**. No empty
folders or shortcuts are presented as video folders. Deploy the complete bundle
to NTFS, then run the materialization command below. No duplicate 40 GB copy was
created and no files outside F:\video were changed by this work.

Formal BAT was executed: Session 01 loaded 468 assignments, then exited through
Esc with zero completed videos. This is not proof of first-video playback or EEG
acquisition. Demo BAT reached its operator dialog; two manual fresh playback runs
remain unverified. Programmatic randomness evidence is explicitly separate.

## One source of truth

Authoritative CSV: `video_eeg/config/session_manifest.csv` inside this project.
Version: `video-eeg-session-manifest-v2-duration-diversity`.
Membership seed: 17; algorithm: `duration-bucket-round-robin-v1`.
The manifest's historical `source_library` field is provenance, not the current
runtime path resolver. Its content/hash and existing checkpoint identities were
preserved. `SESSION_MANIFEST_REFERENCE.csv` in formal_v1 points to it; it is not a
second editable manifest.

The files 0176.mp4, 0180.mp4, 0210.mp4, 0228.mp4 and 0244.mp4 all exist in the
real pool and belong to Session 01, at 7.662, 7.685, 8.010, 8.101 and 8.196 seconds.
They were absent only from the incorrect ten-video runtime directory.

## Fresh pool audit

`scripts/audit_session_pool.py` decoded the first frame of all 7,996 MP4 files.
Every first frame was readable; this is not a complete end-to-end corruption scan.
MP4 mvhd container duration was freshly read for all files. OpenCV frame/fps video
track duration is retained separately; it must not replace container duration in
Session progress. Maximum difference between fresh container duration and existing
manifest duration is zero seconds.

Physical pool: 7,996 videos, 51.0861619444 hours, mean 23.000273 s, minimum 5.107 s,
P25 13.886 s, median 16.394 s, P75 29.76725 s, maximum 60.975 s.
No duplicate filenames, non-MP4 videos or unreadable first frames were found.
There is also a non-video manifest.json. The 47 excluded files are 7950.mp4 through
7996.mp4, all longer than 60 seconds.

Eligible pool: 7,949 videos, 50.2984272222 hours, mean 22.779512 s, minimum 5.107 s,
P25 13.863 s, median 16.275 s, P75 29.400 s, maximum 59.976 s.
Mean Session duration 2.9587310131 hours; shortest Session 14 at 10635.727 s,
longest Session 09 at 10669.311 s; difference 33.584 s; population standard
deviation 14.787034 s; coefficient of variation 0.138827 percent.

Fresh complete file/duration evidence: `formal_v1/VIDEO_POOL_AUDIT.csv` and
`VIDEO_POOL_AUDIT.json`. Per-Session statistics and every video assignment are in
`SESSION_SUMMARY.csv` and `SESSION_VIDEO_MAP.csv` alongside the pool.

## Actual partition algorithm

17 Sessions is the study-design choice, not a value inferred from video count.
`build_duration_bucket_assignments` sorts eligible videos by duration, asset ID
and relative path, then splits by rank at floor(N*b/5). Five buckets contain
1589/1590/1590/1590/1590 videos. Equal durations at boundaries can belong to adjacent
buckets; the stored label is authoritative, not a guessed numeric threshold.

| Bucket | Observed duration range (seconds) |
|---|---:|
| very_short | 5.107–12.725 |
| short | 12.725–15.117 |
| medium | 15.117–20.061 |
| long | 20.061–33.598 |
| very_long | 33.598–59.976 |

`build_duration_balanced_manifest` visits buckets shortest to longest. Within
each bucket it orders videos longest first, with seeded tie ordering. It assigns
each video by the lexicographic minimum of (that bucket's assigned count, Session
total duration, Session index). Thus bucket counts are primary, total duration
secondary. There is no swap optimization stage. Video count and bucket duration
are measured, not additional independent optimization terms. Every Session has
93 or 94 videos from each bucket and 467 or 468 videos overall.

## Formal startup and recovery

`run_video_formal.bat` → `scripts/run_video_formal.bat` → package-local
`.venv/Scripts/python.exe -m video_eeg.experiment.video_runner` with formal config,
real EEG and BrainCo SDK options.

`main` → `parse_args` / `load_config` / `apply_cli_overrides` → `_load_psychopy`
→ `startup_dialog` → `load_video_library` → `ensure_session_manifest`
→ `SessionManifest.session_assets(session_id)` → strict file existence validation
→ PsychoPy Window → `VideoRunner.__init__` → `load_state` or `SessionState.new`
→ `VideoRunner.run` → `_show_instructions` → device check / `_start_eeg`
→ queue-driven `_run_trial`.

The operator dialog has subject, Session integer input and fullscreen. Enter 01
through 17 (1 through 17 is equivalent); there is no requested video-count field.
The automatic suggestion uses the default subject before the dialog; if changing
subject, explicitly select the desired Session. It is not a dropdown.

New Formal states now receive an OS-random seed unless --seed was explicitly
provided. `SessionState.new` shuffles the fixed membership and saves seed, queue
and attention plan atomically. Existing states are not reshuffled or rewritten to
new seeds. Manifest version/hash and membership mismatch causes an error.
State lives under `data/sourcedata/<subject>/session_XX/session_state.json`.
Completed IDs and video_attempts preserve completion/attempt order; queue is the
remaining planned order. Skipped/aborted attempts do not count as completed.

## Demo and randomness evidence

Demo still selects ten videos internally with `build_fast_valid_playlist`, but
now from the full real pool rather than ten leftover copies. Fresh Demo uses a
new seed and run-specific Demo storage; explicit seed/smoke can be reproducible.
No formal state is deleted to force Demo randomness.

`scripts/verify_session_randomness.py` samples the real catalog twice, creates two
independent Formal Session-01 states, and atomically saves/reloads one temporary
state. Assertions check Demo difference, same Formal membership/different order,
and unchanged restored queue and attention plan. Output is
`formal_v1/RANDOMNESS_VERIFICATION.json`; these are programmatic examples, not
claims of two human-operated Demo playback runs.

## Preserved behavior

Formal 18 attention tasks; Demo 3; stored net-duration checkpoints with moderate
jitter, evaluated only at completed video boundaries. No automatic timeout.
Left red F = false, right green J = true. Marker 142 remains once at page flip;
responses remain local. Short post-video rest retains Space skip and actual dwell
logging. Long rest remains 30–45 integer net-watch minutes, F continue/J exit.
Rest, instructions, attention and aborted attempts do not increase completed net
duration. S/Esc/resume and atomic checkpoints are unchanged apart from the new-state
Formal seed source. Expected sampling remains 1000 Hz, without software resampling.
Raw/event/attention/rest/BIDS export structures and rating/emotion business code
were not changed. This audit does not certify real EEG or BIDS conversion.

## Folder tool

Run from this project after deployment to NTFS:

```text
.venv\Scripts\python.exe scripts\materialize_session_folders.py --create-links
```

Without --create-links it only exports reports. With the flag it validates all
sources and all existing destinations, rejects unknown/conflicting files without
deleting them, probes hardlink support, creates original-name links, and verifies
all 17 folder sets and samefile identity. Re-running reuses correct links.
On exFAT it explicitly fails before attempting links. `SESSION_VIDEO_MAP.csv`
currently correctly says view_exists=False; it does not claim missing views exist.

## Testing boundary

The earlier 32 tests did not validate the real runtime root against the real
manifest. `tests/test_session_filesystem.py` now checks the actual configured pool,
every assigned file, exactly-17 membership, exclusion set and Demo candidate count.
The full suite at this audit passed 34 tests. Doctor reports missing=0,
duplicate assignments=0, unassigned eligible=0; folder views are separately 0/17.
Doctor exit 0 validates playback prerequisites, not completion of the newly requested
human-readable folder materialization. Full acquisition and two manual Demo runs
must still be verified on the lab computer.

# Creature Capture

Synchronized multi-camera video acquisition for animal behavior experiments
(open field, elevated plus maze, puzzle box, and any experiment you add).

* Live feeds of every camera used by the selected experiment
* One **Start** for all cameras: they all start on the same frame and stop on the same frame
* Greyscale **H.264 MP4, 800 × 600, exactly 20 fps**, encoded on the NVIDIA GPU (NVENC)
* File names from the start time: `2026-11-05_14-32-07_Arena1_Overhead.mp4`
* Fixed output location per experiment: `<base folder>\OpenField\2026-11-05\…`
* Animal and session information saved as CSV (and JSON) next to the videos, plus a master log per experiment
* Camera controls saved per camera and per experiment, re-applied every time
* Crash-safe recording: a crash or power cut keeps everything recorded up to that point
* Dropped camera frames are replaced so timing stays correct, and they are counted, marked and reported

---

## Installing on the recording PC

1. On GitHub, open **Actions → Build Windows app**, click the latest green run and
   download **CreatureCapture-windows** at the bottom of the page.
   (For tagged releases the same zip is attached under **Releases**.)
2. Unzip it anywhere, e.g. `C:\CreatureCapture\`.
3. Run `CreatureCapture\CreatureCapture.exe`. The first time, Windows SmartScreen says
   *"Windows protected your PC"*: click **More info → Run anyway** (the app is not code-signed).

Settings are stored in `%APPDATA%\CreatureCapture\`, **not** in the app folder, so
installing a newer build keeps all camera assignments and settings.

**Updating to a new version:** unzip the new build (to a new folder or over the old one)
and run it. There is nothing to copy: settings, experiments, camera assignments, camera
controls and the animal list are all in `%APPDATA%\CreatureCapture\`, and videos and logs
are in the video folder chosen in Settings → Output (`D:\BehaviorVideos` by default). Keep
the video folder outside the app folder; the app warns if it isn't, and asks before
recording if the video folder can't be found (drive not plugged in, or folder moved).

### Check the install (optional)

Open a Command Prompt in the app folder and run:

```bat
CreatureCapture.exe --self-test
```

then open `%APPDATA%\CreatureCapture\selftest.txt`. It lists the cameras found,
whether the NVIDIA encoder works, and the result of a 3-second test recording.

---

## First-time setup (Settings tab)

1. **Base folder**: where all videos go, e.g. `D:\BehaviorVideos`. The app creates
   `OpenField`, `ElevatedPlus`, `PuzzleBox` (one folder per experiment) inside it.
2. **Cameras**: for each camera position (Arena 1 Overhead, Arena 1 Horizontal,
   Arena 2 Overhead, Arena 2 Horizontal, Camera 5) choose the physical camera from the list.
   Select a row to see its live feed and confirm it is the right camera.
   Cameras are remembered by the USB port they are plugged into, so **keep every camera in the same port**.
   Click **Refresh camera list** after plugging cameras in.
3. **Camera controls**: click **Camera controls…** in the camera's row, next to where it is
   assigned. The same window opens from the **Camera controls…** button above each feed on the
   Record tab. Settings are saved for that camera *in that experiment* (so Camera 5 has separate
   settings for Elevated Plus and Puzzle Box, and its button asks which). A camera position you
   add gets the same button and starts from the standard settings.
   * Tick **Manual control** to set a value yourself with its slider. Unticked, the camera keeps
     control of that setting.
   * **Auto exposure** and **Auto white balance** have one Manual control box each. Ticked, choose
     **Auto on** or **Auto off**; with Auto off, the Exposure or White balance slider appears.
   * Keep exposure under manual control with **Auto off** and the slider at **-5 or lower**
     (1/32 s or shorter): a longer exposure cannot deliver 20 fps.
   * *Open camera driver dialog…* gives access to the camera's own settings window, including
     anti-flicker (power-line frequency).
4. **Lock settings**: tick the box at the top of Settings. While it is ticked nothing in
   Settings, and no camera controls, can be changed; untick it deliberately to make a change.

## Recording (Record tab)

1. Choose the **Experiment**. The app opens that experiment's cameras.
2. Choose the **Length** from the list or type any number of minutes.
3. Fill in **Experimenter** (required) and each arena's **Animal ID** (required) and any other
   fields. If an animal list is loaded, pick the animal and the rest fills in.
4. Open field: untick an arena (its box title) if only one arena is in use. A single camera
   can be left out with its **Record this camera** box. Feeds that will not be recorded are
   greyed out and marked NOT RECORDING, whether or not a camera is assigned.

   **Check each feed's frame rate before you start.** The line under each feed shows the rate the
   camera is really delivering. If it is below the capture rate asked for (30 fps unless changed in
   Settings), the line shows an orange ⚠ and the feed gets an orange border. If it is below 20 fps,
   the ⚠ and border are red: the camera is too slow for the video, and every recording from it
   will contain repeated frames. A camera that has stopped sending frames is flagged in red too.
   The usual causes are an exposure longer than 1/32 s, or the camera running in a slow mode.
5. Press **Start recording**. Recording begins immediately, so you can record placing the animal.
   It stops automatically at the set length, or press **Stop** (the trial is then logged as *stopped early*).
6. When saving finishes, a summary appears. If any camera dropped frames it is shown as a warning.

After a trial the Animal ID and Notes are cleared, ready for the next animal; other fields are kept.

**Trial day** is the same pick-or-type list (1, 2, 3, …) for every experiment. Experiments with
more than one session per trial day (Puzzle Box, or any experiment with that box ticked in
Settings → Experiments) also show **Session that day**, with the same list. Experiments with one
session per day show Trial day only, and no session is saved for them.

## What gets saved

For an open field trial started at 14:32:07 on 5 Nov 2026 (with date subfolders on):

```
D:\BehaviorVideos\OpenField\
├── OpenField_log.csv                          ← master log: one row per animal per trial
└── 2026-11-05\
    ├── 2026-11-05_14-32-07_Arena1_Overhead.mp4
    ├── 2026-11-05_14-32-07_Arena1_Horizontal.mp4
    ├── 2026-11-05_14-32-07_Arena2_Overhead.mp4
    ├── 2026-11-05_14-32-07_Arena2_Horizontal.mp4
    ├── 2026-11-05_14-32-07_Arena1_info.json   ← animal + session info, length set/actual, per-camera details
    ├── 2026-11-05_14-32-07_Arena2_info.json
    └── 2026-11-05_14-32-07_<arena>_<camera>_frames.csv ← per-frame timestamps for each camera
```

Every video is named `<date>_<time>_<arena>_<camera label>.mp4`, so an Elevated Plus trial
gives `2026-11-05_14-32-07_EPM_Overhead.mp4`. Arena names and camera labels use only letters,
digits and `-`.

Log columns (the log is for people; Track Tamer reads only the JSON): date, start_time,
assay, assay_variant, phase, arena, experimenter, cohort, animal_id, sex, strain, dob, treatment,
trial_day, session_number, notes, duration_set_min, duration_actual_s, stopped_early, frames,
repeated_frames, videos, encoder, app_version. A master log from an older version gets the new
columns added automatically the first time a trial is logged. Earlier versions also wrote
an `_info.csv` per arena with the same row; it is no longer written because the log already has it.

### The info file (`_info.json`)

The `_info.json` follows the **Track Tamer video metadata standard, schema 1 (draft)**
([docs/metadata_standard.md](docs/metadata_standard.md)), so Track Tamer can fill in the trial details
by itself. Creature Capture writes each info file once, when the trial ends, and never changes
it afterwards. Track Tamer later adds its own `track_tamer` section to the file (the setup drawn
for that video and its tracking settings), leaving everything below as written. In short:

* `schema_version` (`1`), `app_name`, `app_version`, and `date` and `start_time` from this
  computer's clock.
* `assay`: the experiment's **Assay type** (Settings → Experiments), written exactly as in the
  standard: `Open Field`, `Elevated Plus Maze`, `Object Recognition`, `Puzzle Box`, … An
  experiment set to *Other* (e.g. a pilot) writes its own name. `assay_variant` and `phase` come from that
  assay's own lists and are chosen on the Record tab; the choices appear only for assays that
  have them (e.g. Object Recognition: variant *Novel Object Recognition* or *Spatial Object
  Recognition*, phase *Habituation*, *Training* or *Test*).
* `arena`, `experimenter`, `cohort` (shown as *Cohort / litter*), `animal_id`, `sex` (`F`, `M`,
  or `U` when not recorded), `strain`, `dob`, `treatment`, `trial_day` (day of a multi-day
  trial), `session_number` (which session that day; only for experiments with more than one
  session per trial day, such as Puzzle Box), `notes`, `duration_set_min`,
  `duration_actual_s` and `stopped_early` (`true`/`false`). Blank fields are left out.
* Object Recognition only: `objects`, one per object with `name` (`object 1`, …), `identity`,
  `kind` (`Familiar`, `Novel`, `Moved`) and `position`, entered on the Record tab per arena.
* `cameras`: one entry per camera in that arena with `label`, `camera_position` (the camera
  position from Settings, e.g. `Camera5`), `camera_settings`, `video`, `timestamps_csv`,
  `fps_set`, `fps_measured`, `width_px`, `height_px`, `frames`, `verified_frames_in_file`
  (frames counted in the finished MP4), `repeated_frames`, `repeated_frame_indices` (from 0,
  like the video), and `error` (only if there was one). `camera_settings` lists every setting
  used, changed or not: the video `encoder` plus each camera control (auto_exposure, exposure,
  gain, brightness, contrast, gamma, sharpness, auto_wb, wb_temperature) with `apply` and
  `value`. `apply` is the **Manual control** box: `false` means the camera kept control.
* Creature Capture's own fields are in a `creature_capture` object: `experiment` (the
  experiment's name) and `gpu`.

The frame times in each camera's `_frames.csv` are the record of timing, one row per video frame: `frame` (from 0),
`video_time_s`, `tick_time_s`, `camera_frame_time_s`, `camera_frame_seq`, `repeated`
(`true`/`false`).

If the master log is open in Excel when a trial finishes, the row is saved to
`OpenField_log_pending.csv` and merged into the log automatically after the next trial.

### Text in the video

The top-left corner of every frame shows `00:03:27.45  F004149  20 fps`: elapsed time,
frame number and frame rate. A `*` is added on repeated frames. Text size and contents
can be changed in Settings. When cropping for ezTrack/DeepLabCut, the text occupies only
a thin strip (about 20 px) at the top-left.

## How synchronization works

Every camera is read continuously in its own thread. A single clock ticks exactly 20 times per
second; at each tick it takes the newest frame from every camera in the trial. So all videos start
and stop on the same tick, have the same number of frames, and frame *N* of every video was
captured within about one camera frame (≤ 33 ms at the default 30 fps capture rate) of the same moment.

If a camera has not delivered a new frame since the last tick, the previous frame is written again
so the video stays in real time. These repeated frames are counted in the logs, listed by frame
number in `_info.json` and `_frames.csv`, and marked with `*` in the video.

## Crash safety

While recording, each video is written as `…​.recording.mp4` (fragmented MP4, playable up to the
last second). When the trial ends it is converted, without re-encoding, to a standard `.mp4`.
If the app or PC crashes, the next time Creature Capture starts it offers to convert any leftover
`.recording.mp4` files.

## Adding experiments

**Settings → Experiments → New…**: give it a name, an **assay type** (from the Track Tamer list,
or *Other*), whether it has **more than one session per trial day**, an output folder, length choices, and one row per camera (arena name, camera
position, camera label). Rows with the same arena name share one animal. Arena names and camera
labels may use only letters, digits and `-`.

## Animal list

**Settings → Animal list → Import CSV…**: a CSV with a header row. Recognised columns (any case):
`animal_id`/`ID`, `sex`, `strain`/`genotype`, `dob`/`date of birth`, `treatment`/`group`.
Use **Save blank template…** for a ready-made file.

---

## Running from source with Anaconda (Mac or PC)

Requires Anaconda, Miniconda or Miniforge. The scripts find conda automatically by
locating its `etc/profile.d/conda.sh` (Mac) or `condabin\conda.bat` (Windows) in the usual
install locations. If yours is somewhere unusual, set `CONDA_BASE` to the conda folder first.

| | Mac | Windows |
|---|---|---|
| Install / update the `creature_capture` environment, then run the self-test | `Install Creature Capture.command` | `Install Creature Capture.bat` |
| Start the program | `Creature Capture.command` | `Creature Capture.bat` |

These four files and this README are all there is in the main folder. Everything the program
itself needs is in `app/`, and the roadmap and metadata standard are in `docs/`; you don't need
to open either. Keep the folders together: the install and run files look for `app/` next to them.

Double-click the file. On a Mac, the first time macOS may refuse to open a downloaded
`.command`: right-click it → **Open** → **Open**. If it opens in a text editor instead, run it from
Terminal with `bash "Install Creature Capture.command"`. macOS also asks for permission for
Terminal to use the camera the first time.

Running the install file again updates the environment after you download a newer version. It
changes the existing environment in place; it does not rebuild it.

**Package versions are fixed.** `app/environment.yml` and `app/requirements.txt` name the exact version
of Python and of every package that the tests pass with, on the Mac and in the Windows build
(Python 3.12.10, PySide6 6.10.3, OpenCV 4.14.0.94, NumPy 2.5.4, imageio-ffmpeg 0.8.1). The
install file installs exactly those. A test fails if the files disagree with each other or
with the environment the tests run in; if it fails after you download a newer version, run the
install file again. To move to a newer package version: change it in both files, run the
install file, and run the tests.

## Development

All commands are run from the `app/` folder.

```bash
cd app
conda env create -f environment.yml     # or, with Python 3.12.10: python3 -m venv .venv && pip install -r requirements-dev.txt
conda activate creature_capture
python run_creature_capture.py
```

Without real cameras, set **Settings → Testing without cameras → Test-pattern cameras** to 5 and
assign them to the positions. On a Mac, the built-in camera also appears in the list (camera controls
are mostly not supported on macOS; they work on Windows).

Run the tests (from `app/`):

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

### Builds

`.github/workflows/build-windows.yml` runs on every push: it runs the tests, builds
`CreatureCapture.exe` with PyInstaller on Windows, runs `--self-test` on the packaged app and
uploads the zip as an artifact. Pushing a tag like `v0.1.0` also attaches the zip to a GitHub Release.

### Code layout

The program is in `app/`: `creature_capture/` (below), `tests/`, `scripts/` (finds conda for the
install and run files), `environment.yml`, the `requirements` files and `run_creature_capture.py`.

| File | Purpose |
|---|---|
| `app/creature_capture/config.py` | Settings file, default experiments and camera positions |
| `app/creature_capture/devices.py` | Camera discovery (DirectShow device paths via FFmpeg) |
| `app/creature_capture/camera.py` | Capture threads, camera controls |
| `app/creature_capture/recorder.py` | Shared 20 fps clock, encoders, overlay, crash-safe output |
| `app/creature_capture/records.py` | Animal info, per-trial CSV/JSON, master log |
| `app/creature_capture/ffmpeg_util.py` | FFmpeg location, NVENC detection, remux/recovery |
| `app/creature_capture/ui/` | Qt interface (Record tab, Settings tab, dialogs) |
| `app/creature_capture/selftest.py` | `--self-test` end-to-end check |

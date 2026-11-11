# Track Tamer video metadata standard

**Schema 1 (draft, 2026-11-06).** The trial information that any app
recording videos for Track Tamer saves beside its videos, so Track Tamer can
fill it in automatically (ROADMAP §16). **Track Tamer owns this standard**:
apps that generate video follow it, and changes are made here first, then in
the apps. It stays a draft until the user says otherwise; while it's a draft,
changes don't raise `schema_version`. Reading it in Track Tamer is planned
for after Track Tamer 1.0.

Apps covered so far: **Creature Capture**, **Boom Box** and **Pellet
Paparazzi** (see "Apps" at the end). Apps whose videos Track Tamer doesn't
analyze follow it too, where the fields apply, so every lab data file has
the same fields with the same names.

---

## 1. Files and names

For each trial, per arena, an app writes beside the videos:

| File | What it is |
|---|---|
| `<date>_<time>_<arena>_info.json` | the trial information (this standard). **The only file Track Tamer reads for trial information.** |
| one video per camera | named in `cameras[].video` |
| one `_frames.csv` per camera | the measured time of every frame, named in `cameras[].timestamps_csv` |
| `<date>_<time>_<arena>_info.csv` (optional) | for people (e.g. a spreadsheet log); Track Tamer doesn't read it |

**Name parts:**
- `<date>` is `YYYY-MM-DD`.
- `<time>` is the start time as `HH-MM-SS` (24-hour; dashes because `:`
  isn't allowed in Windows file names).
- `<arena>` and `<camera label>` use letters, digits and `-` only: **no
  spaces and no `_`**, so names can be split reliably.

Example: `2026-11-05_16-56-42_EPM1_info.json`.

**Videos** are named `<date>_<time>_<arena>_<camera label>.mp4`
(e.g. `2026-11-05_16-56-42_EPM1_Overhead.mp4`). Every video name must be
unique within its folder.

**How Track Tamer matches a video to its info file:** it reads every
`*_info.json` in the video's folder and picks the one whose `cameras[].video`
lists the video's exact file name. If a video was renamed, a name starting
with the info file's `<date>_<time>_<arena>_` still matches, after the user
confirms. So: write bare file names (no folders), exactly as on disk, and
keep videos and their info file together.

**Reserved endings.**
- For the apps: `_info.json`, `_info.csv`, `_frames.csv`, `_trials.csv`.
- For Track Tamer's own files (added to a video's name, so apps must not use
  them): `_LocationOutput.csv`, `_reference.png`, `_ObjectScoring.csv`,
  `_analysis.xlsx`, `_path.png`, `_heatmap.png`, `_tracked.mp4`,
  `_MotionIndex.csv`, `_trace.png`, `_aligned.png`.

Track Tamer skips `_frames.csv`, `_info.csv` and `_trials.csv` when a folder is
added.

---

## 2. How an info file is organized

Every info file has up to three kinds of fields:

| Kind | Where it goes | Who writes it |
|---|---|---|
| **Standard fields** (section 4) | top level, and in each `cameras` entry | every app, using only the ones it has (the required ones are a must) |
| **Assay fields** (section 5) | top level | only for that assay (e.g. `objects` only for Object Recognition) |
| **App fields** | inside one object named after the app, in lowercase with `_` (`creature_capture`, `startle_box`, …) | only that app |

An app writes **only the standard fields it has**: anything it doesn't know
is left out, never filled with blanks. Anything the standard doesn't cover
goes in the app's own object, never at the top level, so it can't clash
with a standard field added later or with another app's field of the same
name. Per-camera app fields go in an object of the same name inside that
camera's entry.

Track Tamer reads the standard and assay fields, copies the app objects
into the export's Settings sheet as they are, and otherwise ignores them. If
a field in an app object turns out to be useful to Track Tamer or needed by
several apps, it's added to the standard (section 7) and apps move it to
the top level.

Example, from a Creature Capture Open Field trial:

```json
{
  "schema_version": 1,
  "app_name": "Creature Capture",
  "app_version": "0.2.0",
  "date": "2026-11-05",
  "start_time": "16:56:42",
  "assay": "Open Field",
  "arena": "OF2",
  "animal_id": "M7",
  "treatment": "saline",
  "trial_day": 1,
  "session_number": 1,
  "duration_set_min": 60,
  "cameras": [
    {
      "label": "Overhead",
      "camera_position": "Camera5",
      "video": "2026-11-05_16-56-42_OF2_Overhead.mp4",
      "timestamps_csv": "2026-11-05_16-56-42_OF2_Overhead_frames.csv",
      "fps_measured": 9.84,
      "camera_settings": {"encoder": "libx264", "exposure": {"apply": true, "value": -5}}
    }
  ],
  "creature_capture": {"experiment": "Open Field 60 min", "gpu": false}
}
```

Here `assay`, `animal_id` and the rest are standard fields. There are no
assay fields, since Open Field has none. `experiment` and `gpu` are Creature
Capture's own fields, so they sit in its object.

---

## 3. Assay names, variants and phases

Three fields say what was run, each from a fixed list:
- **`assay`**: the test. Track Tamer uses it to pick its analysis.
- **`assay_variant`**: the version of that test, when the test has versions
  (e.g. which object task). Left out for tests without versions.
- **`phase`**: which session of the test this is, when the test has
  sessions.

Write each **exactly** as shown. Track Tamer's matching ignores upper/lower
case and spaces at the ends.

| `assay` | Track Tamer | `assay_variant` (one of) | `phase` (one of) |
|---|---|---|---|
| `Elevated Plus Maze` | built | | |
| `Open Field` | built | | |
| `Object Recognition` | built | `Novel Object Recognition`, `Spatial Object Recognition` | `Habituation`, `Training`, `Test` |
| `Acoustic Startle Response` | planned (ROADMAP §13) | `Prepulse Inhibition`, `Startle Habituation` | |
| `Conditioned Place Preference` | planned | | `Pretest`, `Conditioning`, `Test` |
| `Puzzle Box` | not decided (listed so the name is the same everywhere) | | |
| `Skilled Reaching` | not analyzed in Track Tamer (listed for consistency) | | |

Variants of one assay share Track Tamer's analysis: an object trial is
analyzed the same way whichever variant it is (the user marks each object
Familiar, Novel or Moved when drawing it). The variant is recorded in the
Summary, so trials can be told apart, which matters in Habituation and
Training, when every object is familiar.

New assays, variants and phases are added to this table as Track Tamer
analyzes them, or when a lab app records them (so the names stay the same
everywhere), even if Track Tamer never analyzes them. An app may record an
assay that isn't listed (e.g. a pilot); Track Tamer then asks the user to
choose the test.

---

## 4. Standard fields

JSON, UTF-8. **Required:** `schema_version`, `assay`, `animal_id`, and
`cameras`, with each camera's `video`, `camera_position` and
`camera_settings`. Everything else is optional but used when present.
Leave a field out when it's unknown or empty; don't write `""` or `null`.
Numbers are JSON numbers; yes/no values are `true`/`false`. Frames are
counted from **0**, the same as the frames in the video file.

### Trial and animal
| Field | Type | What it is | Track Tamer uses it to |
|---|---|---|---|
| `schema_version` | number | `1` | read the file correctly |
| `app_name`, `app_version` | text | the app that wrote it | Settings sheet |
| `date` | `YYYY-MM-DD` | trial date, from the recording computer's clock | Summary column |
| `start_time` | `HH:MM:SS` | start time, from the recording computer's clock | Summary column |
| `assay` | text | from section 3 | **set the test type** |
| `assay_variant` | text | from section 3's list for that assay (left out if it has none) | Summary column |
| `phase` | text | from section 3's list for that assay | Summary column; Object Recognition phase |
| `arena` | text | arena name (as in the file name) | Summary column; draft crop, scale and regions from that arena's last video |
| `room` | text | room or rig | Summary column |
| `experimenter` | text | who ran it | Summary column |
| `cohort` | text | **Cohort / litter** (label it that way on screen; the field name stays `cohort`) | Summary column |
| `animal_id` | text | animal ID | **Summary column** |
| `sex` | text | `F`, `M`, or `U` (unknown or not recorded) | Summary column |
| `strain` | text | strain or genotype | Summary column |
| `dob` | `YYYY-MM-DD` | date of birth | age on the test day |
| `treatment` | text | treatment or group (a blinded code is fine) | **Summary column for comparing groups** |
| `trial_day` | number | day of a multi-day trial (1, 2, …) | Summary column; Object Recognition trial day |
| `session_number` | number | which session that day, when there's more than one in a day (1, 2, …) | Summary column |
| `notes` | text | | export |
| `duration_set_min` | number | length chosen, in minutes | **set the session length** |
| `duration_actual_s` | number | length actually recorded, in seconds | warn if shorter than the session length |
| `stopped_early` | true/false | | warn |

### `cameras`: one entry per camera in this arena
| Field | Type | What it is | Track Tamer uses it to |
|---|---|---|---|
| `label` | text | camera label (as in the video name) | Settings sheet |
| `camera_position` | text | where the camera is (the app's camera position or slot, e.g. `Camera5`) | Settings sheet |
| `camera_settings` | object | **every** setting used, whether changed or not, including the video `encoder` (e.g. `{"encoder": "libx264", "exposure": {"apply": true, "value": -5}, …}`) | Settings sheet |
| `video` | text | the video's file name | **match the video** |
| `timestamps_csv` | text | its `_frames.csv` file name | **the frame times (the record of timing)** |
| `fps_set` | number | frame rate asked for | Settings sheet |
| `fps_measured` | number | frames ÷ recorded seconds, from the frame times | check |
| `width_px`, `height_px` | number | frame size | check |
| `frames` | number | frames written (including repeats) | check the video is complete |
| `verified_frames_in_file` | number | frames counted in the finished file | check (should equal `frames`) |
| `repeated_frames` | number | frames repeated to keep timing | Summary column |
| `repeated_frame_indices` | list of numbers | which frames, from 0 | kept for timing, left out of speed peaks |
| `error` | text | error message (left out if none) | warn |

### `_frames.csv`
One row per video frame: `frame` (from 0), `video_time_s`, `repeated`
(`true`/`false`), and any of the app's own timing columns (e.g.
`tick_time_s`, `camera_frame_time_s`, `camera_frame_seq`).

**These measured times are the record of timing.** Track Tamer takes each
frame's time from `video_time_s`, and uses `fps_measured` and the video
file's own frame rate only as checks (or when there's no `_frames.csv`).

---

## 5. Assay fields

Written only for those assays.

### Object Recognition
| Field | Type | What it is |
|---|---|---|
| `objects` | list | one entry per object: `name`, `identity` (what it is, e.g. `glass bottle`), `kind` (`Familiar`, `Novel` or `Moved`), `position` (e.g. `top left`) |

`name` must be `object 1`, `object 2`, … in order: those are the names
Track Tamer gives the objects, so each object's type can be matched. Track
Tamer sets each object's type; the user draws the circles.

### Acoustic Startle Response
`stimuli`: one entry per trial that took place, in order.

| Field | Type | What it is |
|---|---|---|
| `frame` | number | video frame at the event time, from 0 (required) |
| `video_time_s` | number | event time, seconds from frame 0. Track Tamer's windows use this when present |
| `type` | text | `pulse`, `prepulse+pulse`, `prepulse` or `none` |
| `pulse_db`, `prepulse_db` | number | levels in dB SPL (absolute, not above background) |
| `interval_ms` | number | prepulse onset to pulse onset (`prepulse+pulse` only) |
| `pulse_freq_hz` | number | tone frequency; left out for noise |
| `pulse_stimulus` | text | `tone` or `noise` |

For `prepulse+pulse` the event time is the **pulse**; the prepulse started
`interval_ms` earlier. Track Tamer's startle window starts at the event time.
Its baseline window ends at the event time, or at the prepulse onset on
`prepulse+pulse` trials.

### Conditioned Place Preference (planned)
To be added when its analysis is built (e.g. which chamber was paired with
the drug, the conditioning session number, and the chamber the animal was
confined to in a conditioning session).

---

## 6. General rules

- Write the JSON in one go when recording stops (write to a temporary name,
  then rename), so a crash never leaves half a file.
- These files hold animal information: they're research data and stay off
  GitHub, like the videos. (This standard itself is fine to share.)

---

## 7. Changing the standard

- Track Tamer owns this file. Changes are agreed here, then made in the apps.
- While the standard is a draft, changes don't raise `schema_version`.
- After that: **adding** an optional field doesn't change `schema_version`;
  **renaming, removing, or changing the meaning** of a field raises it by 1,
  and Track Tamer keeps reading every earlier version.

### Changes
- **Schema 1 (draft, 2026-11-06):** first version, built from Creature
  Capture's `_info.json`. Revised the same day: assay, variant and phase
  each from a fixed list per assay (`Object Recognition` with variants
  `Novel Object Recognition` and `Spatial Object Recognition`; `Acoustic
  Startle Response` with `Prepulse Inhibition` and `Startle Habituation`);
  `phase` made a standard field with a
  list per assay; `start_wall_clock` removed (date and start time come from
  the recording computer's clock); `session_number` added (sessions within
  a day; `trial_day` is the day of a multi-day trial); `sex` may be `U`;
  `slot` renamed `camera_position`, and it and `camera_settings` (now
  including `encoder`) became required standard camera fields; the frame
  times in `_frames.csv` are the record of timing; Track Tamer reads only
  the JSON. Then removed (not recorded in the lab): `weight_g`, `cage`,
  `ear_tag`, dose fields, `arena_size_cm`,
  `environment`; `cohort` is labeled "Cohort / litter".
- **Schema 1 (draft, 2026-11-09):** startle `stimuli` settled from Boom Box
  1.1, with `pulse_freq_hz` and `pulse_stimulus` added.
- **Schema 1 (draft, 2026-11-10):** `Fear Conditioning` removed from the
  assay list (user: it won't be captured). An info file that still says it
  is treated like any assay not on the list.
- **Schema 1 (draft, 2026-11-10):** `Puzzle Box` added to the assay list
  (user). It has trial days and several sessions on each day, so its files
  carry `trial_day` and `session_number`; no variant or phase.

---

## Apps

### Creature Capture
Writes `<date>_<time>_<arena>_info.json` (and `_info.csv`) per arena per
trial, one MP4 and one `_frames.csv` per camera.

**Matches the revised schema 1 draft** (reported by Creature Capture,
2026-11-06; committed and pushed, confirmed 2026-11-10). Its `fps_measured`
is measured from the recording clock: (frames - 1) / (last tick - first
tick). Its assay list is the section 3 list without `Skilled Reaching`,
plus Other. For `Puzzle Box` it writes arena `PuzzleBox` and camera
`Overhead`, with `trial_day` and `session_number`:
- `schema_version`, `app_name`, `app_version`; `date` and `start_time` from
  the recording computer (no `start_wall_clock`).
- `assay`, `assay_variant` and `phase` from each assay's own lists in
  section 3, shown on its Record tab only when the assay has them; values
  outside a list are dropped.
- `trial_day` and `session_number`; `sex` F, M or U; `cohort` labeled
  "Cohort / litter"; numbers and `true`/`false` types; blank fields left out.
- Arena names and camera labels use letters, digits and `-` only (the
  editor enforces it, and output is cleaned); videos named
  `<date>_<time>_<arena>_<camera label>.mp4`.
- Each camera: `camera_position` and `camera_settings` (the `encoder` and
  every control, defaults filled in), `fps_set`, `fps_measured`,
  `width_px`, `height_px`, numeric `repeated_frames`, frames counted from 0,
  `error` left out when empty.
- `objects` for object trials. The `creature_capture` object holds only
  `experiment` and `gpu`.
- None of the fields left out of the standard (weight, cage, ear tag, dose,
  arena size, environment).
- The JSON is written in one go.

Creature Capture keeps a copy of this file (`Creature_Capture/metadata_standard.md`),
taken from GitHub; refresh it from GitHub whenever the standard changes.

### Boom Box
Acoustic startle recording. `assay` = `Acoustic Startle Response` (variants
`Prepulse Inhibition`, `Startle Habituation`); arena `ASR1`, camera label
`Side`. App-only fields in `boom_box`. Boom Box 1.1's full data guide is its
`TRACK_TAMER_DATA.md`.

**To change:** add `pulse_freq_hz` and `pulse_stimulus` to each `stimuli`
entry (section 5). Until then Track Tamer reads them from `boom_box.trials`,
which lines up with `stimuli` by position.

### Pellet Paparazzi
Skilled reaching recording. **Not analyzed in Track Tamer** (the task and
its analysis are different); it follows this standard where the fields
apply, so its data files match the rest of the lab's. `assay` =
`Skilled Reaching`. App-only fields in `pellet_paparazzi`. Its fields will
be listed here once its info file is written.

<!-- Add a section here for each new app as it's brought in. -->

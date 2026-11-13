# Creature Capture roadmap

Last updated 2026-11-12. Tick items off as they're done.

Where things stand: v0.2.0 is the released version (tagged 2026-11-12). It adds the
Track Tamer metadata standard, the code review fixes, Puzzle Box as a standard assay,
the Trial day / Session dropdowns, greyed-out feeds for cameras that won't be
recorded, a 90 min length for Open Field, the new camera controls, the slow-camera
flag, and drops the per-arena `_info.csv`. Every commit on `main` passes the automated
tests and the Windows build, but **nothing has run on the recording PC yet**.

Every release gets a `v` tag on GitHub (v0.1.0, v0.2.0, …), which attaches the Windows
zip to a GitHub Release that doesn't expire. Build to test on the recording PC: the zip
on the newest release, or for a commit after it, the zip from that commit's green run
under GitHub Actions (downloads last 30 days, named
`CreatureCapture-<version>-<commit>-windows.zip`).

## Phase 1: Prove it on the recording PC

- [ ] Install the test build above from a USB drive. The window title should say
      Creature Capture 0.2.0.
- [ ] Run `CreatureCapture.exe --self-test` and confirm `selftest.txt` shows
      `h264_nvenc` available with the Quadro RTX 4000. If not, install NVIDIA driver
      582.99 and run it again.
- [ ] Assign the real cameras and confirm they are remembered after a restart.
- [ ] Record full-length trials with all cameras. Repeated frames should stay near
      zero, and every video in a trial should have the same frame count.
- [ ] Force-quit during a recording and confirm the app offers to recover the videos
      on the next start.
- [ ] Try the newer form fields in real use: Assay type, Variant, Phase, the objects
      table, Trial day, and Session that day (Puzzle Box).
- [ ] Untick an arena and a single camera and check the greyed-out NOT RECORDING
      feeds are clear enough on the PC's screen, including a position with no camera.
- [ ] Check Open Field offers 90 min and a 90 min trial records and saves correctly.
- [ ] With the real cameras, confirm every feed reads close to 30 fps with no ⚠ flag.
      Then set a long exposure (above -5) on one and check its feed turns orange or red.
- [ ] Camera controls (the button in each camera's row in Settings → Cameras, or the
      button above a feed): with
      the real cameras, check that Manual control, Auto on / Auto off and the sliders
      change the picture as expected, and that "Camera reports" shows the values.
      These controls only act on real cameras under Windows, so this is their first
      real test.
- [ ] Check the video names suit downstream tools. Elevated Plus videos are now
      `<date>_<time>_EPM_Overhead.mp4`.

## Phase 2: Settle the handoff with Track Tamer

The metadata standard (`docs/metadata_standard.md`, owned by Track Tamer) is final:
schema 1, finalized 2026-11-12. Optional fields, assays, variants and phases can still
be added; renaming or removing a field, or changing what one means, makes it schema 2,
so raise any such change with Track Tamer first.

- [ ] Test Track Tamer against real Creature Capture output and fix whatever doesn't
      line up.
- [ ] Decide: save the trial details at the start of a recording, so a crash doesn't
      lose the animal information? Today the info JSON and the master-log row are
      written only when a recording ends. Needs agreeing with the standard, which
      says to write the JSON once at the end.
- [ ] Decide: lift the 10,000-entry limit on `repeated_frame_indices` in the JSON?
      The count is always right and `_frames.csv` always has the full list.
- [ ] Decide: keep Acoustic Startle Response in the Assay type list? The standard
      says the Boom Box app records it.
- [x] Take the standard out of draft (schema 1 final, 2026-11-12; nothing Creature
      Capture writes had to change).

## Phase 3: Release

- [x] Raise the version number to 0.2.0 (done 2026-11-10, so test builds are
      labelled correctly).
- [x] Tag `v0.2.0` so the Windows zip is attached to a GitHub Release (2026-11-12).
- [ ] Update the README install steps to cover the offline USB route.
- [ ] Once phases 1 and 2 are settled, raise the version again and tag that release.

## Later

- [ ] Conditioned Place Preference: the standard will add fields for it (such as
      which chamber was paired) when Track Tamer builds that analysis. Creature
      Capture will need a way to record them.
- [ ] Code signing, to remove the "Windows protected your PC" warning on first run.

## Done

- [x] v0.1.0 released with the Windows zip (2026-11-06).
- [x] Camera thread crash on Windows fixed (in v0.1.0).
- [x] `_info.json` follows the Track Tamer metadata standard, schema 1 draft.
- [x] Code review pass: recording robustness fixes, simpler code, Windows and Mac
      checks (2026-11-10).
- [x] Fear Conditioning removed from the assay list and from the standard; it won't
      be recorded.
- [x] Puzzle Box added as a standard assay, with Trial day and Session that day. Not
      analyzed in Track Tamer for now.
- [x] Trial day is the same pick-or-type list for every experiment; Session that day
      appears only for experiments with more than one session per trial day.
- [x] v0.2.0 released and tagged, with the Windows zip (2026-11-12).
- [x] Feeds that won't be recorded are greyed out and marked NOT RECORDING, with or
      without a camera assigned.
- [x] Open Field length choices include 90 min.
- [x] Camera controls reworded to "Manual control" with Auto on / Auto off for
      exposure and white balance, and also opened from each camera's row in Settings.
- [x] Install files pin the exact Python and package versions tested on the Mac and
      in the Windows build (2026-11-11).
- [x] Main folder holds only the install and run files and the README; program files
      are in `app/`, documents in `docs/` (2026-11-11).
- [x] The window can be made much narrower (about 840 wide, was 1420): feeds shrink,
      camera names shorten with "…", and the two controls above each feed use short
      labels when space is tight (2026-11-11).
- [x] A feed is flagged (orange, or red below 20 fps) when its camera runs below the
      rate asked for or stops sending frames (2026-11-11).
- [x] The per-arena `_info.csv` is no longer written: the same row is already in the
      experiment's log, and the `_info.json` has everything else (2026-11-11).
- [x] Video folder checks for updates: a warning when the video folder is inside a
      Creature Capture program folder (in Settings and at startup), and a question
      before recording when the video folder can't be found, instead of silently
      making a new one. README says what an update needs: nothing to copy (2026-11-12).

# Creature Capture roadmap

Last updated 2026-11-10. Tick items off as they're done.

Where things stand: v0.1.0 is the released version. `main` is ahead of it with the
Track Tamer metadata standard, the code review fixes, Puzzle Box as a standard assay
and the Trial day / Session dropdowns. Builds from `main` now report version 0.2.0,
so files made while testing are labelled with the new version. Every commit on `main`
passes the automated tests and the Windows build, but **nothing has run on the
recording PC yet**. The v0.2.0 release is not tagged until phases 1 and 2 are settled.

## Phase 1: Prove it on the recording PC

- [ ] Install the latest build from a USB drive (zip from the newest green run under
      GitHub Actions).
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
- [ ] Check the video names suit downstream tools. Elevated Plus videos are now
      `<date>_<time>_EPM_Overhead.mp4`.

## Phase 2: Settle the handoff with Track Tamer

The metadata standard (`metadata_standard.md`, owned by Track Tamer) is still a
draft, and Track Tamer plans to read these files only after its own 1.0.

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
- [ ] Take the standard out of draft.

## Phase 3: Release v0.2.0

Once phases 1 and 2 are settled:

- [x] Raise the version number to 0.2.0 (done 2026-11-10, so test builds are
      labelled correctly).
- [ ] Tag `v0.2.0` so the Windows zip is attached to a GitHub Release.
- [ ] Update the README install steps to cover the offline USB route.

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

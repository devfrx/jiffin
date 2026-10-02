# ADR-0015: Package with PyInstaller and Velopack, and download the model on first run

- **Status:** Accepted
- **Date:** 2026-09-30
- **Deciders:** devfrx
- **Sources:** tickets [#16](https://github.com/devfrx/jiffin/issues/16) (stack), [#27](https://github.com/devfrx/jiffin/issues/27) (two executables) and [#28](https://github.com/devfrx/jiffin/issues/28) (packId)

## Context

The first version installs on the owner's Windows 11 machine, per user and
without administrator rights, with a Start menu entry, start at login and
updates. The bundle holds two programs, the app and the engine
([ADR-0011](0011-engine-child-process-json-rpc.md)), plus the CUDA runtime; the
model file alone is 2.4 GiB.

Facts checked on 2026-09-30:

- Onefile builds of PyInstaller and Nuitka have known antivirus false
  positives.
- PyInstaller 6.22.3 builds several executables into one folder with a shared
  `COLLECT`.
- Velopack installs into `%LocalAppData%\{packId}` and advises keeping data
  elsewhere. Its updater, `Update.exe`, is started without
  `CREATE_BREAKAWAY_FROM_JOB`, so it dies with a process in a kill-on-close Job
  Object (verified in Velopack's source).
- Microsoft's Artifact Signing does not accept individuals outside the US and
  Canada; the alternatives are paid certificates.

## Decision

- **PyInstaller 6.22.3 in folder mode** (`--onedir`, never onefile), with two
  executables and one shared `COLLECT`:
  - `Jiffin.exe`, windowed;
  - `jiffin-engine.exe`, console, started with `CREATE_NO_WINDOW` and all three
    standard streams piped.

  Python modules are duplicated in the two archives, a few MB. The evaluation
  harness is excluded from the bundle by name
  ([ADR-0017](0017-evaluation-harness-subpackage.md)).
- **Velopack 1.2.161** (MIT): per-user install without administrator rights,
  Start menu, start at login, updates. The packId is **`devfrx.Jiffin`**, so
  the install folder never overlaps the data folder `%LOCALAPPDATA%\Jiffin`
  ([ADR-0013](0013-sqlite-storage.md)). Start at login is Velopack's shortcut
  in the Startup folder.
- **Updates come from the folder the releases are built into**, for personal
  use ([#45](https://github.com/devfrx/jiffin/issues/45)): `scripts/package.py`
  writes each release to the repository's `releases/`, ignored by git, and
  leaves that folder's path in the app. At its start, before anything opens,
  the installed app looks there and applies a newer release, then starts
  again. A GitHub source was ruled out: the repository is private, so the app
  would carry a token.
- **The CUDA 13.4 runtime ships in the installer**, about 575 MB compressed.
- **The model does not ship in the installer.** It is downloaded on first run
  from `rizzoaiacademy/rizzo-flow` at the pinned revision, with resume and
  sha256 verification ([ADR-0006](0006-judge-rizzo-flow-q4.md)). Offline, the
  user puts the file in place by hand, and the app runs the same check.
- **Only the engine goes in the Job Object**, never the app, or Velopack's
  updater would die with it.
- **No code signing** in the first version.

## Consequences

**Positive**

- No administrator rights; updates built in.
- A lower antivirus risk than onefile builds.
- The model comes from its pinned source and is verified, not repackaged.

**Negative (accepted)**

- A large installer, because of the CUDA runtime, and a 2.4 GiB download on
  first run.
- Unsigned binaries: SmartScreen warnings; the antivirus risk is lower, not
  gone.
- In a checkout, llama.cpp's DLLs use the system `msvcp140.dll`, and an old
  one has a known crash. The packaged engine loads the one PyInstaller ships
  beside its libraries instead, 14.51 in 0.1.0 (checked on the running
  process, [#45](https://github.com/devfrx/jiffin/issues/45)).

**Measured on 0.1.0** ([#45](https://github.com/devfrx/jiffin/issues/45)), on
the owner's machine:

- `devfrx.Jiffin-win-Setup.exe` is 652 MB; installed, the app takes 855 MB,
  and Velopack keeps its last full package, 645 MB, for updates.
- A clean install takes about 20 s; then the model downloads, 2.5 min on the
  owner's line, and the engine is ready about 10 s later.
- An update applied at the start through a 1 MB delta took 2 min 19 s until
  the engine was ready: 71 s to rebuild the full package from the delta, 47 s
  to apply it. Jiffin shows nothing meanwhile.
- No SmartScreen warning, since an installer built on the same machine carries
  no mark of the web; Microsoft Defender reported nothing.

**Out of scope for the first version** — distribution to others: code
signing, a Vulkan build for non-NVIDIA GPUs, a mirror of the model, and the
VC++ Redistributable in the installer.

**Follow-up**

- The first packaged build checks that the engine starts from the bundle and
  answers `initialize`: done in [#45](https://github.com/devfrx/jiffin/issues/45),
  and `tests/integration/test_client.py` checks it on the installed app.
- The update source is chosen with the packaging work: the releases' folder,
  above ([#45](https://github.com/devfrx/jiffin/issues/45)).

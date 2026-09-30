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
  ([ADR-0013](0013-sqlite-storage.md)).
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
- llama.cpp's DLLs use the system `msvcp140.dll`, and an old one has a known
  crash. The same llama.cpp build already runs on the owner's machine, where
  all the measurements were taken.

**Out of scope for the first version** — distribution to others: code
signing, a Vulkan build for non-NVIDIA GPUs, a mirror of the model, and the
VC++ Redistributable in the installer.

**Follow-up**

- The first packaged build checks that the engine starts from the bundle and
  answers `initialize`.
- The update source is chosen with the packaging work.

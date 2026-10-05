# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-05

Reminders that ring once per occasion, and that understand a time.

### Added

- A time in the condition, read by Jiffin's own grammar: "alle 15", "dopo le
  11", "il primo lunedì del mese", "una volta ogni due settimane". Under
  "Quando" the creation window says what it understood, or which words it did
  not; a reminder with only a time rings at its time in whatever window is in
  front.
- The "Ogni volta" box: a perennial reminder stays after Fatto and comes back
  at its next occasion or time.
- On the alert, Rimanda opens a menu: Alla prossima volta, Tra 15 minuti, Tra
  un'ora, Domani, and Non qui; the X closes the alert until the next occasion.
- A pause from the tray icon, for an hour or until tomorrow, with Riprendi.
- In the settings, the return pause: how long you must be away from a thing
  before its reminder may ring again there, 2 minutes by default.
- Every window has an X, and every window but the alerts can be dragged; the
  creation window and the settings open again where they were left.

### Changed

- A reminder rings once per occasion, and again when you come back to the
  thing after the return pause, instead of at most once an hour.
- A window in full screen, a locked screen and sleep count as being away:
  alerts wait, and ring when you are back. Alerts stay out of screen capture,
  so a shared screen does not show them.
- Utile is gone: Fatto, Rimanda, Non qui and the X answer an alert. The tray
  list shows each reminder's time, and keeps one card per reminder among "Non
  visti".
- The database migrates to its second version at the first start.
- The evaluation harness replays and reports this version: false alarms once
  per (context, reminder) pair, target 10 and cap 20, and the pairs kept quiet
  as already reminded counted apart from the missed reminders.

## [0.1.0] - 2026-10-02

The first installable version, for the owner's Windows 11 machine.

### Added

- Reminders with a condition in plain Italian, written in a creation window that
  Win+Shift+N opens over any app.
- The context: the app in front, its window title and, in a browser, the tab's
  address, read through UI Automation.
- A local judge, Rizzo Flow 4B on llama.cpp with CUDA, in a process of its own:
  it rewrites each condition as a statement and scores it against the context.
- Alerts in an overlay when a condition holds, about 5 s after the window comes
  to the front, with Fatto, Rimanda, and Utile or Non qui as feedback; a tray
  icon with the list of reminders and alerts; settings for the windows'
  material.
- The model downloaded and verified at the first start, shown in a first-run
  window; local storage in SQLite under `%LOCALAPPDATA%\Jiffin`.
- An evaluation harness that measures the app against its acceptance
  thresholds, kept out of the installer.
- An installer for the current user, with a Start menu entry, start at login and
  updates from the folder the releases are built into.

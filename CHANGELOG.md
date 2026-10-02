# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-02

The first installable version, for the owner's Windows 11 machine.

### Added

- Reminders with a condition in plain Italian, written in a creation window that
  Win+Shift+N opens over any app.
- The context: the app in front, its window title and, in a browser, the tab's
  address, read through UI Automation.
- A local judge, Rizzo Flow 4B on llama.cpp with CUDA, in a process of its own:
  it rewrites each condition as a statement and scores it against the context.
- Alerts in an overlay when a condition holds, with Fatto, Rimanda, and Utile
  or Non qui as feedback; a tray icon with the list of reminders and alerts;
  settings for the windows' material.
- The model downloaded and verified at the first start, shown in a first-run
  window; local storage in SQLite under `%LOCALAPPDATA%\Jiffin`.
- An evaluation harness that measures the app against its acceptance
  thresholds, kept out of the installer.
- An installer for the current user, with a Start menu entry, start at login and
  updates from the folder the releases are built into.

Status: needs-triage

## Parent

- PRD: `.scratch/apple-agent-v1/PRD.md`

## What to build

A single-file, standard-library-only Python CLI (`apple-agent.py`) with an argparse interface, `--json` structured output, and a `scan` subcommand. The CLI must detect the Apple project type (SPM, Xcode, or flat directory), report the environment and available tools, and return a stable JSON schema (`schema_version`, `environment`, `project`, `validation`). For Xcode projects, include a minimal `project.pbxproj` lexer that extracts target names and build settings, falling back to directory scanning with a non-fatal warning if parsing fails. Include minimal unit tests for project detection and the lexer fallback.

## Acceptance criteria

- [ ] `python apple-agent.py scan --root <path> --json` returns valid JSON with `schema_version: "1.0"`, `environment`, `project`, and `validation` blocks.
- [ ] SPM projects are detected by the presence of `Package.swift`.
- [ ] Xcode projects are detected by `*.xcodeproj`; the lexer extracts at least `PBXNativeTarget` names and `productType` without crashing on malformed files.
- [ ] Flat directories (no manifest) fall back to a generic scan of `.swift` files.
- [ ] Unit tests verify JSON shape and graceful fallback on a malformed `.pbxproj`.
- [ ] The CLI uses only Python standard library modules.

## Blocked by

None - can start immediately

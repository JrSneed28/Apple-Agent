Status: needs-triage

## Parent

- PRD: `.scratch/apple-agent-v1/PRD.md`

## What to build

Add deterministic Apple-platform analyzers to the CLI that parse real files with `plistlib`: Info.plist permission-string review, entitlement file presence and capability consistency, `PrivacyInfo.xcprivacy` existence and required-reason API checks, asset catalog sanity (app icon, accent color, dark-mode variants), and localization gap detection (hardcoded string hints). Every finding from these analyzers must use `confidence: "verified"`. Include focused unit tests for each analyzer against temporary project skeletons.

## Acceptance criteria

- [ ] `scan` / `audit` / `shipcheck` reports findings for missing `NSCameraUsageDescription`-style plist keys when matching imports (e.g., `AVFoundation`) are detected.
- [ ] Entitlement files are parsed and checked for suspicious or mismatched capabilities.
- [ ] Missing `PrivacyInfo.xcprivacy` is flagged as a finding when privacy-sensitive Apple frameworks are used.
- [ ] Asset catalog checks report missing app icon set or accent color.
- [ ] All findings from this slice carry `confidence: "verified"`.
- [ ] Unit tests cover each analyzer with representative temporary project trees.

## Blocked by

- `.scratch/apple-agent-v1/issues/01-cli-foundation-scan.md`

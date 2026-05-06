# Apple Project Agent

Claude Code skill. Runs deterministic static analysis of Apple platform projects (iOS, macOS, watchOS, tvOS, visionOS). Backed by a single-file, standard-library-only Python CLI (`apple-agent.py`). Read-only at the CLI layer.

## Quickstart

```
/apple scan              → project map + summary
/apple audit             → categorized findings with paths
/apple shipcheck         → launch-readiness with App Review risk
```

All commands default to `--json` output. The skill parses the CLI JSON and presents findings to the user.

## Command Routing

### `/apple scan`

Detects project type (Xcode, SPM, flat), prints a readable project map.

```
/apple scan
```

Calls: `python apple-agent.py scan --root . --json`

Presents:
- Project type and target list
- Swift file count, framework imports
- Platform analysis summary (permission strings, entitlements, privacy manifest, asset catalogs, localization)
- Severity summary (critical/high/medium/low/info)

### `/apple audit [--target <path>]`

Presents all findings categorized by severity (Critical → High → Medium → Low → Info), each with file path and message.

```
/apple audit
/apple audit --target Sources/App/Profile
```

Calls: `python apple-agent.py audit --root . --target <path> --json`

Presents:
- Findings grouped by severity, each with `file:line`, `message`, `confidence`
- Suggested actions prioritized by severity
- Performed/skipped/macOS-required checklist

### `/apple shipcheck`

Launch-readiness report combining all analyzers with App Review risk weighting.

```
/apple shipcheck
```

Calls: `python apple-agent.py shipcheck --root . --json`

Presents:
- **Risk Score** (0-100) with assessment (clean / low_risk / moderate_risk / high_risk)
- **Launch Blockers** — missing permission strings, broken entitlements
- **App Review Risks** — missing privacy manifest, force-try patterns, missing app icon, image accessibility
- **Privacy Risks** — privacy manifest gaps, undeclared permission usage
- **StoreKit Risks** — missing restore purchases, unhandled transaction states
- macOS-required checks that could not be performed

## Plain-English Modifier Parsing

The skill interprets user intent from natural language and maps it to structured parameters.

| User says | Interpretation | Effect |
|---|---|---|
| `focus on privacy` | scope=privacy | Filter findings to `permission_strings` + `privacy_manifest` categories |
| `focus on accessibility` | scope=accessibility | Filter to `image_accessibility` findings |
| `focus on storekit` | scope=storekit | Filter to `storekit_*` findings |
| `quick pass` / `just the big stuff` | risk=caps(critical,high) | Only show critical + high severity findings |
| `everything` / `full audit` | risk=all | Show all severity levels |
| `this folder only` / `just this directory` | target=<current> | Pass `--target <path>` to audit |
| `safe edits only` | action=low_risk_only | Filter suggested actions to low/cosmetic changes |
| `no project files` / `don't touch configs` | protected_files=true | Skip edits to Info.plist, entitlements, pbxproj |
| `scan <path>` | override_root | Use explicit path instead of cwd |
| `audit <path>` | override_root | Run audit at explicit path |

### Intent resolution flow

1. Extract the verb: `scan`, `audit`, `shipcheck` → maps to CLI subcommand
2. If verb not explicit, infer from context: "check if this is ready" → shipcheck, "find issues" → audit, "what's here" → scan
3. Extract path if named (e.g., `scan ~/Projects/MyApp` → `--root ~/Projects/MyApp`)
4. Apply modifier mappings to filter/focus output
5. Run CLI, parse JSON, present

Default root: current working directory (`.`).

## Reporting Contract

Every response MUST include these four sections:

### ✓ Verified Checks

Findings with `confidence: "verified"` — deterministic file/plist checks that are proven true on any OS.

Examples:
- Missing `NSCameraUsageDescription` when AVFoundation is imported
- Missing `PrivacyInfo.xcprivacy` when privacy-sensitive frameworks used
- Missing AppIcon in asset catalog
- Parsed entitlement capabilities

### ⚡ Inferred Checks

Findings with `confidence: "high_confidence_heuristic"` or `confidence: "heuristic"` — regex-based pattern matching that may produce false positives.

Examples:
- Force unwrap (`!`) operators
- Hardcoded colors/fonts/frames
- View body size metrics
- Image accessibility label gaps

### 🍎 macOS-Required Checks

Items in `validation.requires_macos` that need Xcode, Simulator, or device.

Examples:
- Build with `xcodebuild`
- Run on iOS Simulator
- Verify SwiftUI previews
- Validate code signing
- Test StoreKit transactions

### → Recommended Next Steps

Derived from `suggested_actions`, prioritized by severity. Format as:

```
[priority] Title — affected files
```

## Output Formatting

### Scan output format

```
## Project Map: MyApp
**Type:** Xcode project · **Targets:** MyApp, MyAppTests, Widget
**Swift files:** 42 · **Frameworks:** SwiftUI, Combine, StoreKit

### Configurations
- Info.plist: found ✓
- Entitlements: App.entitlements (push, app-groups)
- Privacy manifest: missing ✗ (PrivacyInfo.xcprivacy)
- Asset catalog: Assets.xcassets (no app icon ⚠)

### Summary
| Severity | Count |
|---|---|
| Critical | 0 |
| High     | 2 |
| Medium   | 5 |
| Low      | 3 |
| Info     | 12 |
```

### Audit output format

```
## Audit Results

### 🔴 Critical (0)
*(none)*

### 🟠 High (2)
- `Info.plist`: Missing NSCameraUsageDescription (Privacy - Camera Usage Description) but AVFoundation is imported **[verified]**
- *(missing)*: PrivacyInfo.xcprivacy is missing but privacy-sensitive frameworks are used: AVFoundation **[verified]**

### 🟡 Medium (5)
- `ContentView.swift:12`: Force unwrap (!) `data!.count` **[heuristic]**
- `ContentView.swift:25`: View body is 95 lines (consider extracting subviews) **[heuristic]**
...

### → Suggested Actions
1. **[high]** Add NSCameraUsageDescription to Info.plist — `Info.plist`
2. **[high]** Create PrivacyInfo.xcprivacy manifest — `PrivacyInfo.xcprivacy`
3. **[medium]** Replace force unwrap with safe unwrap — `ContentView.swift`
...
```

### Shipcheck output format

```
## Shipcheck Report

**Risk Score:** 35/100 — Moderate Risk

### 🚫 Launch Blockers (0)
*(none)*

### ⚠ App Review Risks (3)
- *(missing)*: PrivacyInfo.xcprivacy is missing but privacy-sensitive frameworks used **[verified]**
- `App.entitlements`: Entitlement 'aps-environment' present **[verified]**
- `ProfileView.swift:45`: Force try (try!) `try! JSONDecoder().decode(...)` **[heuristic]**

### 🔒 Privacy Risks (2)
- `Info.plist`: Missing NSCameraUsageDescription but AVFoundation is imported **[verified]**

### 🛒 StoreKit Risks (2)
- `Store.swift:1`: StoreKit import detected **[heuristic]**
- `Store.swift:15`: Restore purchases API usage **[heuristic]**

### → Next Steps
1. **[high]** Create PrivacyInfo.xcprivacy — critical for App Store submission
2. **[high]** Add NSCameraUsageDescription to Info.plist
...
```

## Confidence Tier Reference

| Confidence | Source | Verifiable on Windows |
|---|---|---|
| `verified` | plistlib parse, file existence, deterministic checks | ✓ Yes |
| `high_confidence_heuristic` | import statements, base-class detection, property wrappers | ⚡ High likelihood |
| `heuristic` | regex patterns (colors, fonts, force unwraps) | ⚡ May false-positive |

## Protected File Policy (v1)

The skill must prompt separately before editing any of these files:

- `Info.plist`, `*.entitlements` — signing/privacy breakage risk
- `project.pbxproj` — can break the Xcode project
- `Package.swift` — can break SPM resolution
- `*.xcconfig` — build configuration
- StoreKit configuration files
- Generated files (`.generated.swift`, etc.)

For v1, the skill reports findings on these files but does NOT auto-edit them without an explicit approval round.

## CLI Reference

CLI path: `python apple-agent.py` (relative to project root)

### Subcommands

```
scan      --root <path> [--json]       Project discovery + platform analysis
audit     --root <path> [--target <dir>] [--json]  Scoped findings report
shipcheck --root <path> [--json]       Launch-readiness with App Review risk
validate  --root <path> [--json]       Post-edit re-validation
```

### JSON Contract (v1 schema_version: "1.0")

```json
{
  "schema_version": "1.0",
  "command": "scan|audit|shipcheck|validate",
  "environment": { "os": "...", "is_macos": true/false, ... },
  "project": {
    "root": "...",
    "type": "xcode|spm|flat|xcode_workspace",
    "targets": [...],
    "platform_analysis": {
      "findings": [...],
      "analyzer_summaries": {...}
    },
    "swift_heuristics": {
      "files_scanned": N,
      "heuristics": [...],
      "summary": {...}
    }
  },
  "findings": [
    {
      "finding_id": "string",
      "category": "string",
      "severity": "critical|high|medium|low|info",
      "confidence": "verified|high_confidence_heuristic|heuristic",
      "file": "relative/path",
      "line": N,
      "message": "human-readable description"
    }
  ],
  "suggested_actions": [
    {
      "id": "action_key",
      "title": "action description",
      "category": "privacy|release|accessibility|architecture",
      "priority": "critical|high|medium|low",
      "files": ["file1", "file2"]
    }
  ],
  "summary": {
    "critical": N, "high": N, "medium": N, "low": N, "info": N
  },
  "validation": {
    "performed": ["check1", ...],
    "skipped": ["check2", ...],
    "requires_macos": ["mac-only check", ...],
    "errors": [],
    "warnings": [],
    "valid": true
  },
  "shipcheck": {
    "risk_score": 0-100,
    "assessment": "clean|low_risk|moderate_risk|high_risk",
    "assessment_message": "...",
    "launch_blockers": { "findings": [...], "count": N },
    "app_review_risks": { "findings": [...], "count": N },
    "privacy_risks": { "findings": [...], "count": N },
    "storekit_risks": { "findings": [...], "count": N }
  }
}
```

Notes:
- `shipcheck` section only present for `shipcheck` command
- `audit_scope` section only present when `--target` is used with `audit`
- Findings carry `confidence` reflecting their determinism tier
- Severity uses unified scale: `critical > high > medium > low > info`

## Error Handling

If the CLI fails to run (Python not found, malformed project):
1. Report the error clearly
2. Suggest fixes (install Python 3.10+, check project path)
3. Do NOT attempt to guess or fabricate findings

If the CLI produces a warning (e.g., pbxproj parse failure):
1. Present findings from the fallback directory scan
2. Note the warning but do not treat it as fatal
3. Continue with available data

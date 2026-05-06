# Apple Project Agent for Claude Code

A Claude Code skill that performs deterministic static analysis of Apple platform projects (iOS, macOS, watchOS, tvOS, visionOS). Backed by a single-file, standard-library-only Python CLI.

**Windows-first.** Runs anywhere Python 3.10+ runs. Clearly labels what was verified locally vs. what requires macOS/Xcode.

## Installation

Copy two files into your Claude Code skills directory:

```
mkdir -p ~/.claude/skills/apple/
cp apple-agent.py ~/.claude/skills/apple/
cp SKILL.md ~/.claude/skills/apple/
```

### One-liner (PowerShell)

```powershell
$d = "$env:USERPROFILE\.claude\skills\apple"; mkdir $d -Force; Invoke-WebRequest -Uri "https://github.com/<user>/apple-agent/releases/latest/download/apple-agent.py" -OutFile "$d\apple-agent.py"; Invoke-WebRequest -Uri "https://github.com/<user>/apple-agent/releases/latest/download/SKILL.md" -OutFile "$d\SKILL.md"
```

### One-liner (curl/bash)

```bash
mkdir -p ~/.claude/skills/apple/ && curl -L -o ~/.claude/skills/apple/apple-agent.py https://github.com/<user>/apple-agent/releases/latest/download/apple-agent.py && curl -L -o ~/.claude/skills/apple/SKILL.md https://github.com/<user>/apple-agent/releases/latest/download/SKILL.md
```

**Requirements:** Python 3.10+. No pip packages, no virtual environment, no Swift toolchain.

## Commands

| Command | What it does |
|---|---|
| `/apple scan` | Project map — type, targets, frameworks, config status |
| `/apple audit [--target <path>]` | Categorized findings by severity, with suggested actions |
| `/apple fix [--target <path>]` | Edit plan from audit → approve → apply → validate (HITL) |
| `/apple polish [--target <path>]` | SwiftUI quality: accessibility, semantic colors, Dynamic Type, localization |
| `/apple shipcheck` | Launch-readiness report with App Review risk scoring |

### Examples

```
/apple scan
/apple audit
/apple audit --target Sources/App/Profile
/apple fix --target Sources/App/Checkout
/apple polish
/apple shipcheck
```

### Plain-English modifiers

All commands accept natural language modifiers:

| Say | Effect |
|---|---|
| `focus on privacy` | Filter to permission strings and privacy manifest findings |
| `focus on accessibility` | Filter to accessibility-related findings |
| `quick pass` | Critical + high severity only |
| `everything` / `full audit` | All severity levels |
| `this folder only` | Scope to current directory |
| `safe edits only` | Low-risk suggested actions only |

### Edit workflow (`fix` and `polish`)

Edit commands follow a strict approval-gated pipeline:

1. **CLI audit** — get `suggested_actions`
2. **Edit plan** — exact files, finding IDs, risk levels, behavior-preservation summaries
3. **User approval** — required before ANY edit
4. **Edit only approved files** — via Claude Code's `Edit` tool
5. **CLI validate** — re-scan changed files
6. **Final report** — diff summary, validated checks, remaining risks, macOS-required items

Protected files (`Info.plist`, `*.entitlements`, `project.pbxproj`, `Package.swift`, `*.xcconfig`, signing configs, StoreKit configs, auth/payment/security files, generated files) are **report-only** and require a separate explicit approval round.

## Confidence Tiers

Every finding carries a confidence label. This is the core trust model of the agent.

| Confidence | Source | Verifiable on Windows |
|---|---|---|
| `verified` | `plistlib` parse, file existence, deterministic checks | Yes |
| `high_confidence_heuristic` | Import statements, base-class detection, property wrappers | High likelihood |
| `heuristic` | Regex patterns (colors, fonts, force unwraps) | May false-positive |

**Why this matters:** The CLI runs on Windows and cannot build or run your project. `verified` findings are proven true by parsing files that exist on disk. `heuristic` findings are pattern matches that are likely correct but may include false positives. The skill always separates these in reports so you know what to trust and what to verify on a Mac.

## CLI Standalone Usage

The CLI runs independently of Claude Code for CI/CD or headless automation.

```bash
python apple-agent.py scan --root /path/to/project --json
python apple-agent.py audit --root /path/to/project --target Sources/ --json
python apple-agent.py shipcheck --root /path/to/project --json
python apple-agent.py validate --root /path/to/project --json
```

All subcommands return JSON to stdout conforming to schema version `"1.0"`.

### JSON Output Schema

```json
{
  "schema_version": "1.0",
  "command": "scan|audit|shipcheck|validate",
  "environment": { "os": "...", "is_macos": true|false },
  "project": {
    "root": "/path/to/project",
    "type": "xcode|spm|flat|xcode_workspace",
    "targets": ["TargetA", "TargetB"],
    "platform_analysis": {
      "findings": [...],
      "analyzer_summaries": {...}
    },
    "swift_heuristics": {
      "files_scanned": 42,
      "heuristics": [...],
      "summary": {...}
    }
  },
  "findings": [
    {
      "finding_id": "missing-camera-desc-001",
      "category": "permission_strings",
      "severity": "critical|high|medium|low|info",
      "confidence": "verified|high_confidence_heuristic|heuristic",
      "file": "Sources/App/CameraView.swift",
      "line": 12,
      "message": "Missing NSCameraUsageDescription in Info.plist but AVFoundation is imported"
    }
  ],
  "suggested_actions": [
    {
      "id": "add-camera-desc",
      "title": "Add NSCameraUsageDescription to Info.plist",
      "category": "privacy",
      "priority": "high",
      "files": ["Info.plist"]
    }
  ],
  "summary": {
    "critical": 0, "high": 2, "medium": 5, "low": 3, "info": 12
  },
  "validation": {
    "performed": ["plist_parse", "entitlement_parse", "swift_scan"],
    "skipped": ["xcodebuild", "simulator_test"],
    "requires_macos": ["Build verification", "SwiftUI preview validation"],
    "errors": [],
    "warnings": [],
    "valid": true
  }
}
```

**Command-specific sections:**

| Command | Extra keys |
|---|---|
| `scan` | — (base schema) |
| `audit` | `audit_scope` (when `--target` used) |
| `shipcheck` | `shipcheck` block with risk_score, assessment, launch_blockers, app_review_risks, privacy_risks, storekit_risks |
| `validate` | — (shape matches scan, labeled as validate) |

## What the CLI Checks

### Verified (deterministic)
- Permission strings in `Info.plist` (camera, microphone, location, photos, etc.)
- Entitlement capabilities (push notifications, HealthKit, app groups, etc.)
- Privacy manifest (`PrivacyInfo.xcprivacy`) presence and contents
- Asset catalog structure (app icon, accent color)
- Localization resource presence
- Project type and target names

### Heuristic (pattern-based)
- Framework imports (SwiftUI, UIKit, AppKit, Combine, StoreKit, SwiftData)
- Architecture signals: base classes, property wrappers, type name suffixes
- Code quality: force unwraps, force try, fatalError, TODO/FIXME
- UI patterns: hardcoded colors, fonts, fixed frame sizes
- Accessibility: images without labels, Dynamic Type risks
- View structure: large view bodies, deep stack nesting
- StoreKit: product definitions, purchase/restore calls, transaction handling

## Windows Limitations

**This tool does not run Xcode, Simulator, or macOS-specific tooling.** The following checks are reported as `requires_macos` and can only be verified on a Mac:

- Build verification with `xcodebuild`
- iOS/watchOS/tvOS/visionOS Simulator testing
- SwiftUI preview validation
- Code signing validation
- StoreKit transaction testing
- Device-level entitlement verification

The agent honestly reports what it cannot verify. It never fabricates results for macOS-only checks.

## Development

### Running tests

```bash
# Unit tests (~150 tests)
python -m unittest test_apple_agent.py -v

# Integration tests (23 tests, subprocess-based)
python -m unittest test_integration.py -v

# All tests
python -m unittest discover -v
```

### Project structure

```
apple-agent/
  apple-agent.py       # CLI — all analysis logic (2269 lines)
  test_apple_agent.py  # Unit tests (~150 tests)
  test_integration.py  # Integration tests (23 tests)
  SKILL.md             # Claude Code skill definition
  README.md            # This file
  PRD.md               # v1 Product Requirements Document
  docs/agents/         # Agent workflow documentation
  .scratch/issues/     # Issue tracker
```

**Dependencies:** Python 3.10+ standard library only. No pip installs.

## License

MIT

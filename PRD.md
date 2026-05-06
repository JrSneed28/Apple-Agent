# Apple Project Agent for Claude Code — v1 PRD

**Status:** needs-triage

## Problem Statement

Apple developers need a reliable way to audit, fix, polish, and prepare their iOS / macOS / watchOS / tvOS / visionOS projects for release — but many of them run Claude Code on Windows, where Xcode, the iOS Simulator, SwiftUI Previews, and `xcodebuild` are unavailable. Existing tools either require macOS/Xcode or focus narrowly on UI polish, missing architecture, privacy, entitlement, StoreKit, and App Review risks. There is no Windows-first Apple project analysis agent that can scan, audit, and suggest safe fixes while honestly reporting what cannot be verified outside macOS.

## Solution

Build a **Claude Code skill** (`/apple`) backed by a **single-file, standard-library-only Python CLI** (`apple-agent.py`). The CLI performs deterministic static analysis of Apple projects and returns structured JSON. The skill handles intent parsing, user approval, file editing, and reporting. For v1, the product is strictly read-only at the CLI layer; all edits flow through Claude Code's native approval and `Edit` tool workflow.

## User Stories

1. As an iOS developer on Windows, I want to run `/apple scan` on my project folder, so that I can understand the project structure, targets, frameworks, and configuration without needing Xcode.
2. As a SwiftUI developer, I want to run `/apple audit`, so that I can receive a categorized list of architecture, UI, privacy, and release risks without any files being changed.
3. As a team lead preparing for App Store submission, I want to run `/apple shipcheck`, so that I can discover launch blockers related to privacy manifests, entitlements, StoreKit, and App Review guidelines.
4. As a developer reviewing a proposed fix, I want to see an edit plan with exact files and summaries before any code is modified, so that I can approve or reject the plan explicitly.
5. As a cautious developer, I want the agent to never auto-edit protected files (e.g., `Info.plist`, entitlements, `project.pbxproj`) without a separate approval round, so that I do not accidentally break signing or privacy configuration.
6. As a Windows-first user, I want the agent to clearly label every finding with a confidence tier (`verified`, `high_confidence`, `inferred`, `requires_macos`), so that I know what was proven vs. what needs Xcode validation.
7. As a CI/CD maintainer, I want the CLI to run headlessly with `--json` output, so that I can integrate Apple project health checks into GitHub Actions or other automation.
8. As a developer fixing a SwiftUI screen, I want to run `/apple polish ProfileView`, so that the agent can suggest accessibility, layout, and component-extraction improvements while preserving existing behavior.
9. As a developer using the agent, I want zero external dependencies beyond Python itself, so that I do not need to install pip packages, virtual environments, or a Swift toolchain to get started.
10. As an advanced user, I want optional plain-English controls (e.g., `safe edits only`, `focus on privacy`, `don't touch project files`), so that I can constrain the agent's behavior without memorizing flags.
11. As a developer whose Xcode project is modified by CocoaPods or SPM, I want the agent to gracefully handle `project.pbxproj` parsing failures and fall back to directory scanning, so that the scan never crashes.
12. As a developer using `/apple fix`, I want a post-edit validation run that re-scans changed files and shows a diff summary, so that I can confirm the fix did not introduce regressions.
13. As a macOS user, I want the same agent to work identically on macOS and Windows, so that my team has a consistent experience regardless of OS.
14. As a privacy-conscious developer, I want the agent to flag missing `PrivacyInfo.xcprivacy` files and required-reason API declarations, so that I can avoid App Store rejection for privacy non-compliance.
15. As a developer with a mixed UIKit/SwiftUI project, I want the agent to detect both UI frameworks and report risks relevant to each, so that legacy UIKit code does not get ignored.
16. As a developer with app extensions or widgets, I want the agent to detect extensions and their entitlements, so that I can validate widget/extension configuration alongside the main app.
17. As a developer concerned about accessibility, I want the agent to flag icon-only buttons without accessibility labels and Dynamic Type clipping risks, so that I can improve VoiceOver and accessibility support.
18. As a developer with StoreKit in-app purchases, I want the agent to detect product ID scattering, missing restore-purchase affordances, and missing error/loading states, so that I can fix subscription flows before App Review.
19. As a developer whose project lacks tests, I want the agent to report testing gaps and suggest Windows-safe test strategies, so that I know what validation requires macOS/Xcode.
20. As a user installing the agent, I want a two-file installation (skill + CLI) into the Claude Code skills directory, so that setup is trivial and transparent.

## Implementation Decisions

### Module: `apple-agent.py` (the Python CLI)

- **Language:** Python 3.10+, standard library only (`argparse`, `json`, `os`, `sys`, `pathlib`, `re`, `plistlib`, `xml.etree.ElementTree`, `hashlib`, `subprocess`, `platform`).
- **Distribution:** Single self-contained `.py` file. No `pip`, `setup.py`, `pyproject.toml`, or virtual environment required.
- **Interface:** Four read-only subcommands: `scan`, `audit`, `shipcheck`, `validate`.
- **Output:** Structured JSON (`--json` flag) conforming to the v1 CLI contract.
- **Scope:**
  - **Project type detection:** SPM (`Package.swift`), Xcode (`*.xcodeproj`), or flat directory. Graceful fallback if parsing fails.
  - **`project.pbxproj` parsing:** Minimal lexer that tokenizes the file and extracts `PBXNativeTarget` names, `productType`, `buildSettings`, and high-value build-phase hints. Falls back to directory scanning on parse failure with a warning.
  - **Plist/entitlement/privacy analysis:** Deterministic parsing via `plistlib`. Labels findings as `verified`.
  - **Swift source analysis:** Regex/heuristic only. Detects imports, common patterns (force unwraps, hardcoded colors, missing accessibility labels, large view bodies, nested stacks, `@StateObject` usage), and conservative architecture signals (type name suffixes). Labels findings as `heuristic`.
  - **Asset/localization checks:** File existence and naming convention scans.
  - **StoreKit detection:** Import and API call pattern scanning.
- **Safety:** CLI is strictly read-only. No file modification, no patch generation.

### Module: `SKILL.md` (the Claude Code skill)

- **Invocation:** Single `/apple` command family with five verbs: `scan`, `audit`, `fix`, `polish`, `shipcheck`.
- **Intent parsing:** Maps plain-English modifiers to structured scope, action, focus, and risk parameters.
- **Orchestration flow for all commands:**
  1. Run CLI → receive JSON report.
  2. Present findings to user (or edit plan for `fix`/`polish`).
  3. For `fix`/`polish`: ask for explicit approval on exact files and changes.
  4. Edit only approved files via Claude Code's native `Edit` tool.
  5. Run CLI `validate` on post-edit state.
  6. Present final report with diff summary, validated checks, inferred risks, and macOS-required checklist.
- **Protected-file policy:**
  - `Info.plist`, `*.entitlements`, `project.pbxproj`, `Package.swift`, `*.xcconfig`, signing configs, StoreKit configs, auth/payment/security files, generated files: report-only in v1 unless user initiates a separate, explicit approval round.
- **Reporting contract:** Every response must include:
  - what changed (if anything)
  - what was verified locally
  - what was inferred
  - what requires macOS/Xcode
  - what risky areas were avoided
  - what remains to do

### Architecture Boundary

- **CLI detects and validates; Claude Code decides, edits, and explains.**
- The CLI never modifies files. The skill never edits files the CLI did not return in the resolved scope. The approval chain is preserved end-to-end.

### Out of Scope for v1 (CLI)

- `fix` and `polish` subcommands in the CLI (editing is skill-side only).
- AST-based Swift analysis (no SwiftSyntax).
- Cross-file type resolution.
- Xcode workspace graph analysis.
- Build/test execution (`xcodebuild`, Simulator, Previews).
- Automatic installation/bootstrap scripts (README describes manual copy and optional one-liner download).

## Testing Decisions

### What makes a good test

- Tests should verify **external behavior** (JSON output given a specific input project tree), not internal implementation details (regex patterns, lexer token lists).
- Each test should set up a temporary project directory, run the CLI with a specific subcommand, and assert on the JSON report structure and key finding fields (`id`, `severity`, `category`, `confidence`, `files`).

### Modules to test

- `apple-agent.py` CLI end-to-end tests for each subcommand (`scan`, `audit`, `shipcheck`, `validate`) against representative Apple project skeletons.
- `project.pbxproj` parser tests against a minimal `.pbxproj` file to ensure target extraction works and graceful fallback triggers on malformed input.
- Plist/entitlement/privacy manifest parser tests (deterministic).
- Swift heuristic scanner tests on sample `.swift` files covering SwiftUI, UIKit, and mixed patterns.
- Integration tests for the full skill-to-CLI roundtrip (mocked or via subprocess calls) to verify the JSON contract.

### Prior art

- This repo currently has no prior test suite for Apple project tooling. Testing strategy should follow standard Python `unittest` (standard library) since no external test runner is permitted for v1.

## Out of Scope

- Subagents (apple-architect, swiftui-experience-reviewer, etc.) — removed from v1.
- Hooks (SessionStart, PreToolUse, PostToolUse, etc.) — removed from v1; guardrails live in skill + CLI.
- Plugin manifest / `.claude-plugin/` packaging — v1 uses a skill directory, not a plugin.
- Marketplace distribution — v1 is GitHub/manual install only.
- MCP server for remote Mac validation.
- LSP / SourceKit-LSP integration.
- SwiftSyntax-based analyzer.
- Automatic post-edit hook scripts.
- CI-specific wrappers or GitHub Actions templates.
- Windows PowerShell-specific distribution scripts (README may suggest one-liner, but no required install script).

## Further Notes

- The v1 goal is **trust over speed**. The agent should be boring, useful, and honest. It should never claim a Mac-only check passed.
- Confidence labeling is critical: `verified` for deterministic file checks, `high_confidence_heuristic` / `heuristic` for regex-based Swift analysis, `requires_macos` for anything needing Xcode/Simulator.
- The JSON contract must be versioned (`schema_version`) so that v2 enhancements do not break v1 skill parsing.
- The CLI should be runnable standalone (`python apple-agent.py scan --root . --json`) for CI and headless environments, independent of Claude Code.
- Future phases (v2+) may add: optional auto-fix for very low-risk items, SwiftSyntax deep analyzer, subagent panel, hooks, plugin packaging, and remote Mac validator MCP.

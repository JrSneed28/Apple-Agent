# Apple Project Agent for Claude Code

**Status:** Planning/specification only — do not build yet.  
**Prepared for:** Claude Code-native Apple/iOS project agent design  
**Date:** 2026-05-05  

---

## 0. Product Definition

Build a **Claude Code-native Apple Project Agent** that helps users audit, repair, polish, and prepare iOS / Apple-platform projects.

This agent should handle more than UI:

```text
SwiftUI
UIKit when present
project architecture
navigation
state/data flow
async/concurrency
SwiftData/Core Data
StoreKit
CloudKit
push notifications
widgets
Live Activities
App Intents
permissions
privacy manifests
Info.plist
entitlements
assets
localization
testing
release/App Store readiness
```

The core product decision:

> This is not a separate app. It is a Claude Code plugin with a small, understandable `/apple` command family, backed by skills, subagents, hooks, static analyzers, optional MCP/LSP tools, and Windows-aware validation.

Claude Code is the host. The Apple Project Agent is the specialist layer.

---

## 1. Core Constraints

### 1.1 Claude Code-Native

The agent must use Claude Code’s current extension primitives instead of inventing a parallel framework.

```text
Plugin      = distribution/package
Skills      = command workflows
Subagents   = specialist reviewers/workers
Hooks       = deterministic guardrails/automation
MCP         = optional external tools
LSP         = optional language intelligence
Monitors    = optional long-running watchers
Settings    = team/project configuration
Permissions = safety model
```

Important design point:

> The `/apple` workflow should be implemented as a skill-backed command family, because Claude Code Skills support slash invocation and autonomous invocation.

### 1.2 Windows-First, Mac-Aware

Many users will run Claude Code in Windows environments.

The agent must separate what can be verified locally on Windows from what requires macOS/Xcode.

```text
Validated on Windows:
- static scan
- semantic/code review
- project structure audit
- plist/entitlement/privacy manifest inspection
- Swift syntax/heuristic checks where possible
- generated tests/previews
- final diff review

Requires macOS/Xcode:
- xcodebuild
- iOS Simulator
- SwiftUI previews
- real device testing
- XCUITest execution
- StoreKit sandbox validation
- snapshot/visual regression validation
- upload/archive/export validation
```

Hard rule:

> The agent must never claim `xcodebuild`, Simulator, SwiftUI previews, visual inspection, UI tests, or App Store archive validation passed unless those checks actually ran in a macOS/Xcode-capable environment.

---

## 2. User-Facing Command Design

Use one command family:

```text
/apple <verb> [target] [plain-English controls]
```

Only five verbs:

```text
/apple scan
/apple audit
/apple fix
/apple polish
/apple shipcheck
```

No command jungle. No cryptic flags required.

---

## 3. Command Specifications

### 3.1 `/apple scan`

Purpose: map and understand the project.

Examples:

```text
/apple scan
/apple scan Sources/App
```

Does:

```text
- Detect project type: SwiftUI, UIKit, mixed, package, app extension, widget, etc.
- Identify targets, packages, modules, app extensions, assets, plists, entitlements.
- Detect architecture style: MVVM, TCA, Clean Architecture, feature modules, ad hoc.
- Detect Apple frameworks in use.
- Detect test/previews coverage.
- Detect Windows/Mac validation boundaries.
```

Expected output:

```text
Project Map
- SwiftUI iOS app
- Uses StoreKit, Push Notifications, Firebase, WidgetKit
- Feature-based folder structure
- Windows detected: static validation only
- macOS/Xcode required for build, previews, simulator, UI tests
```

---

### 3.2 `/apple audit`

Purpose: review only.

Examples:

```text
/apple audit
/apple audit ProfileView
/apple audit the onboarding flow, focus architecture and privacy
```

Does:

```text
- Project architecture review
- SwiftUI/UIKit quality review
- state/data flow review
- Apple platform configuration review
- test/previews review
- release/App Store risk review
```

Default behavior:

```text
No edits unless explicitly requested.
```

---

### 3.3 `/apple fix`

Purpose: make safe corrections.

Examples:

```text
/apple fix ProfileView
/apple fix Settings, safe edits only
/apple fix architecture issues, but ask before touching project files
```

Does:

```text
- Runs targeted audit first
- Builds patch plan
- Fixes safe issues
- Avoids protected/risky files unless approved
- Runs Windows-safe validation
- Runs final self-review
- Produces macOS/Xcode checklist
```

---

### 3.4 `/apple polish`

Purpose: improve experience and Apple feel.

Examples:

```text
/apple polish DashboardView
/apple polish onboarding, preserve behavior
/apple polish paywall, focus accessibility and modern SwiftUI
```

Does:

```text
- SwiftUI/UI composition cleanup
- visual hierarchy cleanup
- accessibility improvements
- Dynamic Type risk checks
- reusable component extraction
- previews/states improvements
- design-system consistency
```

Important behavior:

> `/apple polish` can escalate internally into architecture review if the UI problem is caused by bad state, navigation, data flow, or component boundaries.

---

### 3.5 `/apple shipcheck`

Purpose: launch readiness.

Examples:

```text
/apple shipcheck
/apple shipcheck, focus StoreKit, privacy, permissions, and App Review risk
```

Does:

```text
- App Review risk scan
- Info.plist permission string review
- entitlement/capability consistency review
- privacy manifest review
- required reason API review
- third-party SDK/privacy declaration risk review
- StoreKit/paywall/subscription risk review
- localization/assets/app icon sanity review
- testing/release checklist
```

---

## 4. Plain-English Controls

Avoid complex flags.

Support natural modifiers:

```text
safe edits only
read-only
go deep
quick pass
focus on architecture
focus on SwiftUI
focus on privacy
focus on StoreKit
don’t touch auth
don’t touch project files
ask before changing entitlements
preserve behavior
whole project
this folder only
this file only
```

Internally map those to:

```text
Scope:
- file
- feature
- flow
- target
- whole project

Action:
- scan only
- audit only
- suggest patch
- safe patch
- broad patch with approval

Focus:
- architecture
- SwiftUI/UI
- Apple platform
- privacy
- release
- testing
- performance
- accessibility

Risk:
- read-only
- safe edits
- ask before risky edits
- protected-file changes denied
```

---

## 5. Internal Workflow Engine

Every command should use the same progressive pipeline.

```text
1. Intent Parse
2. Project Scan
3. Scope Detection
4. Specialist Pass Selection
5. Risk Classification
6. Patch Plan, if editing
7. Controlled Edits
8. Windows-Safe Validation
9. Final Diff Review
10. Report + macOS/Xcode Checklist
```

### 5.1 Workflow Chaining Rules

Commands are entry points, not isolated workflows.

Example:

```text
/apple polish Settings
```

May run:

```text
SwiftUI experience pass
↓
Accessibility pass
↓
Architecture pass if duplicate state/layout problems are found
↓
Safe fix pass
↓
Final code review
```

Example:

```text
/apple shipcheck
```

May run:

```text
Project scan
↓
Apple platform pass
↓
Privacy manifest pass
↓
StoreKit pass if StoreKit is detected
↓
App Review risk pass
↓
Testing gap pass
↓
Final release report
```

This gives the user control without forcing them to micromanage the internal workflow.

---

## 6. Claude Code Plugin Structure

Proposed package layout:

```text
apple-project-agent/
├─ .claude-plugin/
│  └─ plugin.json
│
├─ skills/
│  └─ apple/
│     ├─ SKILL.md
│     ├─ command-router.md
│     ├─ scan-workflow.md
│     ├─ audit-workflow.md
│     ├─ fix-workflow.md
│     ├─ polish-workflow.md
│     ├─ shipcheck-workflow.md
│     └─ reporting-contract.md
│
├─ agents/
│  ├─ apple-architect.md
│  ├─ swiftui-experience-reviewer.md
│  ├─ apple-platform-auditor.md
│  ├─ privacy-release-guardian.md
│  ├─ test-strategy-reviewer.md
│  └─ final-diff-reviewer.md
│
├─ hooks/
│  ├─ hooks.json
│  └─ scripts/
│     ├─ protected-file-guard.ps1
│     ├─ post-edit-static-check.ps1
│     ├─ apple-project-scan.ps1
│     └─ final-report-validator.ps1
│
├─ tools/
│  ├─ apple_project_scanner/
│  ├─ swift_file_mapper/
│  ├─ swiftui_view_tree_analyzer/
│  ├─ plist_checker/
│  ├─ entitlement_checker/
│  ├─ privacy_manifest_checker/
│  ├─ asset_catalog_checker/
│  ├─ localization_checker/
│  └─ storekit_checker/
│
├─ lsp/
│  └─ sourcekit-lsp-config-notes.md
│
├─ mcp/
│  └─ optional-mac-validator-design.md
│
├─ rules/
│  ├─ architecture-rules.md
│  ├─ swiftui-rules.md
│  ├─ apple-platform-rules.md
│  ├─ privacy-rules.md
│  ├─ app-review-rules.md
│  ├─ accessibility-rules.md
│  ├─ testing-rules.md
│  └─ windows-limitations.md
│
└─ templates/
   ├─ project-report.md
   ├─ audit-report.md
   ├─ fix-report.md
   ├─ shipcheck-report.md
   └─ mac-validation-checklist.md
```

---

## 7. Skill Design

Implement only one visible skill:

```text
/apple
```

Internally, `skills/apple/SKILL.md` handles:

```text
- command parsing
- verb routing
- target interpretation
- risk mode interpretation
- specialist selection
- report format
- Windows/Mac limitation language
```

### 7.1 Skill Invocation Contract

The `/apple` skill should always start by detecting:

```text
1. User intent
2. Target/scope
3. Risk level
4. Whether edits are allowed
5. Environment validation status
6. Relevant workflow path
```

Example:

```text
Apple Agent detected:
- Command: fix
- Scope: Sources/App/Settings
- Mode: safe edits only
- Protected areas: auth, project files, entitlements
- Environment: Windows, static validation only
```

---

## 8. Subagent Design

Use specialist subagents as an expert panel.

### 8.1 `apple-architect`

Role:

```text
Reviews app architecture, module boundaries, state ownership, dependency injection, navigation, service layers, async code, data flow, testability.
```

Tools:

```text
Read, Grep, Glob
No Edit/Write by default
```

Focus:

```text
- MVVM/TCA/Clean Architecture consistency
- ViewModel responsibilities
- service injection
- singleton abuse
- navigation ownership
- feature boundaries
- async/await misuse
- actor/MainActor issues
- model/view coupling
```

---

### 8.2 `swiftui-experience-reviewer`

Role:

```text
Reviews SwiftUI/UIKit experience quality and modern Apple feel.
```

Focus:

```text
- view decomposition
- layout hierarchy
- navigation clarity
- reusable components
- visual hierarchy
- spacing consistency
- dark mode
- Dynamic Type risk
- accessibility labels
- empty/loading/error states
- preview coverage
```

---

### 8.3 `apple-platform-auditor`

Role:

```text
Reviews Apple-specific project configuration.
```

Focus:

```text
- Info.plist
- entitlements
- capabilities
- app groups
- associated domains
- push notification setup
- background modes
- URL schemes
- widgets/extensions
- App Intents
- CloudKit/iCloud
- Keychain usage
- file protection
```

---

### 8.4 `privacy-release-guardian`

Role:

```text
Reviews privacy, App Review, data collection, third-party SDK, StoreKit, and launch-readiness risks.
```

Focus:

```text
- privacy manifests
- required reason APIs
- third-party SDK declarations
- App Store privacy labels
- tracking/ATT risk
- personal data sharing
- AI/third-party data disclosure
- StoreKit/subscription flows
- permission prompts
- App Review guideline risks
```

---

### 8.5 `test-strategy-reviewer`

Role:

```text
Reviews test coverage and proposes Windows-safe and Mac-required validation.
```

Focus:

```text
- unit tests
- Swift Testing
- XCTest
- UI tests
- preview states
- snapshot tests
- StoreKit tests
- accessibility audits
- release validation checklist
```

---

### 8.6 `final-diff-reviewer`

Role:

```text
Read-only final reviewer before the agent reports completion.
```

Focus:

```text
- no unrelated edits
- no protected files touched unexpectedly
- no behavior changes hidden inside UI cleanup
- no dangerous project/signing changes
- no false validation claims
- report is complete and honest
```

---

## 9. Hook Design

Hooks make the agent reliable instead of purely prompt-based.

### 9.1 `SessionStart`

Purpose:

```text
Detect OS and available tools.
```

Detect:

```text
- Windows / WSL / macOS / Linux
- Git availability
- PowerShell/Bash availability
- Swift toolchain availability
- sourcekit-lsp availability
- xcodebuild availability
- project type
```

---

### 9.2 `UserPromptSubmit`

Purpose:

```text
Detect Apple/iOS intent even when the user does not type /apple.
```

Behavior:

```text
If prompt mentions iOS, SwiftUI, Xcode, App Store, StoreKit, Info.plist, entitlements, Apple architecture, etc., inject a light reminder or load the Apple Agent context.
```

Do not hijack every Swift question.

---

### 9.3 `PreToolUse`

Purpose:

```text
Block or ask before dangerous edits.
```

Protected paths:

```text
*.entitlements
Info.plist
project.pbxproj
*.xcworkspace
*.xcodeproj
*.xcconfig
fastlane/*
ExportOptions.plist
StoreKit configuration
auth/payment/security files
generated API clients
Secrets.plist
GoogleService-Info.plist
certificates/profiles
```

Behavior:

```text
- Allow reads
- Ask for edits to project/platform files
- Deny edits to secrets/certificates/provisioning profiles
- Ask before deleting files
```

---

### 9.4 `PostToolUse`

Purpose:

```text
After Swift/file edits, run lightweight static checks.
```

Windows PowerShell path:

```text
hooks/scripts/post-edit-static-check.ps1
```

Checks:

```text
- forbidden hardcoded colors
- force unwraps
- TODO/FIXME introduced
- massive View body
- missing accessibility label on icon-only buttons
- accidental protected-file edit
- Info.plist/privacy/entitlement inconsistency
```

---

### 9.5 `Stop`

Purpose:

```text
Prevent incomplete final answers.
```

Checks final response contains:

```text
- changed files
- what was validated
- what was inferred
- what requires macOS/Xcode
- protected file changes, if any
- remaining risks
```

---

## 10. Permission Model

Recommended default:

```text
Read-only tools: allow
Grep/Glob: allow
Agent/subagent: allow
Edit/Write: ask
Bash static scan scripts: ask first, then allow per project
xcodebuild: ask
git diff/status: allow
git commit: ask
git push: deny by default
delete files: ask/deny depending scope
secrets/certificates/profiles: deny
```

Recommended checked-in config:

```text
.claude/settings.json
```

Recommended machine-local config:

```text
.claude/settings.local.json
```

Use local config for Windows/macOS-specific command paths so the team-shared plugin remains portable.

---

## 11. Static Analysis Tools

These are scripts/binaries called by hooks/skills or exposed through MCP later.

### 11.1 `apple_project_scanner`

Inputs:

```text
repo root
```

Outputs:

```json
{
  "projectType": "swiftui-ios-app",
  "targets": [],
  "packages": [],
  "appleFrameworks": [],
  "extensions": [],
  "plists": [],
  "entitlements": [],
  "privacyManifests": [],
  "testTargets": [],
  "previewFiles": [],
  "macRequiredChecks": []
}
```

---

### 11.2 `swift_file_mapper`

Maps:

```text
- View files
- ViewModels
- Models
- Services
- Coordinators/Routers
- Stores
- Environment values
- ObservableObject / @Observable / @State usage
- async calls
- UIKit bridges
```

---

### 11.3 `swiftui_view_tree_analyzer`

Static approximation only.

Detects:

```text
- giant body
- nested stack soup
- hardcoded frames
- risky GeometryReader usage
- missing ScrollView for dense content
- icon-only buttons without accessibility label
- lineLimit/truncation risk
- inconsistent spacing
- duplicate components
- modifier order smells
```

---

### 11.4 `plist_checker`

Checks:

```text
- permission usage descriptions
- URL schemes
- background modes
- scene configuration
- app transport security exceptions
- supported orientations
- app category hints
```

---

### 11.5 `entitlement_checker`

Checks:

```text
- entitlement file exists when capabilities are detected
- suspicious capabilities
- associated domains format
- app groups format
- iCloud/CloudKit usage consistency
- push notification entitlement consistency
```

---

### 11.6 `privacy_manifest_checker`

Checks:

```text
- PrivacyInfo.xcprivacy existence
- required reason API categories
- SDK privacy manifest presence where inferable
- tracking domains
- mismatch between code usage and manifest declarations
```

---

### 11.7 `asset_catalog_checker`

Checks:

```text
- app icon set present
- accent color present
- missing universal image variants
- duplicate/unused assets, where inferable
- dark mode appearance variants
```

---

### 11.8 `localization_checker`

Checks:

```text
- hardcoded user-facing strings
- missing Localizable entries
- permission strings localization risk
- long localized text layout risk
```

---

### 11.9 `storekit_checker`

Checks:

```text
- StoreKit framework usage
- product ID scattering
- missing restore purchases affordance
- missing error/loading states
- subscription management affordance
- paywall text risk
- sandbox/Xcode validation required
```

---

## 12. LSP Strategy

Plan:

```text
Phase 1:
- No hard dependency on SourceKit-LSP.
- Agent works through file/static scanning.

Phase 2:
- Detect sourcekit-lsp if installed.
- Configure optional Swift LSP integration.
- Use diagnostics and symbol lookup where available.

Phase 3:
- Add better SwiftSyntax-based scanner for structural transforms.
```

Important:

> On Windows, SourceKit-LSP availability and Apple SDK awareness may vary. The agent should degrade gracefully.

---

## 13. MCP Strategy

MCP should be optional.

Use MCP for external integrations:

```text
- remote Mac validator
- GitHub/PR metadata
- Sentry/crash logs
- Linear/Jira issues
- Figma/design references
- App Store Connect metadata
- Xcode Cloud status
```

### 13.1 Optional Remote Mac Validator MCP

Design only:

```text
MCP server: apple-mac-validator
Runs on: Mac mini / MacStadium / CI / local Mac
Exposes:
- run_xcodebuild
- run_tests
- render_swiftui_previews
- capture_simulator_screenshots
- run_accessibility_audit
- run_storekit_sandbox_flow
```

Windows user flow:

```text
/apple fix Onboarding
↓
Windows static pass completes
↓
Agent says:
“Mac validator is available. I can request xcodebuild + simulator screenshots.”
↓
Requires user approval
```

No Mac available:

```text
Agent produces exact commands/checklist for later macOS validation.
```

---

## 14. Remote Control Compatibility

Claude Code Remote Control can allow a user to continue or steer a local Claude Code session from another device while the actual session runs on the machine with access to the local filesystem and tools.

This means `/apple fix ...` can run on Windows while the user approves decisions remotely, but the agent should not depend on Remote Control.

---

## 15. Apple Quality Rules

### 15.1 Architecture Rules

Check:

```text
- app lifecycle entry point is clean
- dependencies injected, not globally grabbed everywhere
- ViewModels do not own unrelated services directly
- views do not perform business logic
- async work is cancellation-aware
- MainActor boundaries are explicit where UI state mutates
- navigation is centralized enough to maintain
- feature boundaries are clear
- generated/API files are not hand-edited
- storage layer does not leak into UI
```

---

### 15.2 SwiftUI Rules

Check:

```text
- small composable views
- body is readable
- state ownership matches intent
- @StateObject vs @ObservedObject vs @Binding usage makes sense
- @Environment and @EnvironmentObject are not abused
- Preview states exist
- empty/loading/error/success states exist
- design tokens are used
- no random hardcoded colors/spacings
- Dynamic Type risk is flagged
- dark mode risk is flagged
- reusable components are extracted
```

---

### 15.3 Accessibility Rules

Check:

```text
- icon-only controls have accessibility labels
- combined cards have meaningful accessibility descriptions
- controls expose correct traits
- tap targets are likely large enough
- important images have labels or are hidden from accessibility
- Dynamic Type clipping risk
- color-only meaning risk
- Reduce Motion alternatives, when animations are present
- VoiceOver flow risk
```

Accessibility should be treated as a default requirement, not an optional polish pass.

---

### 15.4 Apple Platform Rules

Check:

```text
Info.plist:
- usage descriptions are specific and user-facing
- background modes are justified
- URL schemes/deep links are intentional
- ATS exceptions are suspicious and explained

Entitlements:
- capability usage matches code
- app groups/associated domains format
- push/iCloud/CloudKit/Sign in with Apple consistency

Privacy:
- PrivacyInfo.xcprivacy exists when needed
- required reason APIs declared
- third-party SDK privacy risk highlighted
- data sharing with AI/third parties disclosed

Assets:
- app icon set
- accent color
- dark mode variants
- SF Symbol usage sanity

Localization:
- no obvious hardcoded user-facing strings
- permission strings and paywall strings localizable
```

---

### 15.5 App Review / Ship Rules

Check:

```text
Safety:
- user-generated content moderation/reporting risk
- account deletion/support risk
- health/finance/children risk

Performance:
- crashes, broken links, placeholder content
- incomplete flows
- test account requirement

Business:
- StoreKit/paywall/subscription restore/manage flow
- external payment/linking risk
- price/offer clarity

Design:
- native-feeling navigation
- no copycat branding/icon risk
- no misleading UI

Legal:
- privacy policy
- data disclosure
- tracking/ATT
- third-party AI disclosure
```

---

## 16. Protected-File Policy

### 16.1 Freely Editable with Normal Approval

```text
SwiftUI views
UIKit view controllers
components
view models
feature-local models
tests
previews
localized strings
small helper types
```

### 16.2 Ask Before Editing

```text
Info.plist
*.entitlements
project.pbxproj
Package.swift
*.xcconfig
StoreKit files
auth files
payment files
analytics/privacy code
push notification setup
database migrations
navigation root
dependency container
```

### 16.3 Deny by Default

```text
certificates
provisioning profiles
private keys
secrets
API keys
production signing configs
generated files unless regeneration is requested
```

---

## 17. Reporting Contract

Every command should produce a consistent report.

### 17.1 `/apple scan` Report

```text
Apple Project Scan

Detected:
- Project type
- Targets
- Frameworks
- Architecture
- Tests
- Previews
- Apple capabilities
- Privacy files
- Release risks

Environment:
- OS
- available tools
- unavailable Mac-only validation

Recommended next:
- audit/fix/polish/shipcheck suggestion
```

---

### 17.2 `/apple audit` Report

```text
Apple Project Audit

Scope:
Findings:
- Critical
- High
- Medium
- Low

Categories:
- Architecture
- SwiftUI/UI
- Apple platform
- Privacy
- Testing
- Release

No code changed.
```

---

### 17.3 `/apple fix` Report

```text
Apple Fix Report

Scope:
Intent:
Risk mode:

Changed:
- file
- reason
- summary

Validated on this machine:
- checks run
- checks passed/failed

Inferred, not visually verified:
- layout risks
- simulator-only risks

Requires macOS/Xcode:
- xcodebuild command
- test command
- simulator/previews
- StoreKit/sandbox checks

Remaining risks:
```

---

### 17.4 `/apple polish` Report

```text
Apple Polish Report

Experience improvements:
Architecture improvements:
Accessibility improvements:
Preview/test improvements:
Behavior preserved:
Validation:
Mac-only checks:
```

---

### 17.5 `/apple shipcheck` Report

```text
Apple Shipcheck

Launch blockers:
App Review risks:
Privacy risks:
StoreKit/business risks:
Platform/config risks:
Testing gaps:
Mac/Xcode required validation:
Recommended release order:
```

---

## 18. Windows-Safe Validation Levels

The agent should label every check with a confidence tier.

```text
Verified:
The agent inspected concrete code/files and can prove the issue.

High confidence:
Static evidence strongly indicates a problem.

Inferred:
Likely issue, but runtime/Xcode validation needed.

Requires Mac:
Cannot be verified in this environment.
```

Example:

```text
Verified:
- Info.plist contains NSCameraUsageDescription.
- Camera API usage detected.
- PrivacyInfo.xcprivacy missing.

High confidence:
- OnboardingView likely clips at large text because fixed height + lineLimit(1).

Requires Mac:
- Actual Dynamic Type rendering in simulator.
```

---

## 19. Roadmap

### Phase 1 — Spec and Rulebook

Deliverables:

```text
- command contract
- report templates
- protected file policy
- Windows/Mac validation policy
- Apple rule categories
- skill/subagent prompt specs
```

No code yet.

---

### Phase 2 — Claude Code Plugin Skeleton

Deliverables:

```text
- plugin.json
- /apple skill
- supporting workflow docs
- subagent markdown files
- basic hooks.json
- PowerShell hook script stubs
```

Goal:

```text
/apple scan/audit/fix/polish/shipcheck routes correctly
```

---

### Phase 3 — Static Scanner MVP

Deliverables:

```text
- apple_project_scanner
- plist checker
- entitlement checker
- privacy manifest checker
- basic SwiftUI heuristic scanner
- Windows PowerShell integration
```

Goal:

```text
Useful on Windows with no Mac required.
```

---

### Phase 4 — Fix/Polish Workflows

Deliverables:

```text
- safe edit workflow
- final diff reviewer
- generated previews/tests suggestions
- protected file guard
- consistent report output
```

Goal:

```text
Agent can safely improve real project code.
```

---

### Phase 5 — Optional LSP and SwiftSyntax

Deliverables:

```text
- optional sourcekit-lsp config
- stronger symbol mapping
- AST-aware Swift transforms
- better state/navigation analysis
```

Goal:

```text
Less regex, more semantic correctness.
```

---

### Phase 6 — Optional Mac Validator MCP

Deliverables:

```text
- remote Mac validation protocol
- xcodebuild/test/simulator tools
- screenshot capture
- result ingestion
```

Goal:

```text
Windows user can request real Mac validation when available.
```

---

### Phase 7 — Distribution

Deliverables:

```text
- plugin marketplace metadata
- installation docs
- example repos
- sample reports
- team settings examples
```

---

## 20. Acceptance Criteria

The plan is successful when the agent can do this:

```text
/apple scan
```

Produces a useful Apple project map.

```text
/apple audit
```

Finds real architecture, Apple-platform, SwiftUI, privacy, test, and release risks without editing.

```text
/apple fix SomeFeature
```

Safely patches code, avoids protected files unless approved, validates what it can, and does not claim Mac-only checks passed.

```text
/apple polish SomeScreen
```

Improves SwiftUI/UI/accessibility/code structure while preserving behavior.

```text
/apple shipcheck
```

Produces a launch-readiness report aligned with Apple App Review, privacy, entitlement, StoreKit, and testing concerns.

Final reports must always include:

```text
- what changed
- what was verified locally
- what was inferred
- what requires macOS/Xcode
- what risky areas were avoided
- what remains to do
```

---

## 21. Gaps Filled from Earlier Concepts

The earlier concept was too UI-heavy. This plan expands the agent into a full Apple project specialist.

```text
Apple project architecture
App lifecycle
Info.plist
Entitlements
Privacy manifests
Required reason APIs
Third-party SDK privacy risk
App Store privacy labels
StoreKit/subscription risks
App Review guideline risks
Testing strategy
Localization
Assets
Xcode/macOS validation boundaries
Claude Code plugin packaging
Skill-backed command design
Hooks
Permissions
LSP
MCP
Remote Mac validation
Windows-first operation
```

The clean final shape:

```text
Apple Project Agent for Claude Code
├─ One /apple skill-backed command family
├─ Five understandable verbs
├─ Specialist subagents
├─ Deterministic safety hooks
├─ Windows-safe static analyzers
├─ Optional LSP intelligence
├─ Optional MCP Mac validator
├─ Apple platform/release rulebook
└─ Honest validation reporting
```

---

## 22. Reference Links

Claude Code:

- [Claude Code Overview](https://code.claude.com/docs/en/overview)
- [Claude Code Features Overview](https://code.claude.com/docs/en/features-overview)
- [Claude Code Skills](https://code.claude.com/docs/en/skills)
- [Claude Code Subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude Code Hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code Permissions](https://code.claude.com/docs/en/permissions)
- [Claude Code Settings](https://code.claude.com/docs/en/settings)
- [Claude Code Plugins Reference](https://code.claude.com/docs/en/plugins-reference)
- [Claude Code Tools Reference](https://code.claude.com/docs/en/tools-reference)
- [Claude Code Remote Control](https://code.claude.com/docs/en/remote-control)
- [Claude Code Plugin Marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)

Apple:

- [Xcode](https://developer.apple.com/xcode/)
- [SwiftUI](https://developer.apple.com/swiftui/)
- [Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/)
- [Accessibility HIG](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/)
- [App Privacy Details](https://developer.apple.com/app-store/app-privacy-details/)
- [Privacy Manifest Files](https://developer.apple.com/documentation/bundleresources/privacy-manifest-files)
- [Entitlements](https://developer.apple.com/documentation/bundleresources/entitlements)
- [StoreKit](https://developer.apple.com/documentation/storekit)
- [App Review Guideline Updates](https://developer.apple.com/news/?id=ey6d8onl)
- [Required Reason API / SDK Privacy Manifest News](https://developer.apple.com/news/?id=pvszzano)

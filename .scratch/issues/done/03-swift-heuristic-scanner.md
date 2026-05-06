Status: needs-triage

## Parent

- PRD: `.scratch/apple-agent-v1/PRD.md`

## What to build

Add regex-based Swift source analysis to the CLI. Detect SwiftUI/UIKit imports and base classes; approximate view body size and nested stack depth via brace counting; flag hardcoded colors, fonts, frames, and spacings; count `@StateObject` / `@ObservedObject` / `@EnvironmentObject` / `@State` / `@Binding` usage; detect `Task { ... }` inside views; flag `Image(systemName:)` without nearby accessibility labels; detect force unwraps, `try!`, `fatalError`, and `TODO`/`FIXME` markers; detect StoreKit import and API call patterns; count type-name suffixes (`ViewModel`, `Service`, `Manager`, `Store`, `Router`). Every finding must use `confidence: "heuristic"` or `high_confidence_heuristic`. Include focused unit tests with sample `.swift` files.

## Acceptance criteria

- [ ] SwiftUI and UIKit projects are distinguished by imports and superclass usage.
- [ ] Large view bodies and deep stack nesting are flagged with approximate line/depth counts.
- [ ] Hardcoded `.foregroundColor(.blue)`, `.font(.title)`, and `.frame(width: ...)` patterns are detected.
- [ ] `Image(systemName:)` without a trailing `.accessibilityLabel` is flagged.
- [ ] StoreKit imports and common StoreKit API usage are detected.
- [ ] All findings from this slice carry `confidence: "heuristic"`.
- [ ] Unit tests cover each heuristic against representative Swift snippets.

## Blocked by

- `.scratch/apple-agent-v1/issues/01-cli-foundation-scan.md`

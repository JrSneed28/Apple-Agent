#!/usr/bin/env python3
"""Integration and regression tests for apple-agent.py CLI.

Uses subprocess to invoke the CLI as a real user would.
Creates temporary project skeletons and verifies JSON output.
Standard library only.
"""

import json
import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path


_AGENT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apple-agent.py")


def _run_cli(*args):
    """Invoke apple-agent.py via subprocess and return parsed JSON stdout."""
    result = subprocess.run(
        [sys.executable, _AGENT_PATH] + list(args),
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


# ============================================================================
# 1. SPM skeleton — scan reports expected targets and dependencies
# ============================================================================


class TestSPMSkeletonScan(unittest.TestCase):
    """Integration test: representative SPM package skeleton."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_spm_skeleton_scan_includes_targets(self):
        # Package.swift
        (self.root / "Package.swift").write_text(
            '// swift-tools-version: 5.9\n'
            'import PackageDescription\n'
            'let package = Package(\n'
            '    name: "MyLibrary",\n'
            '    products: [.library(name: "MyLibrary", targets: ["MyLibrary"])],\n'
            '    dependencies: [\n'
            '        .package(url: "https://github.com/Alamofire/Alamofire.git", from: "5.8.0"),\n'
            '    ],\n'
            '    targets: [\n'
            '        .target(name: "MyLibrary", dependencies: ["Alamofire"]),\n'
            '        .testTarget(name: "MyLibraryTests", dependencies: ["MyLibrary"]),\n'
            '    ]\n'
            ')\n'
        )
        # Sources
        sources = self.root / "Sources" / "MyLibrary"
        sources.mkdir(parents=True)
        (sources / "Core.swift").write_text(
            'import Foundation\n'
            'public struct Core {\n'
            '    public init() {}\n'
            '}\n'
        )

        # Tests
        tests = self.root / "Tests" / "MyLibraryTests"
        tests.mkdir(parents=True)
        (tests / "CoreTests.swift").write_text(
            'import XCTest\n'
            '@testable import MyLibrary\n'
            'final class CoreTests: XCTestCase {\n'
            '    func testExample() {}\n'
            '}\n'
        )

        output = _run_cli("scan", "--root", str(self.root), "--json")

        # Verify project type
        self.assertEqual(output["project"]["type"], "spm")
        self.assertEqual(
            output["project"]["package_swift_path"], "Package.swift"
        )

        # Verify swift_files include sources and tests
        swift_files = output["project"].get("swift_files", [])
        self.assertGreaterEqual(len(swift_files), 2)
        source_paths = [f["path"] for f in swift_files]
        self.assertTrue(
            any("Core.swift" in p for p in source_paths),
            "Sources/Core.swift should be in swift_files",
        )
        self.assertTrue(
            any("CoreTests.swift" in p for p in source_paths),
            "Tests/CoreTests.swift should be in swift_files",
        )

        # Verify the output is valid JSON and passes validation
        self.assertTrue(output["validation"]["valid"])

    def test_spm_skeleton_findings_and_summary(self):
        """SPM scan should produce findings with proper structure."""
        (self.root / "Package.swift").write_text(
            '// swift-tools-version:5.9\n'
        )
        sources = self.root / "Sources" / "App"
        sources.mkdir(parents=True)
        (sources / "main.swift").write_text(
            'import Foundation\nprint("hello")\n'
        )

        output = _run_cli("scan", "--root", str(self.root), "--json")

        # All unified contract keys present
        for key in ["schema_version", "command", "environment",
                    "project", "findings", "suggested_actions",
                    "summary", "validation"]:
            self.assertIn(key, output, f"Missing key: {key}")

        self.assertEqual(output["command"], "scan")
        self.assertEqual(output["schema_version"], "1.0")


# ============================================================================
# 2. Xcode skeleton — real .pbxproj, scan reports expected target names
# ============================================================================


class TestXcodeSkeletonScan(unittest.TestCase):
    """Integration test: representative Xcode project skeleton."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_xcode_project(self, project_name="TestApp"):
        xcp = self.root / f"{project_name}.xcodeproj"
        xcp.mkdir()
        pbxproj = xcp / "project.pbxproj"
        pbxproj.write_text(f"""\
// !$*UTF8*$!
{{
    archiveVersion = 1;
    classes = {{}};
    objectVersion = 56;
    objects = {{
/* Begin PBXNativeTarget section */
        A111 /* {project_name} */ = {{
            isa = PBXNativeTarget;
            name = {project_name};
            productName = {project_name};
            productType = "com.apple.product-type.application";
            buildSettings = {{
                INFOPLIST_FILE = "{project_name}/Info.plist";
                PRODUCT_BUNDLE_IDENTIFIER = "com.example.{project_name}";
                SWIFT_VERSION = 5.0;
                IPHONEOS_DEPLOYMENT_TARGET = "16.0";
            }};
        }};
        B222 /* {project_name}Tests */ = {{
            isa = PBXNativeTarget;
            name = {project_name}Tests;
            productType = "com.apple.product-type.bundle.unit-test";
            buildSettings = {{
                INFOPLIST_FILE = "{project_name}Tests/Info.plist";
            }};
        }};
/* End PBXNativeTarget section */
    }};
    rootObject = 0001;
}}
""")
        return xcp

    def test_xcode_skeleton_scan_reports_target_names(self):
        self._make_xcode_project("TestApp")
        (self.root / "Sources").mkdir()
        (self.root / "Sources" / "App.swift").write_text("import SwiftUI")

        output = _run_cli("scan", "--root", str(self.root), "--json")

        self.assertEqual(output["project"]["type"], "xcode")
        self.assertIn("targets", output["project"])
        targets = output["project"]["targets"]
        self.assertEqual(len(targets), 2)

        target_names = [t["name"] for t in targets]
        self.assertIn("TestApp", target_names)
        self.assertIn("TestAppTests", target_names)

        # Each target should have the required fields
        for t in targets:
            self.assertIn("productType", t)
            self.assertIn("product_type_human", t)
            self.assertIn("project", t)
            self.assertEqual(t["project"], "TestApp")

    def test_xcode_skeleton_with_swiftui_import(self):
        self._make_xcode_project("MyApp")
        sources = self.root / "Sources"
        sources.mkdir()
        (sources / "ContentView.swift").write_text(
            'import SwiftUI\n'
            'struct ContentView: View {\n'
            '    var body: some View { Text("Hello") }\n'
            '}\n'
        )

        output = _run_cli("scan", "--root", str(self.root), "--json")

        # Should have swift_heuristics from the scan
        self.assertIn("swift_heuristics", output["project"])
        sh = output["project"]["swift_heuristics"]
        self.assertIn("heuristics", sh)
        # Should detect SwiftUI import
        imports = [h for h in sh["heuristics"]
                   if h["finding_id"] == "import_swiftui"]
        self.assertEqual(len(imports), 1)

    def test_xcode_skeleton_with_multiple_files_finds_all_targets(self):
        self._make_xcode_project("BigApp")
        sources = self.root / "Sources"
        sources.mkdir(parents=True)
        for i in range(3):
            (sources / f"File{i}.swift").write_text(
                f'// Source file {i}\nimport Foundation\n'
            )

        output = _run_cli("scan", "--root", str(self.root), "--json")

        self.assertEqual(output["project"]["type"], "xcode")
        self.assertEqual(len(output["project"]["targets"]), 2)
        # Should have swift files from directory scan
        self.assertIn("swift_files", output["project"])
        self.assertEqual(output["project"]["swift_file_count"], 3)


# ============================================================================
# 3. Malformed .pbxproj — lexer fallback without crashing the CLI
# ============================================================================


class TestMalformedPbxprojFallback(unittest.TestCase):
    """Integration test: malformed .pbxproj triggers lexer fallback."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_malformed_pbxproj_no_crash(self):
        xcp = self.root / "Broken.xcodeproj"
        xcp.mkdir()
        (xcp / "project.pbxproj").write_text("COMPLETELY BROKEN {{{ gibberish [] :::")

        (self.root / "App.swift").write_text("import SwiftUI")

        # This must not raise — the CLI should handle gracefully
        output = _run_cli("scan", "--root", str(self.root), "--json")

        # Should still identify as xcode project
        self.assertEqual(output["project"]["type"], "xcode")
        # Should produce valid output
        self.assertTrue(output["validation"]["valid"])
        # Should have warnings about the malformed pbxproj
        self.assertTrue(
            len(output["validation"]["warnings"]) > 0,
            "Should have warnings about malformed pbxproj",
        )
        # Should still produce directory scan data
        self.assertIn("swift_files", output["project"])
        self.assertEqual(output["project"]["swift_file_count"], 1)

    def test_malformed_pbxproj_empty_body_no_crash(self):
        xcp = self.root / "Empty.xcodeproj"
        xcp.mkdir()
        (xcp / "project.pbxproj").write_text("")

        (self.root / "Helper.swift").write_text("import Foundation")

        output = _run_cli("scan", "--root", str(self.root), "--json")

        self.assertEqual(output["project"]["type"], "xcode")
        self.assertTrue(output["validation"]["valid"])
        self.assertTrue(len(output["validation"]["warnings"]) > 0)

    def test_malformed_pbxproj_scan_has_swift_heuristics(self):
        """Even with broken pbxproj, Swift file analysis should still work."""
        xcp = self.root / "Corrupt.xcodeproj"
        xcp.mkdir()
        (xcp / "project.pbxproj").write_text("NOT VALID {{{")

        (self.root / "View.swift").write_text(
            'import SwiftUI\n'
            'struct MyView: View {\n'
            '    var body: some View { Text("Hi") }\n'
            '}\n'
        )

        output = _run_cli("scan", "--root", str(self.root), "--json")

        # Swift heuristic scan should still run
        self.assertIn("swift_heuristics", output["project"])
        # Should find SwiftUI import even with broken pbxproj
        sh = output["project"]["swift_heuristics"]
        swiftui_imports = [
            h for h in sh["heuristics"]
            if h["finding_id"] == "import_swiftui"
        ]
        self.assertEqual(len(swiftui_imports), 1)


# ============================================================================
# 4. Mixed UIKit/SwiftUI — both UI frameworks detected in flat directory
# ============================================================================


class TestMixedUIKitSwiftUI(unittest.TestCase):
    """Integration test: mixed UIKit/SwiftUI flat directory."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_mixed_directory_yields_both_framework_findings(self):
        """Flat directory with UIKit and SwiftUI files should detect both."""
        (self.root / "LoginView.swift").write_text(
            'import SwiftUI\n'
            'struct LoginView: View {\n'
            '    @State private var username = ""\n'
            '    var body: some View {\n'
            '        TextField("Username", text: $username)\n'
            '            .foregroundColor(.blue)\n'
            '            .frame(width: 300)\n'
            '    }\n'
            '}\n'
        )
        (self.root / "ProfileVC.swift").write_text(
            'import UIKit\n'
            'class ProfileViewController: UIViewController {\n'
            '    override func viewDidLoad() {\n'
            '        super.viewDidLoad()\n'
            '        view.backgroundColor = .systemBackground\n'
            '        let label = UILabel()\n'
            '        label.font = UIFont.systemFont(ofSize: 17)\n'
            '        label.text = "Profile"\n'
            '        view.addSubview(label)\n'
            '    }\n'
            '}\n'
        )
        (self.root / "SettingsView.swift").write_text(
            'import SwiftUI\n'
            'struct SettingsView: View {\n'
            '    @State private var notifications = true\n'
            '    var body: some View {\n'
            '        Toggle("Notifications", isOn: $notifications)\n'
            '            .padding(16)\n'
            '    }\n'
            '}\n'
        )

        output = _run_cli("scan", "--root", str(self.root), "--json")

        # Should be "flat" type
        self.assertEqual(output["project"]["type"], "flat")

        # Should have swift_heuristics
        self.assertIn("swift_heuristics", output["project"])
        sh = output["project"]["swift_heuristics"]

        # Should detect both SwiftUI and UIKit
        swiftui_imports = [
            h for h in sh["heuristics"]
            if h["finding_id"] == "import_swiftui"
        ]
        uikit_imports = [
            h for h in sh["heuristics"]
            if h["finding_id"] == "import_uikit"
        ]
        self.assertGreaterEqual(len(swiftui_imports), 1,
                                "Should detect SwiftUI imports")
        self.assertGreaterEqual(len(uikit_imports), 1,
                                "Should detect UIKit imports")

        # Summary should reflect both
        self.assertEqual(sh["summary"]["swiftui_files"], 1)
        self.assertEqual(sh["summary"]["uikit_files"], 1)

    def test_mixed_directory_findings_include_hardcoded_patterns(self):
        """Mixed project should flag hardcoded UI patterns from both frameworks."""
        (self.root / "SwiftUIView.swift").write_text(
            'import SwiftUI\n'
            'struct SwiftUIView: View {\n'
            '    var body: some View {\n'
            '        VStack(spacing: 12) {\n'
            '            Text("Title").font(.title).foregroundColor(.red)\n'
            '            Image(systemName: "star")\n'
            '        }\n'
            '    }\n'
            '}\n'
        )
        (self.root / "UIKitView.swift").write_text(
            'import UIKit\n'
            'class UIKitView: UIView {\n'
            '    let label = UILabel()\n'
            '    func setup() {\n'
            '        label.font = UIFont.systemFont(ofSize: 14)\n'
            '    }\n'
            '}\n'
        )

        output = _run_cli("scan", "--root", str(self.root), "--json")

        sh = output["project"]["swift_heuristics"]

        # Should have hardcoded UI findings
        hardcoded = [h for h in sh["heuristics"]
                     if h["category"] == "hardcoded_ui"]
        self.assertGreaterEqual(len(hardcoded), 1,
                                "Should find hardcoded UI patterns")

        # Should have image accessibility finding
        images = [h for h in sh["heuristics"]
                  if h["category"] == "accessibility"]
        self.assertGreaterEqual(len(images), 1,
                                "Should find accessibility findings")

    def test_mixed_directory_all_findings_confidence_labeled(self):
        """Every finding in mixed directory should have confidence."""
        (self.root / "App.swift").write_text(
            'import SwiftUI\nimport UIKit\n'
            'struct AppView: View {\n'
            '    var body: some View { Text("Hi").foregroundColor(.green) }\n'
            '}\n'
        )

        output = _run_cli("scan", "--root", str(self.root), "--json")

        for finding in output["findings"]:
            self.assertIn("confidence", finding,
                          f"Finding missing confidence: {finding.get('finding_id', '?')}")
            self.assertIn(finding["confidence"],
                          ["verified", "heuristic", "high_confidence_heuristic"])


# ============================================================================
# 5. Skill-to-CLI subprocess contract verification
# ============================================================================


class TestSubprocessContract(unittest.TestCase):
    """Verify skill-to-CLI subprocess JSON contract for all subcommands."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        (self.root / "App.swift").write_text(
            'import SwiftUI\n'
            'struct MyApp: App {\n'
            '    var body: some Scene {\n'
            '        WindowGroup { Text("Hello") }\n'
            '    }\n'
            '}\n'
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_scan_subprocess_returns_valid_json(self):
        result = subprocess.run(
            [sys.executable, _AGENT_PATH, "scan",
             "--root", str(self.root), "--json"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertIsInstance(output, dict)
        self.assertEqual(output["command"], "scan")

    def test_audit_subprocess_returns_valid_json(self):
        result = subprocess.run(
            [sys.executable, _AGENT_PATH, "audit",
             "--root", str(self.root), "--json"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertIsInstance(output, dict)
        self.assertEqual(output["command"], "audit")

    def test_shipcheck_subprocess_returns_valid_json(self):
        result = subprocess.run(
            [sys.executable, _AGENT_PATH, "shipcheck",
             "--root", str(self.root), "--json"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertIsInstance(output, dict)
        self.assertEqual(output["command"], "shipcheck")
        # Shipcheck-specific keys
        self.assertIn("shipcheck", output)
        sc = output["shipcheck"]
        for key in ["launch_blockers", "app_review_risks",
                    "privacy_risks", "storekit_risks"]:
            self.assertIn(key, sc)

    def test_validate_subprocess_returns_valid_json(self):
        result = subprocess.run(
            [sys.executable, _AGENT_PATH, "validate",
             "--root", str(self.root), "--json"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertIsInstance(output, dict)
        self.assertEqual(output["command"], "validate")

    def test_all_commands_share_common_keys(self):
        """All subcommands return the same top-level JSON keys."""
        common_keys = ["schema_version", "command", "environment",
                       "project", "findings", "suggested_actions",
                       "summary", "validation"]

        for cmd in ["scan", "audit", "shipcheck", "validate"]:
            result = subprocess.run(
                [sys.executable, _AGENT_PATH, cmd,
                 "--root", str(self.root), "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0,
                             f"Command '{cmd}' failed with exit code {result.returncode}")
            output = json.loads(result.stdout)
            for key in common_keys:
                self.assertIn(key, output,
                              f"'{cmd}' output missing key: {key}")

    def test_json_parseable_for_bad_root(self):
        """CLI should return valid JSON even for invalid roots."""
        result = subprocess.run(
            [sys.executable, _AGENT_PATH, "scan",
             "--root", "/nonexistent/path/xyz", "--json"],
            capture_output=True, text=True,
        )
        output = json.loads(result.stdout)
        self.assertIsInstance(output, dict)
        self.assertIn("validation", output)
        self.assertFalse(output["validation"]["valid"])
        self.assertGreater(len(output["validation"]["errors"]), 0)

    def test_shipcheck_risk_score_is_valid(self):
        """Shipcheck risk_score should be within 0-100 range."""
        result = subprocess.run(
            [sys.executable, _AGENT_PATH, "shipcheck",
             "--root", str(self.root), "--json"],
            capture_output=True, text=True,
        )
        output = json.loads(result.stdout)
        score = output["shipcheck"]["risk_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_audit_with_target_filter(self):
        """Audit with --target should scope findings."""
        (self.root / "Sources").mkdir()
        (self.root / "Sources" / "A.swift").write_text(
            'import SwiftUI\nstruct A: View { var body: some View { Text("A") } }\n'
        )
        (self.root / "Tests").mkdir()
        (self.root / "Tests" / "B.swift").write_text(
            'import Foundation\n'
        )

        result = subprocess.run(
            [sys.executable, _AGENT_PATH, "audit",
             "--root", str(self.root),
             "--target", str(self.root / "Tests"),
             "--json"],
            capture_output=True, text=True,
        )
        output = json.loads(result.stdout)
        self.assertEqual(output["command"], "audit")
        self.assertIn("audit_scope", output)
        self.assertEqual(
            output["audit_scope"]["target"],
            str(self.root / "Tests"),
        )


# ============================================================================
# Regression: edge cases
# ============================================================================


class TestRegressionEdgeCases(unittest.TestCase):
    """Regression tests for edge cases in CLI behavior."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_empty_directory_scan_does_not_crash(self):
        """Scanning an empty directory should not crash."""
        result = subprocess.run(
            [sys.executable, _AGENT_PATH, "scan",
             "--root", str(self.root), "--json"],
            capture_output=True, text=True,
        )
        output = json.loads(result.stdout)
        self.assertEqual(output["project"]["type"], "flat")
        self.assertTrue(output["validation"]["valid"])

    def test_scan_with_only_plist_files_no_crash(self):
        """Directory with only .plist files should not crash."""
        import plistlib
        info_plist = {"CFBundleName": "Test"}
        with open(self.root / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        result = subprocess.run(
            [sys.executable, _AGENT_PATH, "scan",
             "--root", str(self.root), "--json"],
            capture_output=True, text=True,
        )
        output = json.loads(result.stdout)
        self.assertIsInstance(output, dict)

    def test_scan_with_binary_file_no_crash(self):
        """Directory containing binary files should not crash."""
        (self.root / "data.bin").write_bytes(b"\x00\x01\x02\xFF\xFE")
        (self.root / "App.swift").write_text("import Foundation")

        result = subprocess.run(
            [sys.executable, _AGENT_PATH, "scan",
             "--root", str(self.root), "--json"],
            capture_output=True, text=True,
        )
        output = json.loads(result.stdout)
        self.assertIsInstance(output, dict)

    def test_xcode_project_no_source_files(self):
        """Xcode project with pbxproj but no source files should work."""
        xcp = self.root / "Minimal.xcodeproj"
        xcp.mkdir()
        (xcp / "project.pbxproj").write_text("""\
{
    objects = {
/* Begin PBXNativeTarget section */
        AAA /* App */ = {
            isa = PBXNativeTarget;
            name = App;
            productType = "com.apple.product-type.application";
        };
/* End PBXNativeTarget section */
    };
}
""")

        result = subprocess.run(
            [sys.executable, _AGENT_PATH, "scan",
             "--root", str(self.root), "--json"],
            capture_output=True, text=True,
        )
        output = json.loads(result.stdout)
        self.assertEqual(output["project"]["type"], "xcode")
        self.assertEqual(len(output["project"]["targets"]), 1)


if __name__ == "__main__":
    unittest.main()

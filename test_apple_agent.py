#!/usr/bin/env python3
"""Unit tests for apple-agent.py CLI."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Import apple-agent.py (filename has a hyphen, so use importlib)
_agent_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apple-agent.py")
spec = importlib.util.spec_from_file_location("apple_agent", _agent_path)
apple_agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apple_agent)


class TestEnvironmentDetection(unittest.TestCase):
    """Tests for environment detection."""

    def test_detect_environment_shape(self):
        env = apple_agent.detect_environment()
        self.assertIn("os", env)
        self.assertIn("python_version", env)
        self.assertIn("is_macos", env)
        self.assertIn("platform_machine", env)
        self.assertEqual(type(env["is_macos"]), bool)


class TestProjectDetection(unittest.TestCase):
    """Tests for project type detection."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_detect_spm_project(self):
        (self.root / "Package.swift").write_text("// swift-tools-version: 5.9")
        result = apple_agent.detect_project_type(str(self.root))
        self.assertEqual(result["type"], "spm")

    def test_detect_xcode_project(self):
        xcp = self.root / "Test.xcodeproj"
        xcp.mkdir()
        (xcp / "project.pbxproj").write_text("// placeholder")
        result = apple_agent.detect_project_type(str(self.root))
        self.assertEqual(result["type"], "xcode")
        self.assertIn("xcodeproj_paths", result)
        self.assertIn("Test.xcodeproj", result["xcodeproj_paths"])

    def test_detect_flat_directory(self):
        (self.root / "App.swift").write_text("print(\"hello\")")
        result = apple_agent.detect_project_type(str(self.root))
        self.assertEqual(result["type"], "flat")
        self.assertEqual(result["swift_file_count"], 1)

    def test_detect_empty_flat_directory(self):
        result = apple_agent.detect_project_type(str(self.root))
        self.assertEqual(result["type"], "flat")
        self.assertEqual(result["swift_file_count"], 0)

    def test_invalid_directory(self):
        result = apple_agent.detect_project_type("/nonexistent/path/12345")
        self.assertEqual(result["type"], "invalid")


class TestPbxprojLexer(unittest.TestCase):
    """Tests for the minimal project.pbxproj lexer."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_pbxproj(self, content):
        path = os.path.join(self.tmpdir.name, "project.pbxproj")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_extract_single_target(self):
        pbxproj = self._write_pbxproj("""\
// !$*UTF8*$!
{
    rootObject = 1234;
    objects = {
/* Begin PBXNativeTarget section */
        A12345678901234567890123 /* MyApp */ = {
            isa = PBXNativeTarget;
            name = MyApp;
            productType = "com.apple.product-type.application";
            buildSettings = {
                INFOPLIST_FILE = "MyApp/Info.plist";
                PRODUCT_BUNDLE_IDENTIFIER = "com.example.MyApp";
            };
        };
/* End PBXNativeTarget section */
    };
}
""")
        result = apple_agent.lex_pbxproj(pbxproj)
        self.assertTrue(result["parse_success"])
        self.assertEqual(len(result["targets"]), 1)
        self.assertEqual(result["targets"][0]["name"], "MyApp")
        self.assertEqual(
            result["targets"][0]["productType"],
            "com.apple.product-type.application",
        )
        self.assertIn("buildSettings", result["targets"][0])
        self.assertEqual(
            result["targets"][0]["buildSettings"]["INFOPLIST_FILE"],
            "MyApp/Info.plist",
        )

    def test_extract_multiple_targets(self):
        pbxproj = self._write_pbxproj("""\
{
    objects = {
/* Begin PBXNativeTarget section */
        AAA /* App */ = {
            isa = PBXNativeTarget;
            name = App;
            productType = "com.apple.product-type.application";
        };
        BBB /* Tests */ = {
            isa = PBXNativeTarget;
            name = Tests;
            productType = "com.apple.product-type.bundle.unit-test";
        };
        CCC /* Widget */ = {
            isa = PBXNativeTarget;
            name = Widget;
            productType = "com.apple.product-type.app-extension";
        };
/* End PBXNativeTarget section */
    };
}
""")
        result = apple_agent.lex_pbxproj(pbxproj)
        self.assertTrue(result["parse_success"])
        self.assertEqual(len(result["targets"]), 3)

        names = [t["name"] for t in result["targets"]]
        self.assertIn("App", names)
        self.assertIn("Tests", names)
        self.assertIn("Widget", names)

    def test_extract_product_type_human(self):
        pbxproj = self._write_pbxproj("""\
{
    objects = {
/* Begin PBXNativeTarget section */
        AAA /* App */ = {
            isa = PBXNativeTarget;
            name = App;
            productType = "com.apple.product-type.application.watchapp2";
        };
/* End PBXNativeTarget section */
    };
}
""")
        result = apple_agent.lex_pbxproj(pbxproj)
        self.assertTrue(result["parse_success"])
        self.assertEqual(result["targets"][0]["product_type_human"], "watchapp2")

    def test_falls_back_to_comment_name(self):
        pbxproj = self._write_pbxproj("""\
{
    objects = {
/* Begin PBXNativeTarget section */
        AAA /* FallbackName */ = {
            isa = PBXNativeTarget;
            productType = "com.apple.product-type.application";
        };
/* End PBXNativeTarget section */
    };
}
""")
        result = apple_agent.lex_pbxproj(pbxproj)
        self.assertTrue(result["parse_success"])
        self.assertEqual(result["targets"][0]["name"], "FallbackName")

    def test_malformed_pbxproj_no_crash(self):
        pbxproj = self._write_pbxproj("NOT A VALID PBXPROJ {{{ [[[ gibberish")
        result = apple_agent.lex_pbxproj(pbxproj)
        # Should not crash, just report parse failure
        self.assertFalse(result["parse_success"])
        self.assertGreater(len(result["warnings"]), 0)

    def test_empty_pbxproj(self):
        pbxproj = self._write_pbxproj("")
        result = apple_agent.lex_pbxproj(pbxproj)
        self.assertFalse(result["parse_success"])
        self.assertGreater(len(result["warnings"]), 0)

    def test_nonexistent_pbxproj(self):
        result = apple_agent.lex_pbxproj(
            os.path.join(self.tmpdir.name, "does_not_exist.pbxproj")
        )
        self.assertFalse(result["parse_success"])
        self.assertGreater(len(result["warnings"]), 0)

    def test_no_native_target_section(self):
        pbxproj = self._write_pbxproj("""\
{
    objects = {
        /* No PBXNativeTarget section here */
    };
}
""")
        result = apple_agent.lex_pbxproj(pbxproj)
        self.assertTrue(result["parse_success"])
        self.assertEqual(len(result["targets"]), 0)

    def test_build_settings_extraction(self):
        pbxproj = self._write_pbxproj("""\
{
    objects = {
/* Begin PBXNativeTarget section */
        AAA /* App */ = {
            isa = PBXNativeTarget;
            name = App;
            productType = "com.apple.product-type.application";
            buildSettings = {
                SWIFT_VERSION = 5.0;
                IPHONEOS_DEPLOYMENT_TARGET = "16.0";
                ENABLE_TESTABILITY = YES;
                CODE_SIGN_STYLE = Automatic;
            };
        };
/* End PBXNativeTarget section */
    };
}
""")
        result = apple_agent.lex_pbxproj(pbxproj)
        self.assertTrue(result["parse_success"])
        settings = result["targets"][0]["buildSettings"]
        self.assertEqual(settings.get("SWIFT_VERSION"), "5.0")
        self.assertEqual(settings.get("IPHONEOS_DEPLOYMENT_TARGET"), "16.0")


class TestScanJSONShape(unittest.TestCase):
    """Tests for the scan subcommand JSON output shape."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_json_has_required_top_level_keys(self):
        (self.root / "App.swift").write_text("print(\"hello\")")
        result = apple_agent.cmd_scan(str(self.root))
        self.assertIn("schema_version", result)
        self.assertIn("environment", result)
        self.assertIn("project", result)
        self.assertIn("validation", result)

    def test_schema_version_is_1_0(self):
        (self.root / "App.swift").write_text("print(\"hello\")")
        result = apple_agent.cmd_scan(str(self.root))
        self.assertEqual(result["schema_version"], "1.0")

    def test_validation_block_has_errors_and_warnings(self):
        (self.root / "App.swift").write_text("print(\"hello\")")
        result = apple_agent.cmd_scan(str(self.root))
        self.assertIn("errors", result["validation"])
        self.assertIn("warnings", result["validation"])
        self.assertIn("valid", result["validation"])
        self.assertEqual(type(result["validation"]["errors"]), list)
        self.assertEqual(type(result["validation"]["warnings"]), list)

    def test_scan_invalid_root_reports_error(self):
        result = apple_agent.cmd_scan("/nonexistent/path/xyz")
        self.assertIn("errors", result["validation"])
        self.assertGreater(len(result["validation"]["errors"]), 0)
        self.assertFalse(result["validation"]["valid"])

    def test_scan_xcode_project_json_shape(self):
        xcp = self.root / "TestApp.xcodeproj"
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
        (self.root / "Sources").mkdir()
        (self.root / "Sources" / "App.swift").write_text("import SwiftUI")
        result = apple_agent.cmd_scan(str(self.root))
        self.assertEqual(result["project"]["type"], "xcode")
        self.assertIn("targets", result["project"])
        self.assertEqual(len(result["project"]["targets"]), 1)
        self.assertEqual(result["project"]["targets"][0]["name"], "App")

    def test_scan_spm_project_json_shape(self):
        (self.root / "Package.swift").write_text("// swift-tools-version:5.9")
        (self.root / "Sources").mkdir()
        (self.root / "Sources" / "main.swift").write_text("print(\"hi\")")
        result = apple_agent.cmd_scan(str(self.root))
        self.assertEqual(result["project"]["type"], "spm")
        self.assertIn("package_swift_path", result["project"])


class TestScanGracefulFallback(unittest.TestCase):
    """Tests for graceful fallback on malformed pbxproj."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_malformed_pbxproj_triggers_warning_not_error(self):
        xcp = self.root / "Broken.xcodeproj"
        xcp.mkdir()
        (xcp / "project.pbxproj").write_text("COMPLETELY BROKEN {{{ gibberish")
        (self.root / "App.swift").write_text("import SwiftUI")
        result = apple_agent.cmd_scan(str(self.root))
        # Should still produce valid JSON with project type xcode
        self.assertEqual(result["project"]["type"], "xcode")
        # Validation should have warnings, not errors (for this case)
        self.assertTrue(len(result["validation"]["warnings"]) > 0)
        # Should still be valid overall (no crash)
        self.assertTrue(result["validation"]["valid"])

    def test_malformed_pbxproj_still_produces_directory_scan(self):
        xcp = self.root / "Broken.xcodeproj"
        xcp.mkdir()
        (xcp / "project.pbxproj").write_text("BROKEN")
        (self.root / "Helper.swift").write_text("import Foundation")
        result = apple_agent.cmd_scan(str(self.root))
        # Should still have swift file data from directory scan
        self.assertIn("swift_files", result["project"])
        self.assertEqual(result["project"]["swift_file_count"], 1)


class TestAuditSubcommand(unittest.TestCase):
    """Tests for the audit subcommand."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_audit_output_has_unified_contract(self):
        (self.root / "App.swift").write_text("print(\"hello\")")
        result = apple_agent.cmd_audit(str(self.root))
        self.assertEqual(result["command"], "audit")
        self.assertIn("findings", result)
        self.assertIn("suggested_actions", result)
        self.assertIn("summary", result)
        self.assertIn("performed", result["validation"])

    def test_audit_with_target_filters_findings(self):
        (self.root / "Sources").mkdir(parents=True)
        (self.root / "Sources" / "App.swift").write_text(
            "import SwiftUI\nstruct MyView: View {\n"
            "  var body: some View { Text(\"hi\") }\n}"
        )
        (self.root / "Tests").mkdir()
        (self.root / "Tests" / "Test.swift").write_text("import Foundation")
        result = apple_agent.cmd_audit(
            str(self.root), target_path=str(self.root / "Tests")
        )
        self.assertEqual(result["command"], "audit")
        self.assertIn("audit_scope", result)
        self.assertEqual(
            result["audit_scope"]["target"],
            str(self.root / "Tests"),
        )

    def test_audit_scoped_to_empty_dir(self):
        (self.root / "Sources").mkdir(parents=True)
        (self.root / "Sources" / "App.swift").write_text("import SwiftUI")
        (self.root / "Empty").mkdir()
        result = apple_agent.cmd_audit(
            str(self.root), target_path=str(self.root / "Empty")
        )
        self.assertEqual(result["command"], "audit")
        # All file-level findings should be filtered out
        for f in result["findings"]:
            if f.get("file"):
                self.fail(f"Unexpected file finding in scoped audit: {f}")


class TestShipcheckSubcommand(unittest.TestCase):
    """Tests for the shipcheck subcommand."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_shipcheck_has_required_keys(self):
        (self.root / "App.swift").write_text("print(\"hello\")")
        result = apple_agent.cmd_shipcheck(str(self.root))
        self.assertEqual(result["command"], "shipcheck")
        self.assertIn("shipcheck", result)
        sc = result["shipcheck"]
        self.assertIn("launch_blockers", sc)
        self.assertIn("app_review_risks", sc)
        self.assertIn("privacy_risks", sc)
        self.assertIn("storekit_risks", sc)
        self.assertIn("risk_score", sc)
        self.assertIn("assessment", sc)
        self.assertIn("assessment_message", sc)

    def test_shipcheck_buckets_have_required_structure(self):
        (self.root / "App.swift").write_text("print(\"hello\")")
        result = apple_agent.cmd_shipcheck(str(self.root))
        for bucket_name in ["launch_blockers", "app_review_risks",
                            "privacy_risks", "storekit_risks"]:
            bucket = result["shipcheck"][bucket_name]
            self.assertIn("label", bucket)
            self.assertIn("description", bucket)
            self.assertIn("severity_counts", bucket)
            self.assertIn("count", bucket)
            self.assertIn("findings", bucket)
            self.assertEqual(bucket["count"], len(bucket["findings"]))

    def test_shipcheck_risk_score_range(self):
        (self.root / "App.swift").write_text("print(\"hello\")")
        result = apple_agent.cmd_shipcheck(str(self.root))
        score = result["shipcheck"]["risk_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_shipcheck_assessment_is_valid(self):
        (self.root / "App.swift").write_text("print(\"hello\")")
        result = apple_agent.cmd_shipcheck(str(self.root))
        self.assertIn(
            result["shipcheck"]["assessment"],
            ["clean", "low_risk", "moderate_risk", "high_risk"],
        )

    def test_shipcheck_with_permission_missing_finding(self):
        (self.root / "Sources").mkdir()
        (self.root / "Sources" / "App.swift").write_text("import AVFoundation")
        # Need a plist file present for the permission string analyzer to check
        # against (otherwise it returns empty since there's nothing to analyze)
        import plistlib
        (self.root / "Info.plist").write_bytes(plistlib.dumps({}))
        result = apple_agent.cmd_shipcheck(str(self.root))
        sc = result["shipcheck"]
        # Missing permission string should go to launch_blockers
        self.assertGreater(sc["launch_blockers"]["count"], 0,
                           "Permission string finding should be in launch_blockers")
        # Risk score should be >0
        self.assertGreater(sc["risk_score"], 0)


class TestValidateSubcommand(unittest.TestCase):
    """Tests for the validate subcommand."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_validate_produces_same_shape_as_scan(self):
        (self.root / "App.swift").write_text("print(\"hello\")")
        scan_result = apple_agent.cmd_scan(str(self.root))
        validate_result = apple_agent.cmd_validate(str(self.root))
        # Both should have the same top-level keys
        self.assertEqual(
            sorted(scan_result.keys()), sorted(validate_result.keys())
        )

    def test_validate_has_distinct_command_label(self):
        (self.root / "App.swift").write_text("print(\"hello\")")
        result = apple_agent.cmd_validate(str(self.root))
        self.assertEqual(result["command"], "validate")
        # Validate is distinct from scan
        self.assertNotEqual(result["command"], "scan")


class TestUnifiedJSONContract(unittest.TestCase):
    """Tests for the unified JSON contract across all subcommands."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _get_results(self):
        (self.root / "App.swift").write_text("print(\"hello\")")
        return {
            "scan": apple_agent.cmd_scan(str(self.root)),
            "audit": apple_agent.cmd_audit(str(self.root)),
            "shipcheck": apple_agent.cmd_shipcheck(str(self.root)),
            "validate": apple_agent.cmd_validate(str(self.root)),
        }

    def test_all_commands_have_identical_top_level_keys(self):
        results = self._get_results()
        base_keys = set(results["scan"].keys())
        # shipcheck has an extra "shipcheck" key
        for cmd, result in results.items():
            common = base_keys & set(result.keys())
            for k in ["schema_version", "command", "environment", "project",
                       "findings", "suggested_actions", "summary", "validation"]:
                self.assertIn(k, result, f"{cmd} missing key '{k}'")

    def test_schema_version_consistent_across_commands(self):
        results = self._get_results()
        for cmd, result in results.items():
            self.assertEqual(
                result["schema_version"], "1.0",
                f"{cmd} has wrong schema_version"
            )

    def test_validation_block_has_all_required_fields(self):
        results = self._get_results()
        required = ["performed", "skipped", "requires_macos", "errors",
                     "warnings", "valid"]
        for cmd, result in results.items():
            for field in required:
                self.assertIn(
                    field, result["validation"],
                    f"{cmd} validation missing '{field}'"
                )

    def test_summary_has_all_severity_counts(self):
        results = self._get_results()
        severities = ["critical", "high", "medium", "low", "info"]
        for cmd, result in results.items():
            for sev in severities:
                self.assertIn(
                    sev, result["summary"],
                    f"{cmd} summary missing '{sev}'"
                )
                self.assertIsInstance(
                    result["summary"][sev], int,
                    f"{cmd} summary['{sev}'] is not int"
                )

    def test_findings_are_normalized(self):
        results = self._get_results()
        for cmd, result in results.items():
            for f in result["findings"]:
                self.assertIn("severity", f, f"Finding missing severity in {cmd}")
                self.assertIn("confidence", f, f"Finding missing confidence in {cmd}")
                self.assertIn("category", f, f"Finding missing category in {cmd}")
                self.assertIn("message", f, f"Finding missing message in {cmd}")
                # severity should be one of the valid values
                self.assertIn(
                    f["severity"],
                    ["critical", "high", "medium", "low", "info"],
                    f"Invalid severity '{f['severity']}' in {cmd}"
                )

    def test_findings_count_matches_summary(self):
        results = self._get_results()
        for cmd, result in results.items():
            total = sum(result["summary"].values())
            self.assertEqual(
                len(result["findings"]), total,
                f"{cmd}: findings count {len(result['findings'])} != summary total {total}"
            )

    def test_validation_performed_list_is_nonempty(self):
        results = self._get_results()
        for cmd, result in results.items():
            self.assertGreater(
                len(result["validation"]["performed"]), 0,
                f"{cmd} has empty performed list"
            )


class TestDirectoryScan(unittest.TestCase):
    """Tests for directory scan functionality."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_directory_scan_finds_files(self):
        (self.root / "main.swift").write_text("print(\"hi\")")
        (self.root / "Info.plist").write_text("<xml></xml>")
        result = apple_agent.directory_scan(str(self.root))
        self.assertEqual(result["total_swift_file_count"], 1)
        self.assertEqual(len(result["swift_files"]), 1)
        self.assertEqual(len(result["plist_files"]), 1)

    def test_directory_scan_empty(self):
        result = apple_agent.directory_scan(str(self.root))
        self.assertEqual(result["total_swift_file_count"], 0)
        self.assertEqual(len(result["swift_files"]), 0)

    def test_directory_scan_detects_entitlements(self):
        (self.root / "App.entitlements").write_text("<xml></xml>")
        result = apple_agent.directory_scan(str(self.root))
        self.assertEqual(len(result["entitlement_files"]), 1)

    def test_directory_scan_detects_xcprivacy(self):
        (self.root / "PrivacyInfo.xcprivacy").write_text("<xml></xml>")
        result = apple_agent.directory_scan(str(self.root))
        self.assertEqual(len(result["xcprivacy_files"]), 1)


# ============================================================================
# Issue 02 — Deterministic Platform Analyzer Tests
# ============================================================================

class TestPermissionStringAnalyzer(unittest.TestCase):
    """Tests for Info.plist permission string review."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_camera_permission_with_avfoundation_import(self):
        """AVFoundation import without NSCameraUsageDescription should be flagged."""
        (self.root / "Camera.swift").write_text("import AVFoundation\nimport SwiftUI\n")
        # Info.plist without camera permission key
        import plistlib
        info_plist = {"CFBundleName": "TestApp", "CFBundleIdentifier": "com.test.app"}
        with open(self.root / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        result = apple_agent.analyze_permission_strings(str(self.root))
        self.assertGreater(len(result), 0, "Should find at least one finding")
        camera_findings = [f for f in result if f["missing_key"] == "NSCameraUsageDescription"]
        self.assertEqual(len(camera_findings), 1)
        self.assertEqual(camera_findings[0]["confidence"], "verified")
        self.assertEqual(camera_findings[0]["severity"], "error")
        self.assertEqual(camera_findings[0]["category"], "permission_strings")

    def test_no_finding_when_permission_present(self):
        """When Info.plist has the required key, no finding should be generated for it."""
        (self.root / "Camera.swift").write_text("import AVFoundation\n")
        import plistlib
        info_plist = {
            "CFBundleName": "TestApp",
            "NSCameraUsageDescription": "Need camera for photos",
        }
        with open(self.root / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        result = apple_agent.analyze_permission_strings(str(self.root))
        camera_findings = [f for f in result if f["missing_key"] == "NSCameraUsageDescription"]
        self.assertEqual(len(camera_findings), 0,
                         "Should NOT flag when permission key is present")

    def test_no_framework_no_findings(self):
        """No privacy-sensitive imports means no permission findings."""
        (self.root / "App.swift").write_text("import SwiftUI\nimport Foundation\n")
        import plistlib
        info_plist = {"CFBundleName": "TestApp"}
        with open(self.root / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        result = apple_agent.analyze_permission_strings(str(self.root))
        self.assertEqual(len(result), 0)

    def test_multiple_missing_permissions(self):
        """Multiple privacy-sensitive imports without their keys."""
        (self.root / "App.swift").write_text(
            "import AVFoundation\nimport CoreLocation\nimport Photos\n"
        )
        import plistlib
        info_plist = {"CFBundleName": "TestApp"}
        with open(self.root / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        result = apple_agent.analyze_permission_strings(str(self.root))
        self.assertGreaterEqual(len(result), 2)
        for f in result:
            self.assertEqual(f["confidence"], "verified")

    def test_no_plist_files_no_findings(self):
        """Without any .plist files, gracefully return empty."""
        (self.root / "App.swift").write_text("import AVFoundation\n")
        result = apple_agent.analyze_permission_strings(str(self.root))
        self.assertEqual(len(result), 0)


class TestEntitlementAnalyzer(unittest.TestCase):
    """Tests for entitlement file parsing and capability checks."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_push_notification_entitlement_detected(self):
        import plistlib
        ent_data = {"aps-environment": "development"}
        with open(self.root / "App.entitlements", "wb") as f:
            plistlib.dump(ent_data, f)

        result = apple_agent.analyze_entitlement_capabilities(str(self.root))
        self.assertGreater(len(result), 0)
        push_findings = [f for f in result if f["entitlement_key"] == "aps-environment"]
        self.assertEqual(len(push_findings), 1)
        self.assertEqual(push_findings[0]["confidence"], "verified")
        self.assertIn("Push notifications", push_findings[0]["entitlement_description"])

    def test_healthkit_entitlement_detected(self):
        import plistlib
        ent_data = {"com.apple.developer.healthkit": True}
        with open(self.root / "App.entitlements", "wb") as f:
            plistlib.dump(ent_data, f)

        result = apple_agent.analyze_entitlement_capabilities(str(self.root))
        health_findings = [f for f in result
                           if f["entitlement_key"] == "com.apple.developer.healthkit"]
        self.assertEqual(len(health_findings), 1)
        self.assertEqual(health_findings[0]["confidence"], "verified")

    def test_unknown_entitlement_flagged(self):
        import plistlib
        ent_data = {"com.example.custom-entitlement": "value"}
        with open(self.root / "App.entitlements", "wb") as f:
            plistlib.dump(ent_data, f)

        result = apple_agent.analyze_entitlement_capabilities(str(self.root))
        unknown = [f for f in result
                   if f["entitlement_key"] == "com.example.custom-entitlement"]
        self.assertEqual(len(unknown), 1)
        self.assertIn("not in known capability catalog", unknown[0]["message"])

    def test_empty_entitlements_no_findings(self):
        (self.root / "App.entitlements").write_text("")
        result = apple_agent.analyze_entitlement_capabilities(str(self.root))
        parse_errors = [f for f in result if f["severity"] == "warning"
                        and "Failed to parse" in f["message"]]
        self.assertEqual(len(parse_errors), 1)

    def test_no_entitlement_files_no_findings(self):
        result = apple_agent.analyze_entitlement_capabilities(str(self.root))
        self.assertEqual(len(result), 0)


class TestPrivacyManifestAnalyzer(unittest.TestCase):
    """Tests for PrivacyInfo.xcprivacy existence and required-reason API checks."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_privacy_manifest_with_sensitive_frameworks(self):
        (self.root / "App.swift").write_text("import AVFoundation\nimport Photos\n")
        result = apple_agent.analyze_privacy_manifest(str(self.root))
        self.assertGreater(len(result), 0)
        self.assertEqual(result[0]["category"], "privacy_manifest")
        self.assertEqual(result[0]["severity"], "error")
        self.assertEqual(result[0]["confidence"], "verified")
        self.assertIn("PrivacyInfo.xcprivacy is missing", result[0]["message"])

    def test_no_finding_without_sensitive_frameworks(self):
        (self.root / "App.swift").write_text("import SwiftUI\nimport Foundation\n")
        result = apple_agent.analyze_privacy_manifest(str(self.root))
        # No sensitive framework imports -> no PrivacyInfo.xcprivacy requirement
        missing = [f for f in result
                   if "PrivacyInfo.xcprivacy is missing" in f.get("message", "")]
        self.assertEqual(len(missing), 0)

    def test_privacy_manifest_present_and_parsed(self):
        import plistlib
        (self.root / "App.swift").write_text("import AVFoundation\n")
        manifest = {
            "NSPrivacyAccessedAPITypes": [
                {
                    "NSPrivacyAccessedAPIType":
                        "NSPrivacyAccessedAPICategoryUserDefaults",
                    "NSPrivacyAccessedAPITypeReasons": ["CA92.1"],
                },
            ],
        }
        with open(self.root / "PrivacyInfo.xcprivacy", "wb") as f:
            plistlib.dump(manifest, f)

        result = apple_agent.analyze_privacy_manifest(str(self.root))
        present = [f for f in result if "Privacy manifest found" in f.get("message", "")]
        self.assertEqual(len(present), 1)
        self.assertEqual(present[0]["confidence"], "verified")

    def test_privacy_manifest_parse_failure(self):
        (self.root / "App.swift").write_text("import AVFoundation\n")
        (self.root / "PrivacyInfo.xcprivacy").write_text("NOT VALID PLIST {{{")

        result = apple_agent.analyze_privacy_manifest(str(self.root))
        parse_errors = [f for f in result if "Failed to parse" in f.get("message", "")]
        self.assertEqual(len(parse_errors), 1)
        self.assertEqual(parse_errors[0]["confidence"], "verified")


class TestAssetCatalogAnalyzer(unittest.TestCase):
    """Tests for asset catalog sanity checks."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_asset_dir(self):
        xcassets = self.root / "Assets.xcassets"
        xcassets.mkdir()
        return xcassets

    def _make_appicon(self, xcassets):
        iconset = xcassets / "AppIcon.appiconset"
        iconset.mkdir()
        cj = {
            "images": [
                {"filename": "icon-60@2x.png", "idiom": "iphone", "scale": "2x",
                 "size": "60x60"},
                {"filename": "icon-60@3x.png", "idiom": "iphone", "scale": "3x",
                 "size": "60x60"},
            ],
            "info": {"author": "xcode", "version": 1},
        }
        (iconset / "Contents.json").write_text(json.dumps(cj))
        return iconset

    def _make_accent_color(self, xcassets):
        colorset = xcassets / "AccentColor.colorset"
        colorset.mkdir()
        cj = {
            "colors": [
                {
                    "color": {"color-space": "srgb",
                              "components": {"red": "0x00", "green": "0x7A",
                                             "blue": "0xFF", "alpha": "1.000"}},
                    "idiom": "universal",
                },
            ],
            "info": {"author": "xcode", "version": 1},
        }
        (colorset / "Contents.json").write_text(json.dumps(cj))
        return colorset

    def test_missing_app_icon_flagged(self):
        xcassets = self._make_asset_dir()
        # Create xcassets dir but no app icon
        (xcassets / "SomeImage.imageset").mkdir()

        result = apple_agent.analyze_asset_catalogs(str(self.root))
        icon_missing = [f for f in result
                        if "no AppIcon" in f.get("message", "")]
        self.assertEqual(len(icon_missing), 1)
        self.assertEqual(icon_missing[0]["confidence"], "verified")
        self.assertEqual(icon_missing[0]["severity"], "warning")

    def test_missing_accent_color_flagged(self):
        xcassets = self._make_asset_dir()
        self._make_appicon(xcassets)

        result = apple_agent.analyze_asset_catalogs(str(self.root))
        accent_missing = [f for f in result
                          if "no AccentColor" in f.get("message", "")]
        self.assertEqual(len(accent_missing), 1)
        self.assertEqual(accent_missing[0]["confidence"], "verified")

    def test_complete_asset_catalog_no_warnings(self):
        xcassets = self._make_asset_dir()
        self._make_appicon(xcassets)
        self._make_accent_color(xcassets)

        result = apple_agent.analyze_asset_catalogs(str(self.root))
        warnings = [f for f in result if f["severity"] == "warning"]
        self.assertEqual(len(warnings), 0,
                         "Complete catalog should have no warnings")

    def test_dark_mode_variant_detected(self):
        xcassets = self._make_asset_dir()
        self._make_appicon(xcassets)
        self._make_accent_color(xcassets)
        # Add an image with dark appearance variant
        imgset = xcassets / "Background.imageset"
        imgset.mkdir()
        cj = {
            "images": [
                {
                    "filename": "bg-light.png",
                    "idiom": "universal",
                },
                {
                    "appearances": [
                        {"appearance": "luminosity", "value": "dark"},
                    ],
                    "filename": "bg-dark.png",
                    "idiom": "universal",
                },
            ],
            "info": {"author": "xcode", "version": 1},
        }
        (imgset / "Contents.json").write_text(json.dumps(cj))

        result = apple_agent.analyze_asset_catalogs(str(self.root))
        dark_findings = [f for f in result
                         if "dark-mode" in f.get("message", "")]
        self.assertEqual(len(dark_findings), 1)

    def test_no_asset_catalogs_no_findings(self):
        result = apple_agent.analyze_asset_catalogs(str(self.root))
        self.assertEqual(len(result), 0)


class TestLocalizationAnalyzer(unittest.TestCase):
    """Tests for localization gap detection."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_hardcoded_strings_detected(self):
        (self.root / "ContentView.swift").write_text("""\
import SwiftUI
struct ContentView: View {
    var body: some View {
        Text("Welcome to the app")
        Button("Tap me please") { }
    }
}
""")
        result = apple_agent.analyze_localization_gaps(str(self.root))
        self.assertGreater(len(result), 0)
        self.assertEqual(result[0]["confidence"], "verified")
        self.assertEqual(result[0]["category"], "localization")
        self.assertGreater(result[0]["hardcoded_count"], 0)
        # No localization resources -> warning
        self.assertEqual(result[0]["severity"], "warning")

    def test_hardcoded_strings_with_localization_resources(self):
        (self.root / "ContentView.swift").write_text("""\
import SwiftUI
struct ContentView: View {
    var body: some View {
        Text("Hello World")
    }
}
""")
        # Add localization resources
        en_dir = self.root / "en.lproj"
        en_dir.mkdir()
        (en_dir / "Localizable.strings").write_text("")

        result = apple_agent.analyze_localization_gaps(str(self.root))
        # Should still detect hardcoded strings but severity is info
        hardcoded = [f for f in result if "hardcoded" in f.get("message", "").lower()]
        self.assertGreater(len(hardcoded), 0)
        self.assertEqual(hardcoded[0]["confidence"], "verified")
        self.assertTrue(hardcoded[0]["has_localization_resources"])

    def test_nslocalizedstring_detected_as_localized(self):
        (self.root / "ContentView.swift").write_text("""\
import SwiftUI
struct ContentView: View {
    var body: some View {
        Text(NSLocalizedString("greeting", comment: "Hello"))
    }
}
""")
        result = apple_agent.analyze_localization_gaps(str(self.root))
        # NSLocalizedString counts as localized usage, not hardcoded
        hardcoded = [f for f in result if "hardcoded" in f.get("message", "").lower()]
        if hardcoded:
            self.assertEqual(hardcoded[0]["localized_count"], 1)

    def test_no_swift_files_no_findings(self):
        result = apple_agent.analyze_localization_gaps(str(self.root))
        self.assertEqual(len(result), 0)

    def test_localization_resources_without_hardcoded_strings(self):
        en_dir = self.root / "en.lproj"
        en_dir.mkdir()
        (en_dir / "Localizable.strings").write_text('"key" = "value";')
        (self.root / "App.swift").write_text("import SwiftUI\n// no user-facing strings\n")

        result = apple_agent.analyze_localization_gaps(str(self.root))
        resources = [f for f in result
                     if "Localization resources present" in f.get("message", "")]
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["confidence"], "verified")


class TestPlatformAnalyzersInScan(unittest.TestCase):
    """Integration tests: verify platform_analysis appears in cmd_scan output."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_scan_includes_platform_analysis_key(self):
        (self.root / "App.swift").write_text("import SwiftUI\n")
        import plistlib
        info_plist = {"CFBundleName": "TestApp"}
        with open(self.root / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        result = apple_agent.cmd_scan(str(self.root))
        self.assertIn("platform_analysis", result["project"])
        pa = result["project"]["platform_analysis"]
        self.assertIn("findings", pa)
        self.assertIn("analyzer_summaries", pa)
        # Each analyzer should have a summary entry
        self.assertIn("permission_strings", pa["analyzer_summaries"])
        self.assertIn("entitlement_capabilities", pa["analyzer_summaries"])
        self.assertIn("privacy_manifest", pa["analyzer_summaries"])
        self.assertIn("asset_catalog", pa["analyzer_summaries"])
        self.assertIn("localization", pa["analyzer_summaries"])

    def test_scan_with_avfoundation_flags_missing_permission(self):
        (self.root / "App.swift").write_text("import AVFoundation\nimport SwiftUI\n")
        import plistlib
        info_plist = {"CFBundleName": "TestApp"}
        with open(self.root / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        result = apple_agent.cmd_scan(str(self.root))
        pa = result["project"]["platform_analysis"]
        permission_findings = [
            f for f in pa["findings"]
            if f["category"] == "permission_strings"
        ]
        self.assertGreater(len(permission_findings), 0)
        self.assertEqual(permission_findings[0]["confidence"], "verified")

    def test_all_platform_findings_have_verified_confidence(self):
        (self.root / "App.swift").write_text(
            "import AVFoundation\nimport Photos\nimport SwiftUI\n"
        )
        (self.root / "ContentView.swift").write_text("""\
import SwiftUI
struct ContentView: View {
    var body: some View {
        Text("Welcome to the app")
        Button("Click me") { }
    }
}
""")
        import plistlib
        info_plist = {"CFBundleName": "TestApp"}
        with open(self.root / "Info.plist", "wb") as f:
            plistlib.dump(info_plist, f)

        # Add entitlement file
        ent_data = {"aps-environment": "development"}
        with open(self.root / "App.entitlements", "wb") as f:
            plistlib.dump(ent_data, f)

        # Add asset catalog without app icon
        xcassets = self.root / "Assets.xcassets"
        xcassets.mkdir()

        result = apple_agent.cmd_scan(str(self.root))
        pa = result["project"]["platform_analysis"]
        self.assertGreater(len(pa["findings"]), 0,
                           "Should have platform analysis findings")
        for finding in pa["findings"]:
            self.assertEqual(
                finding["confidence"], "verified",
                f"Finding '{finding.get('message', '')[:60]}...' "
                f"should have confidence='verified'"
            )


# ============================================================================
# Issue 03 — Swift Heuristic Scanner Tests
# ============================================================================


class TestHeuristicScannerBase(unittest.TestCase):
    """Base class with helpers for heuristic scanner tests."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_swift(self, name, content):
        """Write a .swift file and return its relative path."""
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return str(name)

    def _scan(self):
        """Run analyze_swift_files and return findings."""
        return apple_agent.analyze_swift_files(str(self.root))

    def _findings_by_id(self, results, finding_id):
        """Filter heuristics list by finding_id."""
        return [f for f in results["heuristics"] if f["finding_id"] == finding_id]

    def _assert_all_have_confidence(self, heuristics):
        """Verify every heuristic finding has confidence field set to heuristic or high_confidence_heuristic."""
        valid = {"heuristic", "high_confidence_heuristic"}
        for f in heuristics:
            self.assertIn("confidence", f, f"Missing confidence in: {f.get('finding_id', '?')}")
            self.assertIn(f["confidence"], valid,
                          f"Bad confidence '{f['confidence']}' in {f.get('finding_id', '?')}")


class TestImportsAndFrameworkDetection(TestHeuristicScannerBase):
    """Tests for SwiftUI/UIKit/AppKit import and base-class detection."""

    def test_swiftui_import_detected(self):
        self._write_swift("App.swift", "import SwiftUI\nstruct App: View { var body: some View { EmptyView() } }")
        results = self._scan()
        found = self._findings_by_id(results, "import_swiftui")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["confidence"], "high_confidence_heuristic")
        self.assertEqual(found[0]["category"], "framework_import")

    def test_uikit_import_detected(self):
        self._write_swift("VC.swift", "import UIKit\nclass VC: UIViewController { }")
        results = self._scan()
        found = self._findings_by_id(results, "import_uikit")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["confidence"], "high_confidence_heuristic")

    def test_appkit_import_detected(self):
        self._write_swift("Mac.swift", "import AppKit\nclass MacView: NSView { }")
        results = self._scan()
        found = self._findings_by_id(results, "import_appkit")
        self.assertEqual(len(found), 1)

    def test_mixed_swiftui_uikit_detected(self):
        self._write_swift("Mixed.swift", "import SwiftUI\nimport UIKit\nstruct Host: UIViewRepresentable { }")
        results = self._scan()
        sw = self._findings_by_id(results, "import_swiftui")
        uk = self._findings_by_id(results, "import_uikit")
        self.assertEqual(len(sw), 1)
        self.assertEqual(len(uk), 1)
        self.assertEqual(results["summary"]["swiftui_files"], 1)
        self.assertEqual(results["summary"]["uikit_files"], 1)

    def test_combine_import_detected(self):
        self._write_swift("VM.swift", "import Combine\nclass VM: ObservableObject { }")
        results = self._scan()
        found = self._findings_by_id(results, "import_combine")
        self.assertEqual(len(found), 1)

    def test_swiftdata_import_detected(self):
        self._write_swift("Model.swift", "import SwiftData\n@Model class Item { }")
        results = self._scan()
        found = self._findings_by_id(results, "import_swiftdata")
        self.assertEqual(len(found), 1)

    def test_coredata_import_detected(self):
        self._write_swift("Core.swift", "import CoreData\nclass Stack { }")
        results = self._scan()
        found = self._findings_by_id(results, "import_coredata")
        self.assertEqual(len(found), 1)

    def test_import_not_matched_in_comment(self):
        """import in a comment should not be flagged."""
        self._write_swift("Comments.swift", "// import SwiftUI\n/* import UIKit */\nstruct X { }")
        results = self._scan()
        sw = self._findings_by_id(results, "import_swiftui")
        uk = self._findings_by_id(results, "import_uikit")
        self.assertEqual(len(sw), 0, "Import in line comment should not match")
        self.assertEqual(len(uk), 0, "Import in block comment should not match")


class TestBaseClassDetection(TestHeuristicScannerBase):
    """Tests for SwiftUI View struct, UIViewController, App protocol detection."""

    def test_swiftui_view_struct_detected(self):
        self._write_swift("Content.swift", "import SwiftUI\nstruct ContentView: View {\n  var body: some View { Text(\"Hi\") }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "swiftui_view_struct")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["confidence"], "high_confidence_heuristic")
        self.assertEqual(found[0]["type_name"], "ContentView")

    def test_uikit_viewcontroller_detected(self):
        self._write_swift("VC.swift", "import UIKit\nclass MyViewController: UIViewController { }")
        results = self._scan()
        found = self._findings_by_id(results, "uikit_viewcontroller")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["type_name"], "MyViewController")

    def test_uikit_uiview_detected(self):
        self._write_swift("View.swift", "import UIKit\nclass CustomView: UIView { }")
        results = self._scan()
        found = self._findings_by_id(results, "uikit_uiview")
        self.assertEqual(len(found), 1)

    def test_swiftui_app_struct_detected(self):
        self._write_swift("Main.swift", "import SwiftUI\n@main struct MyApp: App {\n  var body: some Scene { WindowGroup { ContentView() } }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "swiftui_app")
        self.assertEqual(len(found), 1)

    def test_uikit_app_delegate_detected(self):
        self._write_swift("Delegate.swift", "import UIKit\nclass AppDelegate: UIApplicationDelegate { }")
        results = self._scan()
        found = self._findings_by_id(results, "uikit_app_delegate")
        self.assertEqual(len(found), 1)

    def test_appkit_viewcontroller_detected(self):
        self._write_swift("MacVC.swift", "import AppKit\nclass MacVC: NSViewController { }")
        results = self._scan()
        found = self._findings_by_id(results, "appkit_viewcontroller")
        self.assertEqual(len(found), 1)

    def test_swiftui_vs_uikit_distinction(self):
        """SwiftUI and UIKit projects are distinguished by imports and superclass usage."""
        self._write_swift("SwiftUIView.swift", "import SwiftUI\nstruct MyView: View { var body: some View { EmptyView() } }")
        self._write_swift("UIKitView.swift", "import UIKit\nclass MyVC: UIViewController { }")
        results = self._scan()
        # Both should be detected
        sv = self._findings_by_id(results, "swiftui_view_struct")
        uv = self._findings_by_id(results, "uikit_viewcontroller")
        self.assertEqual(len(sv), 1)
        self.assertEqual(len(uv), 1)
        # Summary counts
        self.assertEqual(results["summary"]["swiftui_files"], 1)
        self.assertEqual(results["summary"]["uikit_files"], 1)


class TestPropertyWrapperDetection(TestHeuristicScannerBase):
    """Tests for @StateObject, @ObservedObject, @EnvironmentObject, @State, @Binding."""

    def test_state_object_detected(self):
        self._write_swift("VM.swift", "import SwiftUI\nclass MyVM: ObservableObject { }\nstruct V: View {\n  @StateObject var vm = MyVM()\n  var body: some View { EmptyView() }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "state_object")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["confidence"], "high_confidence_heuristic")
        self.assertEqual(found[0]["property_name"], "vm")

    def test_observed_object_detected(self):
        self._write_swift("Child.swift", "import SwiftUI\nstruct Child: View {\n  @ObservedObject var parent: ParentVM\n  var body: some View { EmptyView() }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "observed_object")
        self.assertEqual(len(found), 1)

    def test_environment_object_detected(self):
        self._write_swift("Deep.swift", "import SwiftUI\nstruct Deep: View {\n  @EnvironmentObject var settings: AppSettings\n  var body: some View { EmptyView() }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "environment_object")
        self.assertEqual(len(found), 1)

    def test_state_property_detected(self):
        self._write_swift("Toggle.swift", "import SwiftUI\nstruct Toggle: View {\n  @State private var isOn = false\n  var body: some View { EmptyView() }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "state_property")
        self.assertEqual(len(found), 1)
        self.assertEqual(results["summary"]["total_state"], 1)

    def test_binding_property_detected(self):
        self._write_swift("Slider.swift", "import SwiftUI\nstruct SliderView: View {\n  @Binding var value: Double\n  var body: some View { EmptyView() }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "binding_property")
        self.assertEqual(len(found), 1)
        self.assertEqual(results["summary"]["total_bindings"], 1)

    def test_published_property_detected(self):
        self._write_swift("Model.swift", "import Combine\nclass Model: ObservableObject {\n  @Published var name: String = \"\"\n}")
        results = self._scan()
        found = self._findings_by_id(results, "published_property")
        self.assertEqual(len(found), 1)

    def test_app_storage_detected(self):
        self._write_swift("Settings.swift", "import SwiftUI\nstruct Settings: View {\n  @AppStorage(\"theme\") var theme = \"light\"\n  var body: some View { EmptyView() }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "app_storage")
        self.assertEqual(len(found), 1)

    def test_multiple_property_wrappers_counted(self):
        self._write_swift("Complex.swift", """\
import SwiftUI
struct Complex: View {
  @StateObject var vm = MyVM()
  @State private var text = ""
  @Binding var isPresented: Bool
  @ObservedObject var parent: ParentVM
  @EnvironmentObject var settings: AppSettings
  var body: some View { EmptyView() }
}
""")
        results = self._scan()
        self.assertEqual(results["summary"]["total_state_objects"], 1)
        self.assertEqual(results["summary"]["total_observed_objects"], 1)
        self.assertEqual(results["summary"]["total_environment_objects"], 1)
        self.assertEqual(results["summary"]["total_state"], 1)
        self.assertEqual(results["summary"]["total_bindings"], 1)


class TestViewBodyMetrics(TestHeuristicScannerBase):
    """Tests for view body size and stack depth via brace counting."""

    def test_view_body_size_measured(self):
        code = "import SwiftUI\nstruct V: View {\n  var body: some View {\n" + "    Text(\"line\")\n" * 10 + "  }\n}"
        self._write_swift("V.swift", code)
        results = self._scan()
        found = self._findings_by_id(results, "view_body_size")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["confidence"], "heuristic")
        self.assertIn("body_size_lines", found[0])
        self.assertGreater(found[0]["body_size_lines"], 5)

    def test_large_view_body_flagged(self):
        """Large view bodies (>80 lines) should be flagged."""
        code = "import SwiftUI\nstruct Big: View {\n  var body: some View {\n" + "    Text(\"line\")\n" * 85 + "  }\n}"
        self._write_swift("Big.swift", code)
        results = self._scan()
        large = self._findings_by_id(results, "large_view_body")
        self.assertEqual(len(large), 1, "Large body should be flagged")
        self.assertGreater(large[0]["body_size_lines"], 80)

    def test_small_body_not_flagged_as_large(self):
        code = "import SwiftUI\nstruct Small: View {\n  var body: some View {\n" + "    Text(\"line\")\n" * 5 + "  }\n}"
        self._write_swift("Small.swift", code)
        results = self._scan()
        large = self._findings_by_id(results, "large_view_body")
        self.assertEqual(len(large), 0, "Small body should not be flagged as large")

    def test_stack_depth_measured(self):
        self._write_swift("Stacks.swift", """\
import SwiftUI
struct Stacks: View {
  var body: some View {
    VStack {
      HStack {
        VStack {
          Text("Nested")
        }
      }
    }
  }
}
""")
        results = self._scan()
        depth_found = self._findings_by_id(results, "stack_depth")
        self.assertEqual(len(depth_found), 1)
        self.assertGreaterEqual(depth_found[0]["max_stack_depth"], 2)

    def test_deep_stack_nesting_flagged(self):
        """Deeply nested stacks (>3) should be flagged."""
        self._write_swift("DeepStacks.swift", """\
import SwiftUI
struct DeepStacks: View {
  var body: some View {
    VStack {
      HStack {
        VStack {
          HStack {
            VStack {
              Text("Very deep")
            }
          }
        }
      }
    }
  }
}
""")
        results = self._scan()
        deep = self._findings_by_id(results, "deep_stack_nesting")
        self.assertEqual(len(deep), 1, "Deep stack nesting should be flagged")

    def test_no_stacks_in_body(self):
        self._write_swift("NoStacks.swift", """\
import SwiftUI
struct NoStacks: View {
  var body: some View {
    Text("Just text")
  }
}
""")
        results = self._scan()
        depth = self._findings_by_id(results, "stack_depth")
        self.assertEqual(len(depth), 0, "No stacks means no depth finding")


class TestHardcodedUIPatterns(TestHeuristicScannerBase):
    """Tests for flagging hardcoded colors, fonts, frames, and spacings."""

    def test_hardcoded_foreground_color_detected(self):
        self._write_swift("Color.swift", "import SwiftUI\nstruct C: View {\n  var body: some View {\n    Text(\"Hi\").foregroundColor(.blue)\n  }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "hardcoded_foreground_color")
        self.assertGreaterEqual(len(found), 1)
        self.assertEqual(found[0]["confidence"], "heuristic")

    def test_hardcoded_background_detected(self):
        self._write_swift("Bg.swift", "import SwiftUI\nstruct B: View {\n  var body: some View {\n    Text(\"Hi\").background(.red)\n  }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "hardcoded_background")
        self.assertGreaterEqual(len(found), 1)

    def test_hardcoded_font_style_detected(self):
        self._write_swift("Font.swift", "import SwiftUI\nstruct F: View {\n  var body: some View {\n    Text(\"Hi\").font(.title)\n  }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "hardcoded_font_style")
        self.assertGreaterEqual(len(found), 1)

    def test_hardcoded_system_font_detected(self):
        self._write_swift("SysFont.swift", "import SwiftUI\nstruct SF: View {\n  var body: some View {\n    Text(\"Hi\").font(.system(size: 14))\n  }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "hardcoded_system_font")
        self.assertGreaterEqual(len(found), 1)

    def test_hardcoded_frame_width_detected(self):
        self._write_swift("Frame.swift", "import SwiftUI\nstruct Fr: View {\n  var body: some View {\n    Text(\"Hi\").frame(width: 200)\n  }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "hardcoded_frame_width")
        self.assertGreaterEqual(len(found), 1)

    def test_hardcoded_frame_height_detected(self):
        self._write_swift("Height.swift", "import SwiftUI\nstruct Ht: View {\n  var body: some View {\n    Text(\"Hi\").frame(height: 44)\n  }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "hardcoded_frame_height")
        self.assertGreaterEqual(len(found), 1)

    def test_hardcoded_numeric_padding_detected(self):
        self._write_swift("Pad.swift", "import SwiftUI\nstruct Pd: View {\n  var body: some View {\n    Text(\"Hi\").padding(16)\n  }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "hardcoded_padding_numeric")
        self.assertGreaterEqual(len(found), 1)

    def test_hardcoded_hstack_spacing_detected(self):
        self._write_swift("HSpacing.swift", "import SwiftUI\nstruct HS: View {\n  var body: some View {\n    HStack(spacing: 12) { Text(\"A\"); Text(\"B\") }\n  }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "hardcoded_hstack_spacing")
        self.assertGreaterEqual(len(found), 1)

    def test_hardcoded_vstack_spacing_detected(self):
        self._write_swift("VSpacing.swift", "import SwiftUI\nstruct VS: View {\n  var body: some View {\n    VStack(spacing: 8) { Text(\"A\"); Text(\"B\") }\n  }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "hardcoded_vstack_spacing")
        self.assertGreaterEqual(len(found), 1)

    def test_hardcoded_hex_color_detected(self):
        self._write_swift("Hex.swift", "import SwiftUI\nstruct Hx: View {\n  var body: some View {\n    Color(\"#FF5733\")\n  }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "hardcoded_color_hex")
        self.assertGreaterEqual(len(found), 1)

    def test_hardcoded_uifont_detected(self):
        self._write_swift("UIF.swift", "import UIKit\nclass V: UIViewController {\n  override func viewDidLoad() {\n    label.font = UIFont.systemFont(ofSize: 14)\n  }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "hardcoded_uifont")
        self.assertGreaterEqual(len(found), 1)

    def test_multiple_hardcoded_patterns_in_one_file(self):
        self._write_swift("Many.swift", """\
import SwiftUI
struct Many: View {
  var body: some View {
    VStack(spacing: 8) {
      Text("A").foregroundColor(.blue).font(.title)
      Text("B").padding(16).frame(width: 200)
    }
  }
}
""")
        results = self._scan()
        hardcoded = [f for f in results["heuristics"] if f["category"] == "hardcoded_ui"]
        self.assertGreaterEqual(len(hardcoded), 3, "Should find multiple hardcoded patterns")


class TestTaskInViews(TestHeuristicScannerBase):
    """Tests for Task { ... } detection in views."""

    def test_task_closure_detected(self):
        self._write_swift("TaskView.swift", """\
import SwiftUI
struct TaskView: View {
  @State var data: String = ""
  var body: some View {
    Text(data)
      .onAppear {
        Task {
          data = await fetchData()
        }
      }
  }
}
""")
        results = self._scan()
        found = self._findings_by_id(results, "task_closure")
        self.assertGreaterEqual(len(found), 1)
        self.assertEqual(found[0]["confidence"], "high_confidence_heuristic")

    def test_task_modifier_detected(self):
        self._write_swift("TaskMod.swift", """\
import SwiftUI
struct TaskMod: View {
  var body: some View {
    Text("Hello")
      .task {
        await loadData()
      }
  }
}
""")
        results = self._scan()
        found = self._findings_by_id(results, "task_modifier")
        self.assertEqual(len(found), 1)

    def test_no_task_in_file(self):
        self._write_swift("NoTask.swift", "import SwiftUI\nstruct V: View {\n  var body: some View { Text(\"Hi\") }\n}")
        results = self._scan()
        found = self._findings_by_id(results, "task_closure")
        self.assertEqual(len(found), 0)


class TestImageAccessibility(TestHeuristicScannerBase):
    """Tests for Image(systemName:) accessibility label detection."""

    def test_image_without_label_flagged(self):
        self._write_swift("NoLabel.swift", """\
import SwiftUI
struct NoLabel: View {
  var body: some View {
    Image(systemName: "star.fill")
  }
}
""")
        results = self._scan()
        found = self._findings_by_id(results, "image_without_accessibility_label")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["confidence"], "heuristic")

    def test_image_with_label_not_flagged(self):
        self._write_swift("Label.swift", """\
import SwiftUI
struct Labeled: View {
  var body: some View {
    Image(systemName: "star.fill")
      .accessibilityLabel("Favorite")
  }
}
""")
        results = self._scan()
        without = self._findings_by_id(results, "image_without_accessibility_label")
        self.assertEqual(len(without), 0, "Image with label should not be flagged")
        with_label = self._findings_by_id(results, "image_with_accessibility_label")
        self.assertEqual(len(with_label), 1)

    def test_image_accessibility_hidden(self):
        self._write_swift("Hidden.swift", """\
import SwiftUI
struct Hidden: View {
  var body: some View {
    Image(systemName: "star.fill")
      .accessibilityHidden(true)
  }
}
""")
        results = self._scan()
        hidden = self._findings_by_id(results, "image_accessibility_hidden")
        self.assertEqual(len(hidden), 1)

    def test_multiple_images_mixed_accessibility(self):
        """Images in separate files to avoid window overlap across type boundaries."""
        self._write_swift("NoLabel.swift", """\
import SwiftUI
struct NoLabelView: View {
  var body: some View {
    Image(systemName: "star")
  }
}
""")
        self._write_swift("Labeled.swift", """\
import SwiftUI
struct LabeledView: View {
  var body: some View {
    Image(systemName: "heart.fill")
      .accessibilityLabel("Like")
  }
}
""")
        results = self._scan()
        without = self._findings_by_id(results, "image_without_accessibility_label")
        with_l = self._findings_by_id(results, "image_with_accessibility_label")
        self.assertEqual(len(without), 1, "Star image should be flagged without label")
        self.assertEqual(len(with_l), 1, "Heart image should have label")


class TestRiskMarkers(TestHeuristicScannerBase):
    """Tests for force unwraps, try!, fatalError, TODO/FIXME."""

    def test_force_unwrap_detected(self):
        self._write_swift("Force.swift", "let x: String! = nil\nlet y = x!.count\n")
        results = self._scan()
        found = self._findings_by_id(results, "force_unwrap")
        self.assertGreaterEqual(len(found), 1)
        self.assertEqual(found[0]["confidence"], "high_confidence_heuristic")

    def test_not_equals_not_flagged_as_unwrap(self):
        """!= should not be flagged as force unwrap."""
        self._write_swift("NotEq.swift", "if x != nil { print(x) }\n")
        results = self._scan()
        found = self._findings_by_id(results, "force_unwrap")
        self.assertEqual(len(found), 0, "!= should not be flagged")

    def test_force_try_detected(self):
        self._write_swift("ForceTry.swift", "let data = try! Data(contentsOf: url)\n")
        results = self._scan()
        found = self._findings_by_id(results, "force_try")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["confidence"], "high_confidence_heuristic")

    def test_fatal_error_detected(self):
        self._write_swift("Fatal.swift", "func crash() { fatalError(\"Not implemented\") }\n")
        results = self._scan()
        found = self._findings_by_id(results, "fatal_error_call")
        self.assertEqual(len(found), 1)

    def test_precondition_failure_detected(self):
        self._write_swift("Precond.swift", "func check() { preconditionFailure(\"Bad state\") }\n")
        results = self._scan()
        found = self._findings_by_id(results, "fatal_error_call")
        self.assertGreaterEqual(len(found), 1)

    def test_todo_marker_detected(self):
        self._write_swift("Todo.swift", "// TODO: implement this later\nfunc stub() { }\n")
        results = self._scan()
        found = [f for f in self._findings_by_id(results, "todo_fixme_marker")
                 if f["match"].startswith("TODO")]
        self.assertGreaterEqual(len(found), 1)
        self.assertGreater(results["summary"]["total_todos"], 0)

    def test_fixme_marker_detected(self):
        self._write_swift("Fixme.swift", "// FIXME: this is broken\nfunc broken() { }\n")
        results = self._scan()
        found = [f for f in self._findings_by_id(results, "todo_fixme_marker")
                 if f["match"].startswith("FIXME")]
        self.assertGreaterEqual(len(found), 1)
        self.assertGreater(results["summary"]["total_fixmes"], 0)

    def test_hack_marker_detected(self):
        self._write_swift("Hack.swift", "// HACK: workaround for iOS 15\n")
        results = self._scan()
        found = self._findings_by_id(results, "todo_fixme_marker")
        self.assertGreaterEqual(len(found), 1)


class TestStoreKitDetection(TestHeuristicScannerBase):
    """Tests for StoreKit import and API call patterns."""

    def test_storekit_import_detected(self):
        self._write_swift("Store.swift", "import StoreKit\nimport SwiftUI\n")
        results = self._scan()
        found = self._findings_by_id(results, "storekit_import")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["confidence"], "high_confidence_heuristic")
        self.assertTrue(results["summary"]["storekit_detected"])

    def test_storekit_product_definition_detected(self):
        self._write_swift("Products.swift", "import StoreKit\nlet p = Product.consumable\n")
        results = self._scan()
        found = self._findings_by_id(results, "storekit_product_def")
        self.assertGreaterEqual(len(found), 1)

    def test_storekit_purchase_detected(self):
        self._write_swift("Buy.swift", "import StoreKit\nfunc buy() { product.purchase() }\n")
        results = self._scan()
        found = self._findings_by_id(results, "storekit_purchase")
        self.assertGreaterEqual(len(found), 1)

    def test_storekit_restore_detected(self):
        self._write_swift("Restore.swift", "import StoreKit\nfunc restore() { await restorePurchases() }\n")
        results = self._scan()
        found = self._findings_by_id(results, "storekit_restore")
        self.assertGreaterEqual(len(found), 1)

    def test_subscription_store_view_detected(self):
        self._write_swift("Subs.swift", "import StoreKit\nimport SwiftUI\nstruct Subs: View {\n  var body: some View {\n    SubscriptionStoreView(groupID: \"premium\")\n  }\n}\n")
        results = self._scan()
        found = self._findings_by_id(results, "storekit_subscription_view")
        self.assertGreaterEqual(len(found), 1)

    def test_storekit_transaction_api_detected(self):
        self._write_swift("Tx.swift", "import StoreKit\nfor await result in Transaction.updates { }\n")
        results = self._scan()
        found = self._findings_by_id(results, "storekit_transaction")
        self.assertGreaterEqual(len(found), 1)

    def test_storekit_review_request_detected(self):
        self._write_swift("Review.swift", "import StoreKit\nfunc ask() { requestReview() }\n")
        results = self._scan()
        found = self._findings_by_id(results, "storekit_review_request")
        self.assertGreaterEqual(len(found), 1)

    def test_no_storekit_without_import(self):
        self._write_swift("NoSK.swift", "import SwiftUI\nstruct V: View { var body: some View { EmptyView() } }\n")
        results = self._scan()
        self.assertFalse(results["summary"]["storekit_detected"])


class TestTypeSuffixes(TestHeuristicScannerBase):
    """Tests for type-name suffix counting."""

    def test_view_model_suffix_detected(self):
        self._write_swift("LoginVM.swift", "class LoginViewModel: ObservableObject { }\n")
        results = self._scan()
        found = self._findings_by_id(results, "view_model_suffix")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["confidence"], "heuristic")
        self.assertEqual(found[0]["suffix"], "ViewModel")

    def test_service_suffix_detected(self):
        self._write_swift("API.swift", "class APIService { }\n")
        results = self._scan()
        found = self._findings_by_id(results, "service_suffix")
        self.assertEqual(len(found), 1)

    def test_manager_suffix_detected(self):
        self._write_swift("Cache.swift", "class CacheManager { }\n")
        results = self._scan()
        found = self._findings_by_id(results, "manager_suffix")
        self.assertEqual(len(found), 1)

    def test_store_suffix_detected(self):
        self._write_swift("State.swift", "class AppStore: ObservableObject { }\n")
        results = self._scan()
        found = self._findings_by_id(results, "store_suffix")
        self.assertEqual(len(found), 1)

    def test_router_suffix_detected(self):
        self._write_swift("Nav.swift", "class AppRouter: ObservableObject { }\n")
        results = self._scan()
        found = self._findings_by_id(results, "router_suffix")
        self.assertEqual(len(found), 1)

    def test_repository_suffix_detected(self):
        self._write_swift("Repo.swift", "class UserRepository { }\n")
        results = self._scan()
        found = self._findings_by_id(results, "repository_suffix")
        self.assertEqual(len(found), 1)

    def test_multiple_suffixes_counted(self):
        self._write_swift("AllSuffixes.swift", """\
class LoginViewModel { }
class APIService { }
class CacheManager { }
class AppStore { }
class AppRouter { }
class UserRepository { }
class AuthInteractor { }
""")
        results = self._scan()
        self.assertEqual(results["summary"]["total_view_models"], 1)
        self.assertEqual(results["summary"]["total_services"], 1)
        self.assertEqual(results["summary"]["total_managers"], 1)
        self.assertEqual(results["summary"]["total_stores"], 1)
        self.assertEqual(results["summary"]["total_routers"], 1)

    def test_no_suffix_in_regular_types(self):
        self._write_swift("Plain.swift", "class User { }\nstruct Point { }\nenum Color { }\nprotocol Drawable { }\n")
        results = self._scan()
        arch = [f for f in results["heuristics"] if f["category"] == "architecture_signal"]
        self.assertEqual(len(arch), 0, "Regular types should not match suffixes")


class TestHeuristicConfidenceAndSummary(TestHeuristicScannerBase):
    """Tests for confidence labeling and summary correctness."""

    def test_all_findings_have_heuristic_confidence(self):
        """Every heuristic finding must carry confidence: 'heuristic' or 'high_confidence_heuristic'."""
        self._write_swift("Full.swift", """\
import SwiftUI
import StoreKit

class AppViewModel: ObservableObject {
    @Published var items: [String] = []

    func load() {
        Task {
            let data = try! await fetch()
            items = data!
        }
    }

    func crash() { fatalError("TODO: fix me") }
}

struct ContentView: View {
    @StateObject var vm = AppViewModel()
    @State private var text = ""
    @Binding var show: Bool

    var body: some View {
        VStack(spacing: 8) {
            Text("Hello").foregroundColor(.blue).font(.title)
            Image(systemName: "star")
            Text(text).frame(width: 200)
        }
        .task { await vm.load() }
    }
}
""")
        results = self._scan()
        self.assertGreater(len(results["heuristics"]), 0, "Should have heuristic findings")
        self._assert_all_have_confidence(results["heuristics"])

    def test_files_scanned_count(self):
        self._write_swift("A.swift", "import SwiftUI\n")
        self._write_swift("B.swift", "import UIKit\n")
        self._write_swift("C.swift", "import Foundation\n")
        results = self._scan()
        self.assertEqual(results["files_scanned"], 3)

    def test_swift_heuristics_in_scan_output(self):
        self._write_swift("App.swift", "import SwiftUI\nstruct AppView: View { var body: some View { Text(\"Hi\") } }")
        result = apple_agent.cmd_scan(str(self.root))
        self.assertIn("swift_heuristics", result["project"])
        sh = result["project"]["swift_heuristics"]
        self.assertIn("heuristics", sh)
        self.assertIn("summary", sh)
        self.assertIn("files_scanned", sh)
        # All heuristics in scan output should have confidence
        self._assert_all_have_confidence(sh["heuristics"])

    def test_heuristic_confidence_distinction(self):
        """Verified that imports/hardcoded correctly use heuristic vs high_confidence_heuristic."""
        self._write_swift("Conf.swift", """\
import SwiftUI
struct V: View {
    @State var name = ""
    var body: some View {
        Text(name).foregroundColor(.red).frame(width: 100)
        Image(systemName: "star")
    }
}
""")
        results = self._scan()
        # import_swiftui should be high_confidence_heuristic
        imp = self._findings_by_id(results, "import_swiftui")
        self.assertEqual(imp[0]["confidence"], "high_confidence_heuristic")
        # hardcoded patterns should be heuristic
        hc = self._findings_by_id(results, "hardcoded_foreground_color")
        self.assertGreater(len(hc), 0)
        self.assertEqual(hc[0]["confidence"], "heuristic")
        # Image without label should be heuristic
        img = self._findings_by_id(results, "image_without_accessibility_label")
        self.assertEqual(img[0]["confidence"], "heuristic")
        # @State should be high_confidence_heuristic
        st = self._findings_by_id(results, "state_property")
        self.assertEqual(st[0]["confidence"], "high_confidence_heuristic")


if __name__ == "__main__":
    unittest.main()

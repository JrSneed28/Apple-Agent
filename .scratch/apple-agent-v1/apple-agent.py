#!/usr/bin/env python3
"""Apple Project Agent CLI - v1

Single-file, standard-library-only CLI for deterministic static analysis
of Apple platform projects (iOS, macOS, watchOS, tvOS, visionOS).

Subcommands: scan, audit, shipcheck, validate
"""

import argparse
import json
import os
import sys
import re
import plistlib
import platform
import hashlib
from pathlib import Path
from xml.etree import ElementTree


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0"

PRODUCT_TYPE_MAP = {
    "com.apple.product-type.application": "application",
    "com.apple.product-type.application.watchapp": "watchapp",
    "com.apple.product-type.application.watchapp2": "watchapp2",
    "com.apple.product-type.watchkit2-extension": "watchkit2-extension",
    "com.apple.product-type.application.messages": "messages-app",
    "com.apple.product-type.app-extension": "app-extension",
    "com.apple.product-type.tool": "tool",
    "com.apple.product-type.library.static": "static-library",
    "com.apple.product-type.library.dynamic": "dynamic-library",
    "com.apple.product-type.framework": "framework",
    "com.apple.product-type.bundle": "bundle",
    "com.apple.product-type.bundle.unit-test": "unit-test",
    "com.apple.product-type.bundle.ui-testing": "ui-test",
    "com.apple.product-type.app-extension.intents-service": "intents-extension",
    "com.apple.product-type.xcode-extension": "xcode-extension",
}


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

def detect_environment():
    """Return structured info about the current runtime environment."""
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform_machine": platform.machine(),
        "is_macos": platform.system() == "Darwin",
    }


# ---------------------------------------------------------------------------
# Project type detection
# ---------------------------------------------------------------------------

def detect_project_type(root_path):
    """Detect the Apple project type from the given root directory.

    Returns a dict with 'type' and 'details'.
    """
    root = Path(root_path).resolve()
    if not root.is_dir():
        return {"type": "invalid", "details": "Root path is not a directory"}

    # Check for SPM
    package_swift = root / "Package.swift"
    if package_swift.is_file():
        return {"type": "spm", "details": "Swift Package Manager project"}

    # Check for Xcode project
    xcodeproj_files = list(root.glob("*.xcodeproj"))
    if xcodeproj_files:
        return {
            "type": "xcode",
            "details": "Xcode project",
            "xcodeproj_paths": [str(p.relative_to(root)) for p in xcodeproj_files],
        }

    # Check for Xcode workspace
    xcworkspace_files = list(root.glob("*.xcworkspace"))
    if xcworkspace_files:
        return {
            "type": "xcode_workspace",
            "details": "Xcode workspace (limited support in v1)",
            "xcworkspace_paths": [str(p.relative_to(root)) for p in xcworkspace_files],
        }

    # Flat directory fallback
    swift_files = list(root.rglob("*.swift"))
    return {
        "type": "flat",
        "details": "Flat directory (no Package.swift or .xcodeproj found)",
        "swift_file_count": len(swift_files),
    }


# ---------------------------------------------------------------------------
# Minimal project.pbxproj lexer
# ---------------------------------------------------------------------------

def lex_pbxproj(filepath):
    """Minimal lexer for project.pbxproj files.

    Extracts PBXNativeTarget names, productType, buildSettings, and
    build-phase hints. Returns a dict of extracted data and warnings.
    Never crashes - falls back gracefully on any parse error.
    """
    result = {
        "targets": [],
        "warnings": [],
        "parse_success": True,
    }

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        result["parse_success"] = False
        result["warnings"].append(f"Failed to read pbxproj: {e}")
        return result

    if not content.strip():
        result["parse_success"] = False
        result["warnings"].append("Empty pbxproj file")
        return result

    # Quick structural check: valid pbxproj files contain at least one
    # of these pbxproj-typical markers
    has_isa = "isa =" in content
    has_section = "/* Begin" in content and "/* End" in content
    has_objects = "objects =" in content
    if not (has_isa or has_section or has_objects):
        result["parse_success"] = False
        result["warnings"].append("Content does not appear to be a valid pbxproj (no structural markers found)")
        return result

    try:
        targets = _extract_native_targets(content)
        result["targets"] = targets
    except Exception as e:
        result["parse_success"] = False
        result["warnings"].append(f"Lexer error: {e}")

    return result


def _extract_native_targets(content):
    """Extract PBXNativeTarget entries from pbxproj content."""
    targets = []

    # Find the PBXNativeTarget section
    section_pattern = re.compile(
        r"/\*\s*Begin PBXNativeTarget section\s*\*/(.*?)/\*\s*End PBXNativeTarget section\s*\*/",
        re.DOTALL,
    )
    section_match = section_pattern.search(content)
    if not section_match:
        return targets

    section_text = section_match.group(1)

    # Find each entry start: <hex-id> /* <comment> */ = {
    entry_start_pattern = re.compile(
        r"([A-Fa-f0-9]+)\s*/\*\s*(.*?)\s*\*/\s*=\s*\{"
    )

    for m in entry_start_pattern.finditer(section_text):
        target_id = m.group(1)
        target_comment = m.group(2).strip()
        # m.start() is where the ID begins, m.end() is right after '{'
        brace_start = m.end() - 1  # position of the opening '{'

        # Extract full body using brace-depth tracking
        body = _extract_braced_body(section_text, brace_start)
        if body is None:
            continue

        target_info = {
            "id": target_id,
            "name": _extract_value(body, "name"),
            "productType": _extract_value(body, "productType"),
            "product_type_human": PRODUCT_TYPE_MAP.get(
                _extract_value(body, "productType"), "unknown"
            ),
        }

        # Only include productName if present and differs from name
        product_name = _extract_value(body, "productName")
        if product_name and product_name != target_info["name"]:
            target_info["productName"] = product_name

        # Extract buildSettings (nested dict) using brace tracking
        bs_match = re.search(r"buildSettings\s*=\s*\{", body)
        if bs_match:
            bs_body = _extract_braced_body(body, bs_match.end() - 1)
            if bs_body is not None:
                target_info["buildSettings"] = _extract_build_settings(bs_body)

        # Fall back to target_comment if 'name' field not found
        if not target_info["name"]:
            target_info["name"] = target_comment

        targets.append(target_info)

    return targets


def _extract_braced_body(text, open_brace_pos):
    """Extract content inside braces using depth tracking.

    Returns the text between { and } (inclusive of the braces),
    or None if braces are unbalanced.
    """
    depth = 0
    in_string = False
    in_comment = False

    for i in range(open_brace_pos, len(text)):
        c = text[i]

        # Track comment state (/* ... */)
        if not in_string and c == '/' and i + 1 < len(text) and text[i + 1] == '*':
            in_comment = True
            continue
        if in_comment and c == '*' and i + 1 < len(text) and text[i + 1] == '/':
            in_comment = False
            continue

        if in_comment:
            continue

        # Track string state
        if c == '"' and (i == 0 or text[i - 1] != '\\'):
            in_string = not in_string
            continue

        if in_string:
            continue

        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[open_brace_pos:i + 1]

    return None


def _extract_value(body, key):
    """Extract a simple string value for a given key from pbxproj body text."""
    # Try quoted string first
    pattern = re.compile(
        rf"{re.escape(key)}\s*=\s*\"([^\"]*)\"\s*;"
    )
    match = pattern.search(body)
    if match:
        return match.group(1)

    # Try unquoted identifier
    pattern = re.compile(
        rf"{re.escape(key)}\s*=\s*(\w+)\s*;"
    )
    match = pattern.search(body)
    if match:
        return match.group(1)

    return ""


def _extract_build_settings(settings_text):
    """Extract build settings key-value pairs from settings body text.

    The input includes the outer braces; they are stripped before parsing.
    """
    # Strip outer braces if present
    text = settings_text.strip()
    if text.startswith("{"):
        text = text[1:]
    if text.endswith("}"):
        text = text[:-1]
    text = text.strip()

    settings = {}
    # Match KEY = VALUE; or KEY = "VALUE";
    pattern = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|([^;]*?))\s*;')
    for match in pattern.finditer(text):
        key = match.group(1)
        value = match.group(2) if match.group(2) is not None else match.group(3)
        if value is not None:
            settings[key] = value.strip()
    return settings


# ---------------------------------------------------------------------------
# Directory scan (fallback)
# ---------------------------------------------------------------------------

def directory_scan(root_path):
    """Scan a directory for Swift files and basic structure."""
    root = Path(root_path).resolve()
    result = {
        "swift_files": [],
        "plist_files": [],
        "entitlement_files": [],
        "xcprivacy_files": [],
        "xcconfig_files": [],
        "asset_catalogs": [],
        "total_swift_file_count": 0,
    }

    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(root))
            suffix = path.suffix.lower()

            if suffix == ".swift":
                size = path.stat().st_size
                result["swift_files"].append({
                    "path": rel,
                    "size": size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                })
                result["total_swift_file_count"] += 1

            elif suffix == ".plist":
                result["plist_files"].append(rel)

            elif suffix == ".entitlements":
                result["entitlement_files"].append(rel)

            elif suffix == ".xcconfig":
                result["xcconfig_files"].append(rel)

            elif path.name == "PrivacyInfo.xcprivacy":
                result["xcprivacy_files"].append(rel)

        elif path.is_dir() and path.suffix.lower() == ".xcassets":
            result["asset_catalogs"].append(str(path.relative_to(root)))

    return result


# ---------------------------------------------------------------------------
# Xcode project analysis
# ---------------------------------------------------------------------------

def analyze_xcode_project(root_path, xcodeproj_paths):
    """Analyze an Xcode project: lex pbxproj and run directory scan."""
    root = Path(root_path).resolve()
    project_data = {
        "targets": [],
        "warnings": [],
        "pbxproj_parse_success": True,
    }

    for xcp_path in xcodeproj_paths:
        pbxproj = root / xcp_path / "project.pbxproj"
        if pbxproj.is_file():
            lexed = lex_pbxproj(str(pbxproj))

            # Prefix target names with project name for disambiguation
            project_name = xcp_path.replace(".xcodeproj", "")
            for target in lexed.get("targets", []):
                target_copy = dict(target)
                target_copy["project"] = project_name
                project_data["targets"].append(target_copy)

            project_data["warnings"].extend(lexed.get("warnings", []))
            project_data["pbxproj_parse_success"] = (
                project_data["pbxproj_parse_success"] and lexed.get("parse_success", True)
            )

            if not lexed.get("parse_success", True):
                project_data["warnings"].append(
                    f"pbxproj parse failed for {xcp_path}, falling back to directory scan"
                )

    # Always also run directory scan
    dir_scan = directory_scan(root_path)

    return project_data, dir_scan


# ---------------------------------------------------------------------------
# Plist / Entitlement analysis
# ---------------------------------------------------------------------------

def analyze_plists(root_path):
    """Parse all .plist and .entitlements files for deterministic analysis."""
    root = Path(root_path).resolve()
    findings = []
    warnings = []

    for plist_path in sorted(root.rglob("*")):
        if plist_path.is_file() and plist_path.suffix.lower() in (".plist", ".entitlements"):
            rel = str(plist_path.relative_to(root))
            try:
                with open(plist_path, "rb") as f:
                    data = plistlib.load(f)
                findings.append({
                    "file": rel,
                    "keys": list(data.keys()) if isinstance(data, dict) else ["<array_root>"],
                    "parse_success": True,
                })
            except Exception as e:
                warnings.append(f"Failed to parse {rel}: {e}")
                findings.append({
                    "file": rel,
                    "parse_success": False,
                    "error": str(e),
                })

    return findings, warnings


# ---------------------------------------------------------------------------
# Swift heuristic scan
# ---------------------------------------------------------------------------

def _line_number(text, pos):
    """Return 1-based line number for a position in text."""
    return text[:pos].count("\n") + 1


def _find_braced_block(text, start_pos):
    """Find matching closing brace using depth tracking.

    Skips strings, // line comments, and /* block comments */.
    Returns the index of the matching '}' or None if unbalanced.
    """
    depth = 0
    in_string = False
    in_line_comment = False
    in_block_comment = False
    i = start_pos

    while i < len(text):
        c = text[i]

        if in_line_comment:
            if c == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if c == "*" and i + 1 < len(text) and text[i + 1] == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if not in_string:
            if c == "/" and i + 1 < len(text):
                nxt = text[i + 1]
                if nxt == "/":
                    in_line_comment = True
                    i += 2
                    continue
                if nxt == "*":
                    in_block_comment = True
                    i += 2
                    continue

        if c == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
            i += 1
            continue

        if in_string:
            if c == "\\" and i + 1 < len(text) and text[i + 1] == '"':
                i += 2
                continue
            i += 1
            continue

        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i

        i += 1

    return None


def _scan_imports_and_frameworks(content, rel_path):
    """Detect SwiftUI, UIKit, AppKit imports."""
    findings = []
    patterns = [
        (r"^import\s+SwiftUI", "import_swiftui", "SwiftUI import",
         "high_confidence_heuristic"),
        (r"^import\s+UIKit", "import_uikit", "UIKit import",
         "high_confidence_heuristic"),
        (r"^import\s+AppKit", "import_appkit", "AppKit import",
         "high_confidence_heuristic"),
        (r"^import\s+Combine", "import_combine", "Combine import",
         "high_confidence_heuristic"),
        (r"^import\s+SwiftData", "import_swiftdata", "SwiftData import",
         "high_confidence_heuristic"),
        (r"^import\s+CoreData", "import_coredata", "CoreData import",
         "high_confidence_heuristic"),
        (r"^import\s+WatchKit", "import_watchkit", "WatchKit import",
         "high_confidence_heuristic"),
    ]
    for pattern, pid, desc, conf in patterns:
        for match in re.finditer(pattern, content, re.MULTILINE):
            findings.append({
                "file": rel_path,
                "line": _line_number(content, match.start()),
                "category": "framework_import",
                "finding_id": pid,
                "description": desc,
                "confidence": conf,
                "match": match.group(0).strip(),
            })
    return findings


def _scan_base_classes(content, rel_path):
    """Detect SwiftUI View structs, UIView/UIViewController subclasses, App protocol."""
    findings = []
    patterns = [
        (r"struct\s+(\w+)\s*:\s*View\b", "swiftui_view_struct",
         "SwiftUI View struct", "high_confidence_heuristic"),
        (r"class\s+(\w+)\s*:\s*UIViewController\b", "uikit_viewcontroller",
         "UIViewController subclass", "high_confidence_heuristic"),
        (r"class\s+(\w+)\s*:\s*UIView\b", "uikit_uiview",
         "UIView subclass", "high_confidence_heuristic"),
        (r"class\s+(\w+)\s*:\s*NSViewController\b", "appkit_viewcontroller",
         "NSViewController subclass", "high_confidence_heuristic"),
        (r"class\s+(\w+)\s*:\s*NSView\b", "appkit_nsview",
         "NSView subclass", "high_confidence_heuristic"),
        (r"struct\s+(\w+)\s*:\s*App\b", "swiftui_app",
         "SwiftUI App struct", "high_confidence_heuristic"),
        (r"class\s+(\w+)\s*:\s*NSApplicationDelegate\b", "appkit_app_delegate",
         "NSApplicationDelegate", "high_confidence_heuristic"),
        (r"class\s+(\w+)\s*:\s*UIApplicationDelegate\b", "uikit_app_delegate",
         "UIApplicationDelegate", "high_confidence_heuristic"),
        (r"class\s+(\w+)\s*:\s*WKInterfaceController\b", "watchkit_controller",
         "WKInterfaceController subclass", "high_confidence_heuristic"),
    ]
    for pattern, pid, desc, conf in patterns:
        for match in re.finditer(pattern, content, re.MULTILINE):
            type_name = match.group(1) if match.lastindex and match.lastindex >= 1 else ""
            findings.append({
                "file": rel_path,
                "line": _line_number(content, match.start()),
                "category": "base_class",
                "finding_id": pid,
                "description": desc,
                "confidence": conf,
                "match": match.group(0).strip(),
                "type_name": type_name,
            })
    return findings


def _scan_property_wrappers(content, rel_path):
    """Count @StateObject, @ObservedObject, @EnvironmentObject, @State, @Binding."""
    findings = []
    patterns = [
        (r"@StateObject\s+(private\s+|internal\s+|public\s+)?var\s+(\w+)",
         "state_object", "@StateObject usage", "high_confidence_heuristic"),
        (r"@ObservedObject\s+(private\s+|internal\s+|public\s+)?var\s+(\w+)",
         "observed_object", "@ObservedObject usage", "high_confidence_heuristic"),
        (r"@EnvironmentObject\s+(private\s+|internal\s+|public\s+)?var\s+(\w+)",
         "environment_object", "@EnvironmentObject usage", "high_confidence_heuristic"),
        (r"@State\s+(private\s+|internal\s+|public\s+)?var\s+(\w+)",
         "state_property", "@State usage", "high_confidence_heuristic"),
        (r"@Binding\s+(private\s+|internal\s+|public\s+)?var\s+(\w+)",
         "binding_property", "@Binding usage", "high_confidence_heuristic"),
        (r"@Published\s+(private\s+|internal\s+|public\s+)?var\s+(\w+)",
         "published_property", "@Published usage", "high_confidence_heuristic"),
        (r"@AppStorage\s*\(\s*\"[^\"]*\"\s*\)\s*(private\s+|internal\s+|public\s+)?var\s+(\w+)",
         "app_storage", "@AppStorage usage", "high_confidence_heuristic"),
        (r"@SceneStorage\s*\(\s*\"[^\"]*\"\s*\)\s*(private\s+|internal\s+|public\s+)?var\s+(\w+)",
         "scene_storage", "@SceneStorage usage", "high_confidence_heuristic"),
    ]
    for pattern, pid, desc, conf in patterns:
        for match in re.finditer(pattern, content, re.MULTILINE):
            prop_name = match.group(match.lastindex) if match.lastindex else ""
            findings.append({
                "file": rel_path,
                "line": _line_number(content, match.start()),
                "category": "property_wrapper",
                "finding_id": pid,
                "description": desc,
                "confidence": conf,
                "match": match.group(0).strip(),
                "property_name": prop_name,
            })
    return findings


def _scan_view_body_metrics(content, rel_path):
    """Approximate view body size and nested stack depth via brace counting."""
    findings = []
    body_pattern = re.compile(r"var\s+body\s*:\s*some\s+View\s*\{")
    for match in body_pattern.finditer(content):
        open_pos = match.end() - 1
        close_pos = _find_braced_block(content, open_pos)
        if close_pos is None:
            continue
        body_block = content[open_pos:close_pos + 1]
        body_lines = body_block.count("\n")
        line_num = _line_number(content, match.start())

        findings.append({
            "file": rel_path,
            "line": line_num,
            "category": "view_metrics",
            "finding_id": "view_body_size",
            "description": f"View body size: ~{body_lines} lines",
            "confidence": "heuristic",
            "body_size_lines": body_lines,
            "match": match.group(0).strip(),
        })

        if body_lines > 80:
            findings.append({
                "file": rel_path,
                "line": line_num,
                "category": "view_metrics",
                "finding_id": "large_view_body",
                "description": f"Large view body ({body_lines} lines); consider extracting subviews",
                "confidence": "heuristic",
                "body_size_lines": body_lines,
                "match": match.group(0).strip(),
            })

        stack_pattern = re.compile(r"\b(VStack|HStack|ZStack)\s*\{")
        body_inner = content[open_pos + 1:close_pos]
        stack_matches = list(stack_pattern.finditer(body_inner))

        max_depth = 0
        for sm in stack_matches:
            depth = 1
            inner_start = sm.end() - 1
            inner_close = _find_braced_block(body_inner, inner_start)
            if inner_close:
                inner_content = body_inner[inner_start + 1:inner_close]
                depth += len(stack_pattern.findall(inner_content))
            if depth > max_depth:
                max_depth = depth

        if stack_matches:
            findings.append({
                "file": rel_path,
                "line": line_num,
                "category": "view_metrics",
                "finding_id": "stack_depth",
                "description": f"Stack nesting depth: ~{max_depth}",
                "confidence": "heuristic",
                "stack_count": len(stack_matches),
                "max_stack_depth": max_depth,
                "match": "var body: some View { ... }",
            })

            if max_depth > 3:
                findings.append({
                    "file": rel_path,
                    "line": line_num,
                    "category": "view_metrics",
                    "finding_id": "deep_stack_nesting",
                    "description": f"Deep stack nesting (depth ~{max_depth}); consider extracting subviews",
                    "confidence": "heuristic",
                    "max_stack_depth": max_depth,
                    "match": "var body: some View { ... }",
                })

    return findings


def _scan_hardcoded_ui_patterns(content, rel_path):
    """Flag hardcoded colors, fonts, frames, and spacings."""
    findings = []
    patterns = [
        (r"\.foregroundColor\(\s*\.\w+\s*\)", "hardcoded_foreground_color",
         "Hardcoded foregroundColor", "heuristic"),
        (r"\.background\(\s*\.\w+\s*\)", "hardcoded_background",
         "Hardcoded background color", "heuristic"),
        (r"\.tint\(\s*\.\w+\s*\)", "hardcoded_tint",
         "Hardcoded tint", "heuristic"),
        (r'Color\(\s*"#', "hardcoded_color_hex",
         "Hardcoded hex color literal", "heuristic"),
        (r'UIColor\(\s*"#', "hardcoded_uicolor_hex",
         "Hardcoded UIColor hex literal", "heuristic"),
        (r"\.font\(\s*\.system\s*\(", "hardcoded_system_font",
         "System font without text style", "heuristic"),
        (r"\.font\(\s*\.\w+\s*\)", "hardcoded_font_style",
         "Hardcoded font", "heuristic"),
        (r"UIFont\.systemFont\(", "hardcoded_uifont",
         "Hardcoded UIFont.systemFont", "heuristic"),
        (r"\.frame\(\s*width\s*:", "hardcoded_frame_width",
         "Hardcoded frame width", "heuristic"),
        (r"\.frame\(\s*height\s*:", "hardcoded_frame_height",
         "Hardcoded frame height", "heuristic"),
        (r"\.frame\(\s*width\s*:\s*\d+", "hardcoded_frame_numeric",
         "Hardcoded numeric frame dimension", "heuristic"),
        (r"CGRect\(\s*x\s*:\s*\d+", "hardcoded_cgrect",
         "Hardcoded CGRect with numeric values", "heuristic"),
        (r"\.padding\(\s*\d+\s*\)", "hardcoded_padding_numeric",
         "Hardcoded numeric padding", "heuristic"),
        (r"HStack\s*\(\s*spacing\s*:\s*\d+\s*\)", "hardcoded_hstack_spacing",
         "Hardcoded HStack spacing", "heuristic"),
        (r"VStack\s*\(\s*spacing\s*:\s*\d+\s*\)", "hardcoded_vstack_spacing",
         "Hardcoded VStack spacing", "heuristic"),
    ]
    for pattern, pid, desc, conf in patterns:
        for match in re.finditer(pattern, content, re.MULTILINE):
            findings.append({
                "file": rel_path,
                "line": _line_number(content, match.start()),
                "category": "hardcoded_ui",
                "finding_id": pid,
                "description": desc,
                "confidence": conf,
                "match": match.group(0).strip()[:80],
            })
    return findings


def _scan_task_in_views(content, rel_path):
    """Detect Task { ... } and .task { ... } patterns."""
    findings = []
    patterns = [
        (r"Task\s*\{", "task_closure", "Task { ... } detected",
         "high_confidence_heuristic"),
        (r"\.task\s*\{", "task_modifier", ".task { ... } view modifier",
         "high_confidence_heuristic"),
    ]
    for pattern, pid, desc, conf in patterns:
        for match in re.finditer(pattern, content, re.MULTILINE):
            findings.append({
                "file": rel_path,
                "line": _line_number(content, match.start()),
                "category": "async_patterns",
                "finding_id": pid,
                "description": desc,
                "confidence": conf,
                "match": match.group(0).strip(),
            })
    return findings


def _scan_image_accessibility(content, rel_path):
    """Flag Image(systemName:) without nearby accessibility labels."""
    findings = []
    image_pattern = re.compile(r"Image\(\s*systemName\s*:\s*\"[^\"]*\"")
    for match in image_pattern.finditer(content):
        end_pos = match.end()
        window_end = min(end_pos + 300, len(content))
        window = content[end_pos:window_end]

        has_label = ".accessibilityLabel" in window
        has_hidden = ".accessibilityHidden" in window

        if has_label:
            findings.append({
                "file": rel_path,
                "line": _line_number(content, match.start()),
                "category": "accessibility",
                "finding_id": "image_with_accessibility_label",
                "description": "Image(systemName:) has accessibility label",
                "confidence": "high_confidence_heuristic",
                "match": match.group(0).strip()[:80],
            })
        elif has_hidden:
            findings.append({
                "file": rel_path,
                "line": _line_number(content, match.start()),
                "category": "accessibility",
                "finding_id": "image_accessibility_hidden",
                "description": "Image(systemName:) is accessibility hidden",
                "confidence": "high_confidence_heuristic",
                "match": match.group(0).strip()[:80],
            })
        else:
            findings.append({
                "file": rel_path,
                "line": _line_number(content, match.start()),
                "category": "accessibility",
                "finding_id": "image_without_accessibility_label",
                "description": "Image(systemName:) without accessibility label",
                "confidence": "heuristic",
                "match": match.group(0).strip()[:80],
            })

    return findings


def _scan_risk_markers(content, rel_path):
    """Detect force unwraps, try!, fatalError, TODO/FIXME markers."""
    findings = []

    fu_pattern = re.compile(r"(?<![!=])\b(\w+)\s*!(?!\s*=)")
    for match in fu_pattern.finditer(content):
        findings.append({
            "file": rel_path,
            "line": _line_number(content, match.start()),
            "category": "risk_signal",
            "finding_id": "force_unwrap",
            "description": "Force unwrap (!)",
            "confidence": "high_confidence_heuristic",
            "match": match.group(0).strip(),
        })

    for match in re.finditer(r"try\s*!", content, re.MULTILINE):
        findings.append({
            "file": rel_path,
            "line": _line_number(content, match.start()),
            "category": "risk_signal",
            "finding_id": "force_try",
            "description": "Force try (try!)",
            "confidence": "high_confidence_heuristic",
            "match": match.group(0).strip(),
        })

    for match in re.finditer(r"\b(fatalError|preconditionFailure)\s*\(", content, re.MULTILINE):
        findings.append({
            "file": rel_path,
            "line": _line_number(content, match.start()),
            "category": "risk_signal",
            "finding_id": "fatal_error_call",
            "description": f"{match.group(1)}() call",
            "confidence": "high_confidence_heuristic",
            "match": match.group(0).strip()[:80],
        })

    for match in re.finditer(r"(TODO|FIXME|HACK|XXX)\s*[:]", content, re.MULTILINE):
        findings.append({
            "file": rel_path,
            "line": _line_number(content, match.start()),
            "category": "risk_signal",
            "finding_id": "todo_fixme_marker",
            "description": f"{match.group(1)} marker in source",
            "confidence": "high_confidence_heuristic",
            "match": match.group(0).strip()[:80],
        })

    return findings


def _scan_storekit_patterns(content, rel_path):
    """Detect StoreKit imports and API call patterns."""
    findings = []

    for match in re.finditer(r"^import\s+StoreKit\b", content, re.MULTILINE):
        findings.append({
            "file": rel_path,
            "line": _line_number(content, match.start()),
            "category": "storekit",
            "finding_id": "storekit_import",
            "description": "StoreKit import detected",
            "confidence": "high_confidence_heuristic",
            "match": match.group(0).strip(),
        })

    patterns = [
        (r"Product\.(consumable|nonConsumable|autoRenewable|nonRenewable)",
         "storekit_product_def", "StoreKit product definition",
         "high_confidence_heuristic"),
        (r"\.purchase\s*\(", "storekit_purchase", "StoreKit purchase call",
         "high_confidence_heuristic"),
        (r"\b(restorePurchases|tryRestorePurchases|restore_purchases)\b",
         "storekit_restore", "StoreKit restore purchases",
         "high_confidence_heuristic"),
        (r"SubscriptionStoreView\b",
         "storekit_subscription_view", "SubscriptionStoreView usage",
         "high_confidence_heuristic"),
        (r"ProductView\b",
         "storekit_product_view", "ProductView usage",
         "high_confidence_heuristic"),
        (r"\.subscriptionStatusTask\s*\{",
         "storekit_status_task", "StoreKit subscriptionStatusTask",
         "high_confidence_heuristic"),
        (r"\.manageSubscriptionsSheet\b",
         "storekit_manage_sheet", "StoreKit manageSubscriptionsSheet",
         "high_confidence_heuristic"),
        (r"\brequestReview\s*\(",
         "storekit_review_request", "StoreKit review request",
         "high_confidence_heuristic"),
        (r"Transaction\.(currentEntitlements|updates|latest)",
         "storekit_transaction", "StoreKit Transaction API",
         "high_confidence_heuristic"),
    ]
    for pattern, pid, desc, conf in patterns:
        for match in re.finditer(pattern, content, re.MULTILINE):
            findings.append({
                "file": rel_path,
                "line": _line_number(content, match.start()),
                "category": "storekit",
                "finding_id": pid,
                "description": desc,
                "confidence": conf,
                "match": match.group(0).strip()[:80],
            })

    return findings


def _scan_type_suffixes(content, rel_path):
    """Count type-name suffixes (ViewModel, Service, Manager, Store, Router)."""
    findings = []
    suffixes = {
        "ViewModel": "view_model_suffix",
        "Service": "service_suffix",
        "Manager": "manager_suffix",
        "Store": "store_suffix",
        "Router": "router_suffix",
        "Coordinator": "coordinator_suffix",
        "Repository": "repository_suffix",
        "Interactor": "interactor_suffix",
        "Presenter": "presenter_suffix",
        "UseCase": "usecase_suffix",
    }
    for suffix, pid in suffixes.items():
        pattern = re.compile(
            rf"\b(?:class|struct|actor|enum|protocol|extension)\s+\w*{suffix}\b"
        )
        for match in pattern.finditer(content):
            findings.append({
                "file": rel_path,
                "line": _line_number(content, match.start()),
                "category": "architecture_signal",
                "finding_id": pid,
                "description": f"Type with '{suffix}' suffix",
                "confidence": "heuristic",
                "suffix": suffix,
                "match": match.group(0).strip(),
            })
    return findings


def _update_summary(summary, file_findings):
    """Update summary counters from a file's heuristic findings."""
    for f in file_findings:
        fid = f.get("finding_id", "")
        if fid == "import_swiftui":
            summary["swiftui_files"] = 1
        elif fid == "import_uikit":
            summary["uikit_files"] = 1
        elif fid == "import_appkit":
            summary["appkit_files"] = 1
        elif fid == "state_object":
            summary["total_state_objects"] += 1
        elif fid == "observed_object":
            summary["total_observed_objects"] += 1
        elif fid == "environment_object":
            summary["total_environment_objects"] += 1
        elif fid == "state_property":
            summary["total_state"] += 1
        elif fid == "binding_property":
            summary["total_bindings"] += 1
        elif fid == "view_model_suffix":
            summary["total_view_models"] += 1
        elif fid == "service_suffix":
            summary["total_services"] += 1
        elif fid == "manager_suffix":
            summary["total_managers"] += 1
        elif fid == "store_suffix":
            summary["total_stores"] += 1
        elif fid == "router_suffix":
            summary["total_routers"] += 1
        elif fid == "force_unwrap":
            summary["total_force_unwraps"] += 1
        elif fid == "force_try":
            summary["total_force_trys"] += 1
        elif fid == "todo_fixme_marker":
            match_text = f.get("match", "")
            if match_text.startswith("TODO"):
                summary["total_todos"] += 1
            elif match_text.startswith("FIXME"):
                summary["total_fixmes"] += 1
        elif fid == "storekit_import":
            summary["storekit_detected"] = True


def analyze_swift_files(root_path):
    """Heuristic scan of .swift files for common patterns.

    Performs regex-based analysis covering:
      - SwiftUI/UIKit/AppKit import and base-class detection
      - View body size and nested stack depth (brace counting)
      - Hardcoded colors, fonts, frames, and spacings
      - @StateObject, @ObservedObject, @EnvironmentObject, @State, @Binding
      - Task { ... } and .task { ... } inside views
      - Image(systemName:) without accessibility labels
      - Force unwraps, try!, fatalError, TODO/FIXME markers
      - StoreKit import and API call patterns
      - Type-name suffixes (ViewModel, Service, Manager, Store, Router)

    Every finding carries confidence: "heuristic" or "high_confidence_heuristic".

    Returns a dict with 'files_scanned', 'heuristics', and 'summary' keys.
    """
    root = Path(root_path).resolve()
    findings = {
        "files_scanned": 0,
        "heuristics": [],
        "summary": {
            "swiftui_files": 0,
            "uikit_files": 0,
            "appkit_files": 0,
            "total_state_objects": 0,
            "total_observed_objects": 0,
            "total_environment_objects": 0,
            "total_state": 0,
            "total_bindings": 0,
            "total_view_models": 0,
            "total_services": 0,
            "total_managers": 0,
            "total_stores": 0,
            "total_routers": 0,
            "total_force_unwraps": 0,
            "total_force_trys": 0,
            "total_todos": 0,
            "total_fixmes": 0,
            "storekit_detected": False,
        },
    }

    for swift_file in sorted(root.rglob("*.swift")):
        try:
            with open(swift_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            continue

        findings["files_scanned"] += 1
        rel = str(swift_file.relative_to(root))

        file_findings = []
        file_findings.extend(_scan_imports_and_frameworks(content, rel))
        file_findings.extend(_scan_base_classes(content, rel))
        file_findings.extend(_scan_property_wrappers(content, rel))
        file_findings.extend(_scan_view_body_metrics(content, rel))
        file_findings.extend(_scan_hardcoded_ui_patterns(content, rel))
        file_findings.extend(_scan_image_accessibility(content, rel))
        file_findings.extend(_scan_risk_markers(content, rel))
        file_findings.extend(_scan_storekit_patterns(content, rel))
        file_findings.extend(_scan_type_suffixes(content, rel))
        file_findings.extend(_scan_task_in_views(content, rel))

        seen = set()
        deduped = []
        for f in file_findings:
            key = (f["finding_id"], f["line"], f.get("match", ""))
            if key not in seen:
                seen.add(key)
                deduped.append(f)

        findings["heuristics"].extend(deduped)
        _update_summary(findings["summary"], deduped)

    return findings

# ---------------------------------------------------------------------------
# Platform analyzer constants
# ---------------------------------------------------------------------------

# Framework import -> required Info.plist usage description keys
FRAMEWORK_PERMISSION_MAP = {
    "AVFoundation": [
        ("NSCameraUsageDescription", "Privacy - Camera Usage Description"),
        ("NSMicrophoneUsageDescription", "Privacy - Microphone Usage Description"),
    ],
    "CoreLocation": [
        ("NSLocationWhenInUseUsageDescription", "Privacy - Location When In Use Usage Description"),
        ("NSLocationAlwaysAndWhenInUseUsageDescription",
         "Privacy - Location Always and When In Use Usage Description"),
    ],
    "Photos": [
        ("NSPhotoLibraryUsageDescription", "Privacy - Photo Library Usage Description"),
    ],
    "PhotosUI": [
        ("NSPhotoLibraryUsageDescription", "Privacy - Photo Library Usage Description"),
    ],
    "Contacts": [
        ("NSContactsUsageDescription", "Privacy - Contacts Usage Description"),
    ],
    "ContactsUI": [
        ("NSContactsUsageDescription", "Privacy - Contacts Usage Description"),
    ],
    "CoreBluetooth": [
        ("NSBluetoothAlwaysUsageDescription", "Privacy - Bluetooth Always Usage Description"),
    ],
    "EventKit": [
        ("NSCalendarsUsageDescription", "Privacy - Calendars Usage Description"),
    ],
    "HealthKit": [
        ("NSHealthShareUsageDescription", "Privacy - Health Share Usage Description"),
        ("NSHealthUpdateUsageDescription", "Privacy - Health Update Usage Description"),
    ],
    "Speech": [
        ("NSSpeechRecognitionUsageDescription", "Privacy - Speech Recognition Usage Description"),
    ],
    "MediaPlayer": [
        ("NSAppleMusicUsageDescription", "Privacy - Media Library Usage Description"),
    ],
    "HomeKit": [
        ("NSHomeKitUsageDescription", "Privacy - HomeKit Usage Description"),
    ],
    "ARKit": [
        ("NSCameraUsageDescription", "Privacy - Camera Usage Description"),
    ],
    "AdSupport": [],
    "AppTrackingTransparency": [
        ("NSUserTrackingUsageDescription", "Privacy - User Tracking Usage Description"),
    ],
    "CallKit": [],
    "PushKit": [],
    "PassKit": [],
    "Intents": [],
}

# Frameworks whose use triggers a privacy-manifest requirement
PRIVACY_SENSITIVE_FRAMEWORKS = [
    "AVFoundation", "CoreLocation", "Photos", "PhotosUI", "Contacts", "ContactsUI",
    "CoreBluetooth", "EventKit", "HealthKit", "Speech", "MediaPlayer", "HomeKit",
    "ARKit", "AdSupport", "AppTrackingTransparency",
]

# Required-reason API categories per Apple documentation
REQUIRED_REASON_API_PATTERNS = [
    (r"UserDefaults\b", "NSUserDefaults", "NSPrivacyAccessedAPICategoryUserDefaults"),
    (r"FileManager\.default", "FileManager", "NSPrivacyAccessedAPICategoryFileTimestamp"),
    (r"\.creationDate|\.modificationDate|\.fileModificationDate", "FileTimestamp",
     "NSPrivacyAccessedAPICategoryFileTimestamp"),
    (r"systemUptime|ProcessInfo\.processInfo\.systemUptime", "SystemBootTime",
     "NSPrivacyAccessedAPICategorySystemBootTime"),
    (r"activeInputModes|UITextInputMode\.activeInputModes", "ActiveInputModes",
     "NSPrivacyAccessedAPICategoryActiveInputModes"),
    (r"\.availableDiskSpace|\.volumeAvailableCapacity|\.volumeTotalCapacity",
     "DiskSpace", "NSPrivacyAccessedAPICategoryDiskSpace"),
]


# ---------------------------------------------------------------------------
# Permission string analyzer (Info.plist review)
# ---------------------------------------------------------------------------

def _detect_framework_imports(root_path):
    """Scan Swift files for Apple framework imports. Returns set of framework names."""
    root = Path(root_path).resolve()
    imports = set()
    import_re = re.compile(r"^import\s+(\w+)", re.MULTILINE)
    for swift_file in root.rglob("*.swift"):
        try:
            content = swift_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in import_re.finditer(content):
            imports.add(m.group(1))
    return imports


def _load_plist_data(root_path):
    """Load all .plist files in the project tree. Returns dict of {relpath: parsed_data}."""
    root = Path(root_path).resolve()
    plists = {}
    for plist_path in root.rglob("*.plist"):
        try:
            with open(plist_path, "rb") as f:
                plists[str(plist_path.relative_to(root))] = plistlib.load(f)
        except Exception:
            pass
    return plists


def analyze_permission_strings(root_path):
    """Check Info.plist files for missing usage-description keys based on detected imports.

    Returns a list of finding dicts, all with confidence='verified'.
    """
    findings = []
    imports = _detect_framework_imports(root_path)
    plists = _load_plist_data(root_path)

    if not plists:
        return findings

    # For each imported framework that maps to plist keys, check presence in all plists
    all_plist_keys = set()
    for data in plists.values():
        if isinstance(data, dict):
            all_plist_keys.update(data.keys())

    # Filter to frameworks actually imported that have permission requirements
    for framework, required_keys in sorted(FRAMEWORK_PERMISSION_MAP.items()):
        if framework not in imports:
            continue
        if not required_keys:
            continue

        for key, description in required_keys:
            if key not in all_plist_keys:
                findings.append({
                    "category": "permission_strings",
                    "severity": "error",
                    "confidence": "verified",
                    "message": f"Missing '{key}' ({description}) in Info.plist "
                               f"but '{framework}' is imported",
                    "framework": framework,
                    "missing_key": key,
                    "description": description,
                    "plist_files": sorted(plists.keys()),
                })

    return findings


# ---------------------------------------------------------------------------
# Entitlement capability analyzer
# ---------------------------------------------------------------------------

ENTITLEMENT_CHECK_MAP = {
    "aps-environment": {
        "description": "Push notifications",
        "requires_notification_framework": True,
    },
    "com.apple.developer.healthkit": {
        "description": "HealthKit capability",
        "requires_healthkit_import": True,
    },
    "com.apple.developer.networking.wifi-info": {
        "description": "WiFi network information (Hotspot Helper)",
    },
    "com.apple.developer.siri": {
        "description": "Siri / Intents capability",
    },
    "com.apple.developer.associated-domains": {
        "description": "Associated Domains",
    },
    "com.apple.security.application-groups": {
        "description": "App Groups (shared container)",
    },
    "keychain-access-groups": {
        "description": "Keychain sharing",
    },
    "com.apple.developer.in-app-payments": {
        "description": "Apple Pay / In-App Payments",
    },
    "com.apple.developer.homekit": {
        "description": "HomeKit capability",
    },
    "com.apple.developer.nfc.readersession": {
        "description": "NFC capability",
    },
}

# Capabilities that should exist in-app only, not in extensions
APP_ONLY_ENTITLEMENTS = {
    "aps-environment",
    "com.apple.developer.healthkit",
    "com.apple.developer.in-app-payments",
}


def analyze_entitlement_capabilities(root_path):
    """Parse .entitlements files and check for capability consistency.

    Returns a list of finding dicts, all with confidence='verified'.
    """
    root = Path(root_path).resolve()
    findings = []

    for ent_path in sorted(root.rglob("*.entitlements")):
        rel = str(ent_path.relative_to(root))
        try:
            with open(ent_path, "rb") as f:
                data = plistlib.load(f)
        except Exception:
            findings.append({
                "category": "entitlements",
                "severity": "warning",
                "confidence": "verified",
                "message": f"Failed to parse entitlement file '{rel}'",
                "file": rel,
            })
            continue

        if not isinstance(data, dict):
            continue

        # Check each entitlement key against known patterns
        for ent_key, info in sorted(ENTITLEMENT_CHECK_MAP.items()):
            if ent_key in data:
                value = data[ent_key]
                finding = {
                    "category": "entitlements",
                    "severity": "info",
                    "confidence": "verified",
                    "message": f"Entitlement '{info['description']}' ({ent_key}) present in '{rel}'",
                    "file": rel,
                    "entitlement_key": ent_key,
                    "entitlement_description": info["description"],
                    "value": str(value) if not isinstance(value, (dict, list)) else "<complex>",
                }
                findings.append(finding)

        # Flag entitlements not in our knowledge base
        for key in data:
            if key not in ENTITLEMENT_CHECK_MAP and not key.startswith("_"):
                findings.append({
                    "category": "entitlements",
                    "severity": "info",
                    "confidence": "verified",
                    "message": f"Entitlement '{key}' in '{rel}' is not in known capability catalog",
                    "file": rel,
                    "entitlement_key": key,
                })

    return findings


# ---------------------------------------------------------------------------
# Privacy manifest (PrivacyInfo.xcprivacy) analyzer
# ---------------------------------------------------------------------------

def analyze_privacy_manifest(root_path):
    """Check for PrivacyInfo.xcprivacy existence and required-reason API coverage.

    Returns a list of finding dicts, all with confidence='verified'.
    """
    root = Path(root_path).resolve()
    findings = []

    xcprivacy_files = list(root.rglob("PrivacyInfo.xcprivacy"))
    imports = _detect_framework_imports(root_path)

    # Find privacy-sensitive frameworks that ARE imported
    sensitive_used = [fw for fw in PRIVACY_SENSITIVE_FRAMEWORKS if fw in imports]

    if sensitive_used and not xcprivacy_files:
        findings.append({
            "category": "privacy_manifest",
            "severity": "error",
            "confidence": "verified",
            "message": (
                f"PrivacyInfo.xcprivacy is missing but privacy-sensitive "
                f"frameworks are used: {', '.join(sorted(sensitive_used))}. "
                f"Required for App Store submission starting May 1, 2024."
            ),
            "frameworks_used": sorted(sensitive_used),
        })
        return findings

    # Parse each PrivacyInfo.xcprivacy
    for xcp_path in sorted(xcprivacy_files):
        rel = str(xcp_path.relative_to(root))
        try:
            with open(xcp_path, "rb") as f:
                data = plistlib.load(f)
        except Exception:
            findings.append({
                "category": "privacy_manifest",
                "severity": "warning",
                "confidence": "verified",
                "message": f"Failed to parse '{rel}'",
                "file": rel,
            })
            continue

        if not isinstance(data, dict):
            continue

        # Check for required reason API entries
        api_entries = data.get("NSPrivacyAccessedAPITypes", [])
        declared_categories = set()
        if isinstance(api_entries, list):
            for entry in api_entries:
                if isinstance(entry, dict):
                    cat = entry.get("NSPrivacyAccessedAPIType", "")
                    if cat:
                        declared_categories.add(cat)

        findings.append({
            "category": "privacy_manifest",
            "severity": "info",
            "confidence": "verified",
            "message": f"Privacy manifest found at '{rel}' with "
                       f"{len(declared_categories)} required-reason API category entries",
            "file": rel,
            "declared_categories": sorted(declared_categories),
        })

    return findings


# ---------------------------------------------------------------------------
# Asset catalog sanity analyzer
# ---------------------------------------------------------------------------

def analyze_asset_catalogs(root_path):
    """Check .xcassets directories for app icon set, accent color, and dark-mode variants.

    Returns a list of finding dicts, all with confidence='verified'.
    """
    root = Path(root_path).resolve()
    findings = []

    xcassets_dirs = sorted(root.rglob("*.xcassets"))
    if not xcassets_dirs:
        return findings

    for xc_dir in xcassets_dirs:
        rel = str(xc_dir.relative_to(root))
        contents = list(xc_dir.rglob("Contents.json"))
        found_icon = False
        found_accent = False
        has_dark_variant = False
        image_sets = []

        for cj_path in contents:
            try:
                cj = json.loads(cj_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            parent_dir = cj_path.parent.name
            parent_parent = cj_path.parent.parent.name if cj_path.parent.parent != xc_dir else None

            # Detect app icon set
            if parent_dir.endswith(".appiconset"):
                found_icon = True
                images = [img.get("filename", "") for img in cj.get("images", [])]
                image_sets.append({
                    "type": "appicon",
                    "name": parent_dir,
                    "image_count": len(images),
                })

            # Detect accent color
            if parent_dir.endswith(".colorset") and "accent" in parent_dir.lower():
                found_accent = True

            # Detect dark mode variants in any asset
            for img in cj.get("images", []):
                appearances = img.get("appearances", [])
                for app in appearances:
                    if app.get("appearance") == "luminosity" and app.get("value") == "dark":
                        has_dark_variant = True

        # Report findings
        if not found_icon:
            findings.append({
                "category": "asset_catalog",
                "severity": "warning",
                "confidence": "verified",
                "message": f"Asset catalog '{rel}' has no AppIcon app icon set",
                "asset_catalog": rel,
            })

        if not found_accent:
            findings.append({
                "category": "asset_catalog",
                "severity": "info",
                "confidence": "verified",
                "message": f"Asset catalog '{rel}' has no AccentColor color set",
                "asset_catalog": rel,
            })

        if found_icon:
            findings.append({
                "category": "asset_catalog",
                "severity": "info",
                "confidence": "verified",
                "message": f"Asset catalog '{rel}' has app icon set with {len(image_sets)} icon config(s)",
                "asset_catalog": rel,
                "icon_sets": image_sets,
            })

        if has_dark_variant:
            findings.append({
                "category": "asset_catalog",
                "severity": "info",
                "confidence": "verified",
                "message": f"Asset catalog '{rel}' includes dark-mode asset variants",
                "asset_catalog": rel,
            })

    return findings


# ---------------------------------------------------------------------------
# Localization gap detector
# ---------------------------------------------------------------------------

# Patterns that suggest hardcoded user-facing strings in Swift files
HARDCODED_STRING_PATTERNS = [
    (re.compile(r'Text\("(.+?)"\)'), "SwiftUI Text"),
    (re.compile(r'Text\("""'), "SwiftUI multiline Text"),
    (re.compile(r'"(?:\w+[ ]){2,}[^"]*"'), "multi-word string literal"),
    (re.compile(r"\.alert\(\s*\"(.+?)\""), ".alert title string"),
    (re.compile(r'Button\("(.+?)"'), "SwiftUI Button label"),
    (re.compile(r'Label\("(.+?)"'), "SwiftUI Label"),
    (re.compile(r"NSLocalizedString"), "NSLocalizedString usage"),
    (re.compile(r"String\(localized:"), "String(localized:) usage"),
]


def _detect_localization_resources(root_path):
    """Scan for localization resource files and directories."""
    root = Path(root_path).resolve()
    resources = {
        "lproj_dirs": [],
        "strings_files": [],
        "stringsdict_files": [],
        "xcstrings_files": [],
    }
    for path in sorted(root.rglob("*")):
        if path.is_dir() and path.suffix.lower() == ".lproj":
            resources["lproj_dirs"].append(str(path.relative_to(root)))
        elif path.is_file():
            if path.suffix.lower() == ".strings":
                resources["strings_files"].append(str(path.relative_to(root)))
            elif path.suffix.lower() == ".stringsdict":
                resources["stringsdict_files"].append(str(path.relative_to(root)))
            elif path.suffix.lower() == ".xcstrings":
                resources["xcstrings_files"].append(str(path.relative_to(root)))
    return resources


def analyze_localization_gaps(root_path):
    """Detect hardcoded string hints vs. localization resource presence.

    Returns a list of finding dicts, all with confidence='verified'.
    """
    root = Path(root_path).resolve()
    findings = []
    loc_resources = _detect_localization_resources(root_path)

    has_resources = bool(
        loc_resources["lproj_dirs"]
        or loc_resources["strings_files"]
        or loc_resources["stringsdict_files"]
        or loc_resources["xcstrings_files"]
    )

    # Scan Swift files for hardcoded string patterns
    hardcoded_instances = []
    localized_usage = []

    for swift_file in sorted(root.rglob("*.swift")):
        try:
            content = swift_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        rel = str(swift_file.relative_to(root))

        for pattern, label in HARDCODED_STRING_PATTERNS:
            for match in pattern.finditer(content):
                line_num = content[:match.start()].count("\n") + 1
                snippet = match.group(0)[:100]

                if label in ("NSLocalizedString usage", "String(localized:) usage"):
                    localized_usage.append({
                        "file": rel,
                        "line": line_num,
                        "pattern": label,
                        "snippet": snippet,
                    })
                else:
                    hardcoded_instances.append({
                        "file": rel,
                        "line": line_num,
                        "pattern": label,
                        "snippet": snippet,
                    })

    # Cap counts to reasonable limits to keep JSON manageable
    hardcoded_summary = hardcoded_instances[:50]
    localized_summary = localized_usage[:50]

    if hardcoded_summary:
        severity = "warning" if not has_resources else "info"
        findings.append({
            "category": "localization",
            "severity": severity,
            "confidence": "verified",
            "message": (
                f"Found {len(hardcoded_instances)} hardcoded string(s) "
                f"that may need localization"
                + (". No .lproj/.strings/.xcstrings resources found!" if not has_resources else "")
            ),
            "hardcoded_count": len(hardcoded_instances),
            "localized_count": len(localized_usage),
            "example_instances": hardcoded_summary[:10],
            "has_localization_resources": has_resources,
        })
        if has_resources:
            findings.append({
                "category": "localization",
                "severity": "info",
                "confidence": "verified",
                "message": f"Localization resources found: "
                           f"{len(loc_resources['lproj_dirs'])} .lproj dir(s), "
                           f"{len(loc_resources['strings_files'])} .strings file(s), "
                           f"{len(loc_resources['xcstrings_files'])} .xcstrings file(s)",
                "resources": loc_resources,
            })
    elif has_resources:
        findings.append({
            "category": "localization",
            "severity": "info",
            "confidence": "verified",
            "message": f"Localization resources present with no obvious hardcoded strings",
            "resources": loc_resources,
        })

    return findings


# ---------------------------------------------------------------------------
# Orchestration: run all platform analyzers
# ---------------------------------------------------------------------------

def run_platform_analyzers(root_path):
    """Run all deterministic platform analyzers and return a combined result dict.

    Returns a dict with 'findings' (flat list of all finding dicts) and
    'analyzer_summaries' (per-analyzer counts).
    """
    all_findings = []
    summaries = {}

    analyzers = [
        ("permission_strings", analyze_permission_strings),
        ("entitlement_capabilities", analyze_entitlement_capabilities),
        ("privacy_manifest", analyze_privacy_manifest),
        ("asset_catalog", analyze_asset_catalogs),
        ("localization", analyze_localization_gaps),
    ]

    for name, func in analyzers:
        try:
            result = func(root_path)
            all_findings.extend(result)
            summaries[name] = {"findings_count": len(result)}
        except Exception as e:
            summaries[name] = {"findings_count": 0, "error": str(e)}

    return {
        "findings": all_findings,
        "analyzer_summaries": summaries,
    }


# ---------------------------------------------------------------------------
# JSON output helpers
# ---------------------------------------------------------------------------

# Severity mapping from finding categories and patterns
_CATEGORY_SEVERITY_DEFAULTS = {
    "permission_strings": "high",
    "entitlement_capabilities": "medium",
    "privacy_manifest": "high",
    "asset_catalog_missing_app_icon": "high",
    "asset_catalog_missing_accent": "low",
    "localization_hardcoded": "medium",
    "force_unwrap": "medium",
    "force_try": "high",
    "fatal_error": "medium",
    "todo": "low",
    "fixme": "low",
    "hack": "low",
    "image_accessibility": "high",
    "hardcoded_ui": "low",
    "view_body_size": "medium",
    "stack_depth": "low",
    "storekit_import": "info",
    "storekit_api": "info",
}

# Shipcheck risk categories and their severity thresholds
SHIPCHECK_RISK_CATEGORIES = {
    "launch_blockers": {
        "label": "Launch Blockers",
        "description": "Issues likely to cause App Store rejection or crash on launch",
        "min_severity": "critical",
        "categories": {"permission_strings", "entitlement_capabilities"},
        "finding_ids": set(),
    },
    "app_review_risks": {
        "label": "App Review Risks",
        "description": "Issues that increase App Review scrutiny or rejection risk",
        "min_severity": "high",
        "categories": {"privacy_manifest", "entitlement_capabilities"},
        "finding_ids": {"force_try", "image_accessibility", "missing_app_icon"},
    },
    "privacy_risks": {
        "label": "Privacy Risks",
        "description": "Privacy manifest, permission strings, and data-use concerns",
        "min_severity": "medium",
        "categories": {"permission_strings", "privacy_manifest"},
        "finding_ids": set(),
    },
    "storekit_risks": {
        "label": "StoreKit Risks",
        "description": "In-App Purchase, subscription, and StoreKit configuration issues",
        "min_severity": "info",
        "categories": set(),
        "finding_ids": {"storekit_import", "storekit_api", "storekit_restore"},
    },
}


def make_validation(errors=None, warnings=None, performed=None, skipped=None,
                    requires_macos=None):
    """Build the v1 validation block."""
    return {
        "performed": performed or [],
        "skipped": skipped or [],
        "requires_macos": requires_macos or [],
        "errors": errors or [],
        "warnings": warnings or [],
        "valid": len(errors or []) == 0,
    }


def _normalize_finding(f, default_severity="low"):
    """Ensure a finding dict has the unified schema fields.

    Returns a copy with category, severity, confidence, and message normalized.
    """
    nf = dict(f)
    # Ensure 'severity' exists
    if "severity" not in nf:
        fid = nf.get("finding_id", nf.get("category", ""))
        nf["severity"] = _CATEGORY_SEVERITY_DEFAULTS.get(fid, default_severity)
    # Normalize severity values from older "error"/"warning" -> "high"/"medium"
    sev = nf.get("severity", "low")
    if sev == "error":
        nf["severity"] = "high"
    elif sev == "warning":
        nf["severity"] = "medium"
    # Ensure 'message' exists (use description if needed)
    if "message" not in nf:
        nf["message"] = nf.get("description", str(nf.get("finding_id", "")))
    return nf


def _collect_all_findings(swift_heuristics, platform_analysis):
    """Combine all findings from both scan pipelines into a flat, normalized list."""
    all_findings = []

    # Platform analyzer findings (confidence: verified)
    for f in platform_analysis.get("findings", []):
        all_findings.append(_normalize_finding(f))

    # Swift heuristic findings (confidence: heuristic)
    for h in (swift_heuristics.get("heuristics") or []):
        all_findings.append(_normalize_finding(h))

    return all_findings


def _compute_severity_summary(findings):
    """Compute severity counts from a flat findings list."""
    summary = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        sev = f.get("severity", "low")
        if sev in summary:
            summary[sev] += 1
    return summary


def _build_suggested_actions(findings):
    """Generate suggested actions from findings, deduplicated by action key."""
    actions = []
    seen_actions = set()

    for f in findings:
        fid = f.get("finding_id", "")
        cat = f.get("category", "")
        sev = f.get("severity", "medium")

        # Permission string suggestions
        if cat == "permission_strings" and sev in ("high", "critical"):
            key = f"add_{f.get('missing_key', '')}"
            if key not in seen_actions:
                seen_actions.add(key)
                actions.append({
                    "id": key,
                    "title": f"Add {f.get('missing_key', 'permission string')} to Info.plist",
                    "category": "privacy",
                    "priority": sev,
                    "files": f.get("plist_files", []),
                })

        # Missing privacy manifest
        if fid == "missing_privacy_manifest":
            if "create_privacy_manifest" not in seen_actions:
                seen_actions.add("create_privacy_manifest")
                actions.append({
                    "id": "create_privacy_manifest",
                    "title": "Create PrivacyInfo.xcprivacy manifest",
                    "category": "privacy",
                    "priority": "high",
                    "files": ["PrivacyInfo.xcprivacy"],
                })

        # Missing app icon
        if fid == "missing_app_icon" and "add_app_icon" not in seen_actions:
            seen_actions.add("add_app_icon")
            actions.append({
                "id": "add_app_icon",
                "title": "Add an app icon set to the asset catalog",
                "category": "release",
                "priority": "high",
                "files": [],
            })

        # Image accessibility
        if fid in ("image_without_label", "sf_symbol_no_label"):
            key = f"a11y_{f.get('file', '')}"
            if key not in seen_actions:
                seen_actions.add(key)
                actions.append({
                    "id": key,
                    "title": f"Add accessibility labels to images in {f.get('file', 'unknown')}",
                    "category": "accessibility",
                    "priority": sev,
                    "files": [f.get("file", "")],
                })

        # Force unwrap/try patterns
        if fid in ("force_unwrap", "force_try"):
            key = f"safe_{fid}_{f.get('file', '')}"
            if key not in seen_actions:
                seen_actions.add(key)
                actions.append({
                    "id": key,
                    "title": f"Replace {fid.replace('_', ' ')} with safe unwrap in "
                             f"{f.get('file', 'unknown')}",
                    "category": "architecture",
                    "priority": sev,
                    "files": [f.get("file", "")],
                })

        # Large view body
        if fid == "large_view_body":
            key = f"extract_view_{f.get('file', '')}"
            if key not in seen_actions:
                seen_actions.add(key)
                actions.append({
                    "id": key,
                    "title": f"Extract subviews from large body in {f.get('file', 'unknown')}",
                    "category": "architecture",
                    "priority": "medium",
                    "files": [f.get("file", "")],
                })

    return actions


def _classify_shipcheck_findings(findings):
    """Classify findings into shipcheck risk categories.

    Returns a dict with keys: launch_blockers, app_review_risks, privacy_risks,
    storekit_risks, each containing the relevant findings.
    """
    buckets = {key: [] for key in SHIPCHECK_RISK_CATEGORIES}
    severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}

    for f in findings:
        fid = f.get("finding_id", "")
        cat = f.get("category", "")
        sev = f.get("severity", "low")

        for bucket_name, rules in SHIPCHECK_RISK_CATEGORIES.items():
            match = False
            if cat in rules["categories"]:
                match = True
            elif fid in rules["finding_ids"]:
                match = True
            elif sev == "critical" and bucket_name == "launch_blockers":
                match = True

            if match:
                buckets[bucket_name].append(f)
                break  # put in first matching bucket
        else:
            # Any remaining finding goes to app_review_risks by default
            buckets["app_review_risks"].append(f)

    return buckets


def _count_shipcheck_severities(bucket_findings):
    """Count severities within a shipcheck bucket."""
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in bucket_findings:
        sev = f.get("severity", "low")
        if sev in counts:
            counts[sev] += 1
    return counts


# ---------------------------------------------------------------------------
# Shared analysis pipeline
# ---------------------------------------------------------------------------

def _run_analysis_pipeline(root_path, target_path=None):
    """Run the full analysis pipeline and return raw data.

    Returns a dict with: env, project, warnings, errors, swift_heuristics,
    platform_analysis, performed_checks, skipped_checks.
    """
    warnings = []
    errors = []
    performed_checks = []
    skipped_checks = []

    root = Path(root_path).resolve()
    effective_root = target_path or str(root)

    if not root.is_dir():
        errors.append(f"Root path '{root_path}' is not a valid directory")

    env = detect_environment()
    proj_type = detect_project_type(str(root))

    # Initialize project data
    project = {
        "root": str(root),
        "type": proj_type["type"],
        "type_details": proj_type.get("details", ""),
    }

    dir_scan = None
    xcode_data = None

    if proj_type["type"] == "xcode":
        performed_checks.append("xcode_project_scan")
        xcode_data, dir_scan = analyze_xcode_project(
            str(root), proj_type.get("xcodeproj_paths", [])
        )
        project["targets"] = xcode_data["targets"]
        if xcode_data["warnings"]:
            warnings.extend(xcode_data["warnings"])
        if not xcode_data["pbxproj_parse_success"]:
            warnings.append("pbxproj parse failed; falling back to directory scan")

    elif proj_type["type"] == "xcode_workspace":
        performed_checks.append("directory_scan")
        skipped_checks.append("deep_workspace_analysis")
        dir_scan = directory_scan(str(root))
        warnings.append("Xcode workspace analysis is limited in v1; scanning files only")

    elif proj_type["type"] == "spm":
        performed_checks.append("spm_detection")
        dir_scan = directory_scan(str(root))
        project["package_swift_path"] = "Package.swift"

    elif proj_type["type"] == "flat":
        performed_checks.append("directory_scan")
        dir_scan = directory_scan(str(root))
        if proj_type.get("swift_file_count", 0) == 0:
            warnings.append("No Swift files found in directory")

    # Merge directory scan into project
    if dir_scan:
        project["swift_file_count"] = dir_scan["total_swift_file_count"]
        project["swift_files"] = dir_scan["swift_files"]
        if dir_scan["plist_files"]:
            project["plist_files"] = dir_scan["plist_files"]
        if dir_scan["entitlement_files"]:
            project["entitlement_files"] = dir_scan["entitlement_files"]
        if dir_scan["xcprivacy_files"]:
            project["xcprivacy_files"] = dir_scan["xcprivacy_files"]
        if dir_scan["xcconfig_files"]:
            project["xcconfig_files"] = dir_scan["xcconfig_files"]
        if dir_scan["asset_catalogs"]:
            project["asset_catalogs"] = dir_scan["asset_catalogs"]

    # Plist analysis
    plist_findings, plist_warnings = analyze_plists(str(root))
    if plist_findings:
        project["plist_analysis"] = plist_findings
    warnings.extend(plist_warnings)

    # Swift heuristic scan
    performed_checks.append("swift_heuristic_scan")
    swift_findings = analyze_swift_files(str(root))
    if swift_findings["heuristics"]:
        project["swift_heuristics"] = swift_findings

    # Platform analyzers (deterministic, confidence='verified')
    performed_checks.append("platform_analysis")
    platform_analysis = run_platform_analyzers(str(root))
    project["platform_analysis"] = platform_analysis

    # MacOS-required checks that cannot be performed
    if not env.get("is_macos"):
        skipped_checks.extend([
            "xcodebuild_validation",
            "simulator_testing",
            "swiftui_preview_verification",
            "signing_validation",
        ])

    return {
        "env": env,
        "project": project,
        "warnings": warnings,
        "errors": errors,
        "swift_heuristics": swift_findings,
        "platform_analysis": platform_analysis,
        "performed_checks": performed_checks,
        "skipped_checks": skipped_checks,
    }


def _build_unified_output(raw, command_name):
    """Build the unified JSON output for any subcommand."""
    all_findings = _collect_all_findings(
        raw["swift_heuristics"], raw["platform_analysis"]
    )
    summary = _compute_severity_summary(all_findings)
    suggested_actions = _build_suggested_actions(all_findings)

    requires_macos = []
    if not raw["env"].get("is_macos"):
        requires_macos = [
            "Build and test with xcodebuild",
            "Run on iOS Simulator / device",
            "Verify SwiftUI previews render correctly",
            "Validate code signing and provisioning profiles",
            "Test StoreKit transactions with StoreKit Testing",
        ]

    output = {
        "schema_version": SCHEMA_VERSION,
        "command": command_name,
        "environment": raw["env"],
        "project": raw["project"],
        "findings": all_findings,
        "suggested_actions": suggested_actions,
        "summary": summary,
        "validation": make_validation(
            errors=raw["errors"],
            warnings=raw["warnings"],
            performed=raw["performed_checks"],
            skipped=raw["skipped_checks"],
            requires_macos=requires_macos,
        ),
    }

    return output


# ---------------------------------------------------------------------------
# Scan subcommand
# ---------------------------------------------------------------------------

def cmd_scan(root_path):
    """Execute the scan subcommand."""
    raw = _run_analysis_pipeline(root_path)
    return _build_unified_output(raw, "scan")


# ---------------------------------------------------------------------------
# Audit subcommand
# ---------------------------------------------------------------------------

def cmd_audit(root_path, target_path=None):
    """Execute the audit subcommand — scoped re-run of all analyzers.

    If target_path is provided, findings are filtered to files within that subdirectory.
    """
    raw = _run_analysis_pipeline(root_path, target_path=target_path)
    output = _build_unified_output(raw, "audit")

    if target_path:
        output["audit_scope"] = {"target": target_path}
        # Filter findings to those within the target path
        target = Path(target_path).resolve()
        filtered = []
        for f in output["findings"]:
            ffile = f.get("file", "")
            if ffile:
                abs_file = Path(root_path).resolve() / ffile
                try:
                    abs_file.relative_to(target)
                    filtered.append(f)
                except ValueError:
                    continue
            else:
                # Findings without a file field are project-level (keep them)
                filtered.append(f)
        output["findings"] = filtered
        output["summary"] = _compute_severity_summary(filtered)

    return output


# ---------------------------------------------------------------------------
# Shipcheck subcommand
# ---------------------------------------------------------------------------

def cmd_shipcheck(root_path):
    """Execute the shipcheck subcommand — launch-readiness report."""
    raw = _run_analysis_pipeline(root_path)
    output = _build_unified_output(raw, "shipcheck")

    # Classify findings into shipcheck risk categories
    buckets = _classify_shipcheck_findings(output["findings"])
    shipcheck_report = {}
    for bucket_name, bucket_findings in buckets.items():
        rules = SHIPCHECK_RISK_CATEGORIES[bucket_name]
        shipcheck_report[bucket_name] = {
            "label": rules["label"],
            "description": rules["description"],
            "severity_counts": _count_shipcheck_severities(bucket_findings),
            "count": len(bucket_findings),
            "findings": bucket_findings,
        }

    # Compute a weighted risk score (0-100, higher = riskier)
    severity_weight = {"critical": 25, "high": 10, "medium": 4, "low": 1, "info": 0}
    risk_score = 0
    for f in output["findings"]:
        risk_score += severity_weight.get(f.get("severity", "low"), 0)
    risk_score = min(100, risk_score)

    # Shipcheck severity assessment
    if risk_score >= 50:
        assessment = "high_risk"
        assessment_message = "Multiple high-severity issues detected. App Store submission is likely to be rejected."
    elif risk_score >= 20:
        assessment = "moderate_risk"
        assessment_message = "Several issues need attention before submission. Review required."
    elif risk_score >= 5:
        assessment = "low_risk"
        assessment_message = "Minor issues found. Review and address before submission."
    else:
        assessment = "clean"
        assessment_message = "No significant issues detected."

    shipcheck_report["risk_score"] = risk_score
    shipcheck_report["assessment"] = assessment
    shipcheck_report["assessment_message"] = assessment_message

    output["shipcheck"] = shipcheck_report
    return output


# ---------------------------------------------------------------------------
# Validate subcommand
# ---------------------------------------------------------------------------

def cmd_validate(root_path):
    """Execute the validate subcommand — post-edit validation.

    Same analysis as scan but semantically labeled for post-edit reporting.
    """
    raw = _run_analysis_pipeline(root_path)
    output = _build_unified_output(raw, "validate")
    return output


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser():
    """Build the argparse parser."""
    parser = argparse.ArgumentParser(
        prog="apple-agent",
        description="Apple Project Agent CLI - v1 deterministic static analysis for Apple projects",
    )
    parser.add_argument(
        "--version", action="version", version=f"apple-agent v{SCHEMA_VERSION}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # scan
    scan_parser = subparsers.add_parser("scan", help="Scan an Apple project")
    scan_parser.add_argument(
        "--root", required=True, help="Root directory of the Apple project"
    )
    scan_parser.add_argument(
        "--json", action="store_true", default=True, help="Output structured JSON"
    )

    # audit
    audit_parser = subparsers.add_parser("audit", help="Audit an Apple project")
    audit_parser.add_argument(
        "--root", required=True, help="Root directory of the Apple project"
    )
    audit_parser.add_argument(
        "--target", default=None, help="Scope audit to a specific subdirectory"
    )
    audit_parser.add_argument(
        "--json", action="store_true", default=True, help="Output structured JSON"
    )

    # shipcheck
    shipcheck_parser = subparsers.add_parser(
        "shipcheck", help="Check App Store ship readiness"
    )
    shipcheck_parser.add_argument(
        "--root", required=True, help="Root directory of the Apple project"
    )
    shipcheck_parser.add_argument(
        "--json", action="store_true", default=True, help="Output structured JSON"
    )

    # validate
    validate_parser = subparsers.add_parser(
        "validate", help="Validate post-edit state"
    )
    validate_parser.add_argument(
        "--root", required=True, help="Root directory of the Apple project"
    )
    validate_parser.add_argument(
        "--json", action="store_true", default=True, help="Output structured JSON"
    )

    return parser


def main():
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "scan":
        result = cmd_scan(args.root)
    elif args.command == "audit":
        result = cmd_audit(args.root, target_path=getattr(args, "target", None))
    elif args.command == "shipcheck":
        result = cmd_shipcheck(args.root)
    elif args.command == "validate":
        result = cmd_validate(args.root)
    else:
        print(json.dumps({"error": f"Unknown command: {args.command}"}, indent=2))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

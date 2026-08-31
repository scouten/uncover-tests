#!/usr/bin/env python3
"""Regression tests for filter_lcov.py.

Run with: python3 -m unittest test_filter_lcov -v
"""

import io
import os
import tempfile
import unittest
from unittest import mock

import filter_lcov

RUST_FILE_WITH_TEST_MOD = """\
pub fn covered() -> u32 {
    42
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn it_works() {
        assert_eq!(covered(), 42);
    }
}
"""


class NormalizePathTests(unittest.TestCase):
    def test_posix_path_under_src(self):
        self.assertEqual(
            filter_lcov.normalize_path("/home/user/repo/parser/src/content/quotes.rs"),
            "/src/content/quotes.rs",
        )

    def test_windows_path_under_src(self):
        # Windows paths use backslashes in both os.walk results and LCOV SF:
        # records; they must normalize identically to POSIX paths.
        self.assertEqual(
            filter_lcov.normalize_path(
                r"C:\work\repo\parser\src\content\quotes.rs"
            ),
            "/src/content/quotes.rs",
        )

    def test_windows_and_posix_paths_agree(self):
        # Cross-platform Codecov merging depends on both platforms producing
        # the same key for the same file.
        self.assertEqual(
            filter_lcov.normalize_path(r"D:\a\repo\parser\src\tests\subs\quotes.rs"),
            filter_lcov.normalize_path("/home/u/repo/parser/src/tests/subs/quotes.rs"),
        )

    def test_windows_basename_collision(self):
        # Two files sharing a basename in different directories must keep
        # distinct keys. Before the backslash fix, both collapsed to
        # "quotes.rs" and one file's test-module ranges were silently lost.
        a = filter_lcov.normalize_path(
            r"C:\repo\parser\src\content\inline_builder\quotes.rs"
        )
        b = filter_lcov.normalize_path(
            r"C:\repo\parser\src\tests\asciidoc_lang\subs\quotes.rs"
        )
        self.assertNotEqual(a, b)
        self.assertEqual(a, "/src/content/inline_builder/quotes.rs")
        self.assertEqual(b, "/src/tests/asciidoc_lang/subs/quotes.rs")

    def test_path_outside_src_falls_back_to_basename(self):
        self.assertEqual(filter_lcov.normalize_path("/repo/build.rs"), "build.rs")
        self.assertEqual(filter_lcov.normalize_path(r"C:\repo\build.rs"), "build.rs")


class FindTestModuleRangesTests(unittest.TestCase):
    def test_same_basename_in_two_directories(self):
        # Regression test for the Windows basename collision: two files named
        # quotes.rs in different directories must each contribute their own
        # test-module ranges.
        with tempfile.TemporaryDirectory() as root:
            src = os.path.join(root, "parser", "src")
            for subdir in ("content", os.path.join("tests", "subs")):
                d = os.path.join(src, subdir)
                os.makedirs(d)
                with open(os.path.join(d, "quotes.rs"), "w", encoding="utf-8") as f:
                    f.write(RUST_FILE_WITH_TEST_MOD)

            with mock.patch.object(filter_lcov, "SRC_DIRS", [src]):
                ranges = filter_lcov.find_test_module_ranges()

            self.assertEqual(
                sorted(ranges),
                ["/src/content/quotes.rs", "/src/tests/subs/quotes.rs"],
            )
            for key in ranges:
                self.assertEqual(len(ranges[key]), 1)


class FilterLcovTests(unittest.TestCase):
    def filter(self, lcov_text, test_funcs=None, test_mod_ranges=None):
        outfile = io.StringIO()
        stats = filter_lcov.filter_lcov(
            io.StringIO(lcov_text),
            outfile,
            test_funcs or set(),
            test_mod_ranges or {},
        )
        return outfile.getvalue(), stats

    def test_windows_sf_path_matches_test_module_ranges(self):
        # The SF: path (Windows-style) and the range-dict key (derived from
        # os.walk) must land on the same normalized key so the DA lines inside
        # the test module are stripped.
        lcov = (
            "SF:C:\\repo\\parser\\src\\content\\quotes.rs\n"
            "DA:2,1\n"
            "DA:10,0\n"
            "end_of_record\n"
        )
        ranges = {"/src/content/quotes.rs": [(5, 13)]}

        output, (_, _, excluded_lines) = self.filter(lcov, test_mod_ranges=ranges)

        self.assertIn("DA:2,1\n", output)
        self.assertNotIn("DA:10,0\n", output)
        self.assertEqual(excluded_lines, 1)

    def test_windows_sf_path_under_tests_dir_is_skipped(self):
        lcov = (
            "SF:C:\\repo\\parser\\src\\tests\\subs\\quotes.rs\n"
            "DA:2,1\n"
            "end_of_record\n"
            "SF:C:\\repo\\parser\\src\\content\\other.rs\n"
            "DA:1,1\n"
            "end_of_record\n"
        )

        output, (excluded_files, _, _) = self.filter(lcov)

        self.assertEqual(excluded_files, {"/src/tests/subs/quotes.rs"})
        self.assertNotIn("DA:2,1\n", output)
        self.assertIn("DA:1,1\n", output)


if __name__ == "__main__":
    unittest.main()

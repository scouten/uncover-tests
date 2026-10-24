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


RUST_FILE_WITH_PUB_CRATE_TEST_MOD = """\
pub fn covered() -> u32 {
    42
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;

    pub(crate) fn response_der(status: u8) -> Vec<u8> {
        #[derive(Debug)]
        struct Status {
            code: u8,
        }
        vec![Status { code: status }.code]
    }

    #[test]
    fn it_works() {
        assert_eq!(covered(), 42);
        assert_eq!(response_der(1), vec![1]);
    }
}
"""


class ModDefPatternTests(unittest.TestCase):
    def test_matches_visibility_qualified_mod_tests(self):
        # Regression test for issue #2: `#[cfg(test)]` modules declared with a
        # visibility qualifier must be recognized, not just a bare `mod tests`.
        for line in (
            "mod tests {",
            "    mod tests {",
            "pub mod tests {",
            "pub(crate) mod tests {",
            "pub(super) mod tests {",
            "pub(self) mod tests {",
            "pub(in crate::foo) mod tests {",
            "    pub(crate)  mod  tests  {",
            "pub (crate) mod tests {",
        ):
            with self.subTest(line=line):
                self.assertIsNotNone(filter_lcov.MOD_DEF_PATTERN.match(line))

    def test_does_not_match_other_modules(self):
        for line in (
            "mod test_utils {",
            "pub(crate) mod helpers {",
            "mod tests;",
            "pub use tests::*;",
            "// mod tests {",
        ):
            with self.subTest(line=line):
                self.assertIsNone(filter_lcov.MOD_DEF_PATTERN.match(line))


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

    def test_pub_crate_mod_tests_is_recognized(self):
        # Regression test for issue #2: a `pub(crate) mod tests` block under
        # `#[cfg(test)]` must produce a range covering the whole module,
        # including non-#[test] helpers and nested declarations.
        with tempfile.TemporaryDirectory() as root:
            src = os.path.join(root, "crate", "src")
            os.makedirs(src)
            with open(os.path.join(src, "response.rs"), "w", encoding="utf-8") as f:
                f.write(RUST_FILE_WITH_PUB_CRATE_TEST_MOD)

            with mock.patch.object(filter_lcov, "SRC_DIRS", [src]):
                ranges = filter_lcov.find_test_module_ranges()

        # `mod tests {` is on line 6; the module body spans lines 7-22,
        # ending on the closing brace.
        self.assertEqual(ranges, {"/src/response.rs": [(7, 22)]})

        # The helper function and its nested struct fall inside the range.
        self.assertTrue(filter_lcov.in_test_module("/src/response.rs", 9, ranges))
        self.assertTrue(filter_lcov.in_test_module("/src/response.rs", 11, ranges))
        # The covered() function above the module does not.
        self.assertFalse(filter_lcov.in_test_module("/src/response.rs", 2, ranges))


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

    def test_pub_crate_mod_tests_helper_is_stripped_end_to_end(self):
        # Regression test for issue #2, exercising the whole pipeline: the
        # range discovered from a `pub(crate) mod tests` block must strip the
        # FN/FNDA/DA records of a non-#[test] helper defined inside it.
        with tempfile.TemporaryDirectory() as root:
            src = os.path.join(root, "crate", "src")
            os.makedirs(src)
            rs_path = os.path.join(src, "response.rs")
            with open(rs_path, "w", encoding="utf-8") as f:
                f.write(RUST_FILE_WITH_PUB_CRATE_TEST_MOD)

            with mock.patch.object(filter_lcov, "SRC_DIRS", [src]):
                test_funcs = filter_lcov.find_test_functions()
                ranges = filter_lcov.find_test_module_ranges()

            lcov = (
                f"SF:{rs_path}\n"
                "FN:1,covered\n"
                "FNDA:1,covered\n"
                "FN:9,response_der\n"
                "FNDA:1,response_der\n"
                "FN:18,it_works\n"
                "FNDA:1,it_works\n"
                "DA:1,1\n"
                "DA:2,1\n"
                "DA:9,1\n"
                "DA:14,1\n"
                "DA:20,1\n"
                "end_of_record\n"
            )

        output, (_, excluded_fns, excluded_lines) = self.filter(
            lcov, test_funcs=test_funcs, test_mod_ranges=ranges
        )

        self.assertIn("FN:1,covered\n", output)
        self.assertIn("FNDA:1,covered\n", output)
        self.assertIn("DA:1,1\n", output)
        self.assertIn("DA:2,1\n", output)

        self.assertNotIn("response_der", output)
        self.assertNotIn("it_works", output)
        self.assertNotIn("DA:9,1\n", output)
        self.assertNotIn("DA:14,1\n", output)
        self.assertNotIn("DA:20,1\n", output)

        self.assertEqual(excluded_fns, 4)
        self.assertEqual(excluded_lines, 3)


if __name__ == "__main__":
    unittest.main()

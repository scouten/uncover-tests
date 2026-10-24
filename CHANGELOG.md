# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.2](https://github.com/scouten/uncover-tests/compare/v1.1.1...v1.1.2)
_24 October 2026_

## Fixed

* Recognize `#[cfg(test)]` modules declared with a visibility qualifier (`pub mod tests`, `pub(crate) mod tests`, etc.) so their helper code is excluded from LCOV ([#2](https://github.com/scouten/uncover-tests/issues/2))
* Strip the `FNDA:` record of a non-`#[test]` function inside a test module along with its `FN:` record, instead of leaving an orphaned `FNDA:` line in the output

## [1.1.1](https://github.com/scouten/uncover-tests/compare/v1.1.0...v1.1.1)
_31 August 2026_

## Fixed

* Fix Windows path handling: normalize backslashes so files sharing a basename in different directories no longer collide, and test modules are stripped from Windows-generated LCOV reports

## [1.1.0](https://github.com/scouten/asciidoc-parser/compare/v1.1.0...v1.0.1)
_19 October 2025_

## Added

* Add option to delete unfiltered LCOV output file

## [1.0.1](https://github.com/scouten/asciidoc-parser/compare/v1.0.1...v1.0.0)
_19 October 2025_

## Fixed

* Fix crate root search

## 1.0.0
_19 October 2025_

* Initial release

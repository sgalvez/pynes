# Release Notes

This directory contains the permanent release notes used by the GitHub Release
workflow. Each version tag should have a matching `docs/releases/vX.Y.Z.md`
file before the tag is pushed.

## Versions

| Version | Date | Summary |
| --- | --- | --- |
| [v0.0.7](v0.0.7.md) | 2026-07-01 | Fix scaled Windows rendering crash |
| [v0.0.6](v0.0.6.md) | 2026-07-01 | Improve emulator frame performance |
| [v0.0.5](v0.0.5.md) | 2026-07-01 | Cache scrolled backgrounds for faster rendering |
| [v0.0.4](v0.0.4.md) | 2026-07-01 | Render scrolled backgrounds and smooth audio |
| [v0.0.3](v0.0.3.md) | 2026-07-01 | Render sprites and improve APU mixing |
| [v0.0.2](v0.0.2.md) | 2026-07-01 | Improve frame pacing and add pulse audio |
| [v0.0.1](v0.0.1.md) | 2026-07-01 | Initial emulator, packaging, and release workflow |

## Release Checklist

- Update or add `docs/releases/vX.Y.Z.md`.
- Confirm the release workflow can read that file through
  `docs/releases/${{ github.ref_name }}.md`.
- Push the matching `vX.Y.Z` tag only after the release notes are present on
  the target commit.

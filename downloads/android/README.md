# Android pilot download

- APK: `docket-debug.apk`
- Version: `0.5.3-email-fixes` (code `8`)
- Package: `in.docket.app`
- Minimum Android: 8.0 / API 26
- Signing: local pilot debug certificate; not a Play release
- Integrity: verify against `SHA256SUMS.txt`

[Installation and backend connection](../../docs/android-installation.md). Sample exploration works offline. Business accounts and incoming email require a running backend. This private repository's files can be downloaded by people with repository access.

This binary was built from the restored 0.5.3 Android source in commit `fe00bd4`; subsequent changes in this PR affect CI and documentation only. No accounts, customer notices, provider keys or local databases are included in the APK. CI verifies the binary's checksum, signature and version and independently builds/tests the source.

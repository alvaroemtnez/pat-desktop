# Verifying a download

Every release has `SHA256SUMS`, listing a checksum for each file, and
`SHA256SUMS.asc`, a signature over that list made with the Pat Desktop release
key.

```sh
# Once: import the release key (docs/pat-desktop-release-key.asc in the repository).
gpg --import pat-desktop-release-key.asc

# For each download, in the folder holding the files:
gpg --verify SHA256SUMS.asc SHA256SUMS
sha256sum --check --ignore-missing SHA256SUMS
```

The first command must report a good signature from the release key below, the
second `OK` for every file you downloaded.

**Release key fingerprint:** `D9BE 461F 96BC 1C9D 4D1E  BB2E 0657 C64F C6CD 6C62`
(ed25519, `Pat Desktop releases <support@alvaroedo.io>`, expires 2031-11-12)

An AppImage updated by Gear Lever or AppImageUpdate is checked against the
`.zsync` file of the release, which `SHA256SUMS` covers.

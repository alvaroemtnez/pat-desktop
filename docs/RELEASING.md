# Releasing

## Routine

1. **Record changes as you go** under `## [Unreleased]` in `CHANGELOG.md`, using
   *Added*, *Changed* and *Fixed* subsections. If the release updates Pat, say so
   ("Update Pat to v1.0.1").

2. **Build and test locally:**

   ```sh
   tools/build-flatpak.sh
   podman run --rm -v "$PWD:/src:Z" -w /src docker.io/library/golang:1-bookworm \
       sh -c 'git config --global --add safe.directory /src && tools/build-appimage.sh'
   flatpak install --user dist/Pat_Desktop-*.flatpak
   ```

   Both files land in `dist/`, which is ignored by git.

3. **Cut the release** once testing passes:

   ```sh
   tools/bump-version.py X.Y.Z        # optional second argument: release date
   git diff                           # CHANGELOG.md, metainfo, VERSION
   git commit -am "Release X.Y.Z"
   git tag -a vX.Y.Z -m "Pat Desktop X.Y.Z"
   git push && git push origin vX.Y.Z
   ```

   `bump-version.py` moves the `[Unreleased]` entries into a `[X.Y.Z] - date`
   section, sets `VERSION` in `pat_desktop/__init__.py`, and adds the matching
   `<release>` to the AppStream metainfo, which software centres show for the
   Flatpak.

4. **The tag publishes the release.** The *Release* workflow:
   - checks that the tag, `VERSION`, the changelog and the metainfo all agree
     (`tools/changelog.py check vX.Y.Z`), and stops otherwise;
   - builds the Flatpak bundle and the AppImage;
   - creates the Forgejo release. The notes are that version's `CHANGELOG.md`
     section plus install instructions. The assets are the `.flatpak`, the
     `.AppImage` and `SHA256SUMS`.

## Upstream Pat updates

The weekly *Update Pat* workflow (or `tools/update-pat.py` by hand) opens a pull
request that re-pins Pat when upstream tags a release. Review the upstream
release notes, merge, add a changelog entry, and release as above. The Flatpak
manifest is the only place Pat is pinned. The AppImage build reads the same pin.

## CI setup (once)

The workflows use `runs-on: docker`. The Flatpak jobs need a privileged
container, because flatpak-builder uses bubblewrap. In the Forgejo runner's
`config.yml`:

```yaml
container:
  privileged: true
```

Register the runner with a `docker` label, or edit `runs-on` in
`.forgejo/workflows/*.yml`.

Optional secret: `FORGEJO_TOKEN`, a personal access token with repository write
access. With it, the *Update Pat* pull requests trigger CI. Pushes made with the
automatic token don't.

## If we go to Flathub later

What we found when we looked into it (October 2026):

- **App ID:** the domain in the ID must be one we control, or upstream must
  give explicit permission. `io.getpat.*` is upstream's domain. IDs ending in
  `.desktop` are rejected outright.
- **AI policy:** Flathub requires disclosure of AI-generated code, which the
  README already has. It does not accept AI-generated or AI-assisted manifests,
  so the Flathub manifest would have to be written by hand. The manifest in
  `build-aux/flatpak/` could no longer be used there.
- **Web wrappers:** "simple web wrapper applications ... without providing
  significant polish, functionality, or meaningful desktop integration" are
  rejected. The case for us: Pat Desktop ships and manages the whole Pat
  backend.
- **Trademarks:** the app name and icon must not violate trademarks. Asking
  LA5NTA for permission would settle this and the app ID together.
- Everything else (build from source, offline Go modules, licenses, metainfo)
  already passes `flatpak-builder-lint`.

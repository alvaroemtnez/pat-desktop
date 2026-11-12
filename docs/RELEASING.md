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

4. **The tag publishes the releases.** The *Release* workflow:
   - checks that the tag, `VERSION`, the changelog and the metainfo all agree
     (`tools/changelog.py check vX.Y.Z`), and stops otherwise;
   - builds the Flatpak bundle and the AppImage;
   - creates the Forgejo release. The notes are that version's `CHANGELOG.md`
     section plus install instructions. The assets are the `.flatpak`, the
     `.AppImage` and `SHA256SUMS`;
   - creates the same release, with the same files, on the GitHub mirror, once
     the mirror has received the tag (see below).

   `tools/publish-release.py` does the publishing. If a run fails halfway,
   re-run the job: existing releases are reused and only missing files are
   uploaded.

## Betas

A beta is a pre-release of the next version, for testing before it goes out:

```sh
tools/bump-version.py X.Y.Z-beta.N     # N from 1; sets VERSION only
git commit -am "Beta X.Y.Z-beta.N"
git tag -a vX.Y.Z-beta.N -m "Pat Desktop X.Y.Z-beta.N"
git push && git push origin vX.Y.Z-beta.N
```

The *Release* workflow builds and publishes it like a release
(`Pat_Desktop-X.Y.Z-beta.N-…`), marked as a pre-release on Forgejo and GitHub, so
anything that follows the latest release (GitHub's "latest", Obtainium without
*Include prereleases*) keeps offering the last release. Its notes are the
`[Unreleased]` entries under a "Pre-release of X.Y.Z" line, so that section must
not be empty; the beta gets no changelog section and no metainfo `<release>` of
its own. When it is good, release X.Y.Z as usual: `bump-version.py X.Y.Z` turns
those same entries into its section. `tools/changelog.py check` refuses a beta of
a version that is already released.

`python3 -m unittest discover -s tools -p 'test_*.py'` tests these rules (CI runs it).

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

## GitHub mirror (once)

The repository is push-mirrored from Forgejo to
<https://github.com/alvaroemtnez/pat-desktop>. Releases are built once, on
Forgejo, and the same files are published on both, so checksums match.

1. In the Forgejo mirror settings, enable **Sync when commits are pushed**, so
   tags reach GitHub right away. The release job waits up to 15 minutes for
   the tag to appear on GitHub. Creating the release first would make GitHub
   create its own tag, which would conflict with the mirrored one.
2. On GitHub, create a fine-grained personal access token limited to
   `alvaroemtnez/pat-desktop`, with **Contents: Read and write**.
3. In the Forgejo repository settings, add it as the Actions secret
   `GH_RELEASE_TOKEN`. To mirror to a different repository, set the Actions
   variable `GH_REPO` (default `alvaroemtnez/pat-desktop`).

Without the secret, releases are only published on Forgejo. GitHub Actions
never runs: the workflows live in `.forgejo/`, which GitHub ignores.

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

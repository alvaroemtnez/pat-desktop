# Publishing guide

How Pat Desktop goes from a tag on Forgejo to Flathub. Steps 1–4 happen once.
Step 5 is the routine for every release.

## 1. Blockers to resolve before submitting

Flathub will reject the app as it stands today:

1. **The app ID `io.getpat.desktop` is not accepted.**
   - IDs must not end in `.desktop`. The linter fails with
     `appid-ends-with-lowercase-desktop`.
   - The domain in the ID has to be under your control. getpat.io belongs
     to upstream, so third parties need upstream's explicit permission.

   Options:
   - **Ask LA5NTA.** With permission (they would host the verification token
     on getpat.io), use something like `io.getpat.PatDesktop`. This also covers
     the trademark rule ("name or icon must not violate any trademarks") and
     the official icon.
   - **Use a domain you control**, e.g. the one your Forgejo runs on:
     `tld.yourdomain.PatDesktop`. You can only verify a domain you own.

   Then run `tools/rename-app-id.sh NEW_ID`, rebuild, and review the diff.
   Once the linter passes, remove `continue-on-error` from the lint step in
   `.forgejo/workflows/ci.yml`.

2. **Placeholder URLs.** Replace `https://git.example.com/alvaroemtnez/pat-desktop`
   in `data/*.metainfo.xml` with the real public repository URL. Screenshot
   URLs must be publicly reachable. Add a `<developer id="...">` (reverse DNS
   of your domain, e.g. `tld.yourdomain`). The linter treats a missing ID as
   an error.

3. **AI policy.** Flathub requires disclosure of AI-generated code and
   **does not accept AI-generated or AI-assisted manifests**. The README already
   has the disclosure. Write the Flathub manifest yourself (step 3). The manifest
   in `build-aux/flatpak/` is for local builds and CI only.

4. **Web-wrapper policy.** Flathub rejects "simple web wrapper applications
   that embed local or remote content in a web engine without providing
   significant polish, functionality, or meaningful desktop integration". Pat
   Desktop ships and manages the whole Pat application, not a website. Make
   that case in the submission: bundled backend, process lifecycle, native
   dialogs, notifications and popups.

5. **Repository must be public**, and tags must stay reachable forever. Flathub
   fetches the source from your Forgejo at build time.

## 2. Verify locally

```sh
flatpak run org.flatpak.Builder --user --install --install-deps-from=flathub \
    --force-clean --repo=repo build-dir build-aux/flatpak/APP_ID.yml
flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest build-aux/flatpak/APP_ID.yml
flatpak run --command=flatpak-builder-lint org.flatpak.Builder repo repo
```

Both lint runs should report no errors.

## 3. Submit to Flathub (once)

1. Tag a release on Forgejo (step 5) so a public tag exists.
2. Write the Flathub manifest **by hand**, in YAML, named `APP_ID.yml`. It needs
   to build three modules: libax25, Pat from `https://github.com/la5nta/pat.git`
   with the Go modules from `pat-go-vendor.json`, and this repository as a
   `type: git` source. For both git sources, write `url:`, `tag:` and `commit:`
   in that order: `tools/flathub-bump.py` relies on it. The Flatpak docs on
   [manifests](https://docs.flatpak.org/en/latest/manifests.html) and the
   [Flathub submission guide](https://docs.flathub.org/docs/for-app-authors/submission)
   cover the format.
3. Fork <https://github.com/flathub/flathub>. Create a branch **from `new-pr`**
   and add your manifest, `pat-go-vendor.json` and `pat-modules.txt`. Open a PR
   **against `new-pr`** titled `Add APP_ID`. Answer the PR template's questions,
   including the AI disclosure and the unofficial/unaffiliated status.
4. Comment `bot, build` to trigger a test build, then address review comments.
5. Once it is merged, Flathub creates `github.com/flathub/APP_ID` and invites
   you. Accept the invite and enable 2FA on GitHub, which Flathub requires.
6. Verify the app on flathub.org (developer portal → your app → Verification):
   publish the token at `https://yourdomain/.well-known/org.flathub.VerifiedApps.txt`.

## 4. Set up the automation (once)

**Forgejo runner.** The workflows use `runs-on: docker` and a privileged
container, because flatpak-builder needs bubblewrap. In the runner's
`config.yml`:

```yaml
container:
  privileged: true
```

Register the runner with a `docker` label, or edit `runs-on` in
`.forgejo/workflows/*.yml`.

**Secrets and variables** (repository → Settings → Actions):

| Name | Kind | Value |
|---|---|---|
| `FLATHUB_TOKEN` | secret | GitHub token able to push branches and open PRs on `flathub/APP_ID`. A fine-grained token with *Contents* and *Pull requests* read/write works if the flathub org allows it. Otherwise use a classic token with `public_repo`. |
| `FLATHUB_REPO` | variable | `flathub/APP_ID` (optional; defaults to that) |
| `PUBLIC_GIT_URL` | variable | The URL of this repo exactly as written in the Flathub manifest, e.g. `https://git.yourdomain/alvaroemtnez/pat-desktop.git` |
| `FORGEJO_TOKEN` | secret | Optional Forgejo token with repo write access, so the weekly *Update Pat* PRs trigger CI |

Until `FLATHUB_TOKEN` exists, releases still build and publish the bundle on
Forgejo and skip the Flathub step. You can use that during testing.

## 5. Release routine

```
 upstream Pat release
        │  (weekly "Update Pat" workflow, or tools/update-pat.py)
        ▼
 PR "Update Pat to vX" on Forgejo ── review, merge
        │
 tools/bump-version.py 0.2.0 "Update Pat to vX"  →  commit
 git tag -a v0.2.0 -m v0.2.0 && git push --follow-tags
        │  (release workflow)
        ├─► Forgejo release with pat-desktop-v0.2.0.flatpak
        └─► PR "Update to v0.2.0" on github.com/flathub/APP_ID
                │  Flathub bot runs a test build on the PR
                ▼
            merge PR  →  Flathub builds and publishes (usually within a few hours)
```

The release workflow refuses to run if the tag, `pat_desktop/__init__.py`
and the newest metainfo `<release>` disagree.

It only changes the `tag:`/`commit:` pins and the generated Go module list in
your manifest. Anything else, such as a new runtime version or new
permissions, you edit by hand in the Flathub repo.

Wrapper-only releases (no Pat change) follow the same routine without the
first step.

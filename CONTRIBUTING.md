# Working together on LawChakra / Docket

Repository: https://github.com/SameerUpadhyay/LawChakra (private).

Use your own GitHub account and a separate local clone. Accept the repository invitation before cloning. GitHub authentication is separate from app login; never share a GitHub token, account password, app session, signing key or `.env` file in chat or Git.

```sh
git clone https://github.com/SameerUpadhyay/LawChakra.git
cd LawChakra
```

Open your own clone in Codex or Android Studio. See [local setup](README.md), [Android build](android/README.md) and [OCR setup](docs/bilingual-ocr.md). `npm run setup` installs application dependencies; install a supported Tesseract runtime and its English/Hindi models for full OCR tests. Android needs JDK 17+ and an Android SDK. Each developer has their own development database and verification-email outbox; these are ignored by Git.

## Concurrent work

Work on separate branches so both developers can push without overwriting each other's work. Start each task from the latest main:

```sh
git switch main
git pull --ff-only
git switch -c codex/your-name-short-feature
```

Make the change, run the relevant checks, then commit and push your branch:

```sh
git add path/to/changed-files
git commit -m "Describe the change"
git push -u origin HEAD
```

Open a pull request into `main`, review each other's changes, and merge once the checks pass. GitHub Actions runs backend/database, web, Android and infrastructure checks. Avoid force-pushing shared branches. If a normal push is rejected because another person advanced the branch, fetch and integrate their changes before pushing again. Two developers can push separate branches at the same time; changes to the same lines still need a merge decision.

## Validation

```sh
npm test
npm run typecheck
npm run build
npm run android:build
```

Run checks that match your change. Camera and ML Kit behavior also need a real Android phone. Synthetic OCR fixtures and results are not real-notice accuracy certification. See [camera intake](docs/camera-intake.md) and [verification](docs/android-verification.md).

## Keep local data private

Commit source, locked dependencies, tests and fictional fixtures. Local databases, encrypted records and keys, development email, `.env` values, AWS credentials, Android signing material, downloaded runtimes/models, editor state and generated output are excluded. Do not add real notices or screenshots containing customer/account data to fixtures or issues. Use the hosting platform's secret manager for deployment credentials.

The debug APK is generated at `output/android/docket-debug.apk`; GitHub Actions also uploads a `docket-debug` artifact on successful Android runs. Generated APKs, previews and benchmark reports are not versioned. Infrastructure templates are reviewable code and do not deploy AWS resources during tests.

No project-wide open-source license has been selected. This is a private collaboration repository; preserve dependency licenses, including the bundled test font's OFL notice, and review PyMuPDF licensing before public/proprietary distribution.

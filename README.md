# ICPC Resolver Helper

A practical guide for downloading a Kattis contest through the CLICS Contest API, preparing an ICPC Resolver package, managing team photos, generating corrected awards, validating the package, and launching ICPC Resolver.

> **Scope:** This document covers `resolver_helper.py`. The separate photo-sorting and one-off photo-repair utilities are not required for the normal helper workflow.

## Table of Contents

1. [Overview](#overview)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Quick Start](#quick-start)
5. [What the Helper Does](#what-the-helper-does)
6. [Interactive Workflow](#interactive-workflow)
7. [Configuration and Saved Settings](#configuration-and-saved-settings)
8. [Team Photos](#team-photos)
9. [Awards](#awards)
10. [Site Discovery](#site-discovery)
11. [Package Validation and Backups](#package-validation-and-backups)
12. [Command-Line Options](#command-line-options)
13. [Generated Files and Directories](#generated-files-and-directories)
14. [Troubleshooting](#troubleshooting)
15. [Recommended Final-Contest Procedure](#recommended-final-contest-procedure)
16. [Security Notes](#security-notes)

## Overview

`resolver_helper.py` is intended to live in the same directory as `resolver.sh`, `resolver.bat`, and the ICPC Resolver JAR files.

The helper performs the following tasks:

- Connects to a Kattis contest using the CLICS Contest API.
- Remembers the Kattis host, API user, API key, and last selected contest.
- Downloads the latest contest data on every run.
- Downloads organizations, teams, logos, flags, and other API-provided assets.
- Creates team-photo staging folders.
- Converts staged team photos to Resolver-compatible `photo.jpg` files.
- Discovers physical contest sites from Kattis.
- Replaces unreliable Kattis award events with locally generated awards.
- Removes known data incompatibilities, such as null language command objects.
- Builds the package in a temporary directory.
- Validates the package before launch.
- Preserves recent working-package backups.
- Automatically uses Resolver `--test` mode when results are not finalized.

## Requirements

### Required

- Python 3.10 or newer.
- Java installed and available through the `java` command.
- An ICPC Resolver download containing `resolver.sh` on macOS/Linux or `resolver.bat` on Windows.
- A Kattis API username and API key with access to the contest.
- Network access to the Kattis contest server.

### Recommended

- Pillow for robust image validation and conversion:

  ```bash
  python3 -m pip install Pillow
  ```

- `pillow-heif` for direct HEIC/HEIF support through Pillow:

  ```bash
  python3 -m pip install pillow-heif
  ```

On macOS, the helper can fall back to the built-in `sips` command for HEIC conversion.

## Installation

Place `resolver_helper.py` in the Resolver directory:

```text
resolver-2.x.xxxx/
├── resolver.sh
├── resolver.bat
├── resolver_helper.py
├── resolver.jar
├── presentations.jar
└── ...
```

On macOS or Linux:

```bash
cd ~/Downloads/resolver-2.x.xxxx
chmod +x resolver.sh resolver_helper.py
```

Run the offline self-tests:

```bash
python3 resolver_helper.py --self-test
```

Expected output:

```text
All offline self-tests passed.
```

Show the helper version:

```bash
python3 resolver_helper.py --version
```

## Quick Start

Run the helper from the Resolver directory:

```bash
python3 resolver_helper.py
```

On the first run, provide:

1. The Kattis contest host, such as `https://ncna26.kattis.com`.
2. The API username.
3. The API key.
4. The contest to download.

The helper then downloads the contest, creates photo staging folders, pauses for photos, generates awards, validates the package, and asks whether to launch Resolver.

On later runs, press Enter to reuse the saved host, username, API key, and contest selection.

## What the Helper Does

The normal workflow contains six phases:

```text
[1/6] Preflight checks
[2/6] Connect to Kattis
[3/6] Download and build contest package
[4/6] Prepare team photos
[5/6] Generate awards and validate
[6/6] Launch Resolver
```

### Phase 1: Preflight checks

The helper verifies:

- Python is new enough.
- Java is installed.
- `resolver.sh` or `resolver.bat` exists.
- The Resolver directory is writable.
- At least 1 GB of free disk space is available.

A failed preflight stops the run before contest data is downloaded.

### Phase 2: Connect to Kattis

The helper confirms the Kattis host and credentials, requests the contest list, and prompts for the contest to use.

The API base is formed as:

```text
https://<kattis-host>/api/clics/
```

### Phase 3: Download and build

The helper downloads, when available:

- contest
- judgement types
- languages
- problems
- groups
- organizations
- teams
- persons
- accounts
- state
- submissions
- judgements
- runs
- clarifications
- awards
- commentary
- scoreboard
- event feed

Kattis may return HTTP 404 for optional collections such as `runs`, `clarifications`, or `commentary`. The helper logs these as skipped and continues.

The helper also downloads organization and team assets referenced by the API, including logos, country flags, subdivision flags, banners, and photos.

### Phase 4: Prepare team photos

The helper creates contest-specific staging folders and pauses so the operator can add photos. See [Team Photos](#team-photos).

### Phase 5: Generate awards and validate

The helper:

- Creates a default `awards.json` policy if one does not exist.
- Discovers physical sites.
- Generates awards from the current scoreboard and submissions.
- Replaces Kattis award events in the event feed.
- Writes award audit files.
- Validates the completed package.

### Phase 6: Launch Resolver

If Kattis does not report finalized results, the helper launches:

```bash
./resolver.sh <contest-package> --test
```

If results are finalized, the helper launches without `--test`.

The helper always asks before launching.

## Interactive Workflow

A typical run looks like this:

```text
ICPC Resolver Helper

[1/6] Preflight checks
  [OK] Python ...
  [OK] resolver.sh
  [OK] Java ...

[2/6] Connect to Kattis
Kattis host: ...
API user: ...
API key: ...
Use these Kattis settings? [Y/n]

Available contests:
  1. Practice Contest
  2. Regional Contest
Contest number [2]:
Use this contest? [Y/n]
```

At the photo phase, the helper opens the staging folder when supported and asks:

```text
Have you finished placing team photos in the staging folders? [y/N]
```

Answering No leaves the helper paused. Answering Yes processes the photos and displays a summary.

After validation:

```text
Launch ICPC Resolver now? [Y/n]
```

## Configuration and Saved Settings

The helper stores remembered settings in:

```text
.resolver-helper.json
```

The file contains the last-used:

- Kattis host
- API username
- API key
- contest ID

On macOS and Linux, the helper attempts to set the file permissions to `600`, meaning only the current user can read or write it.

To reset saved settings:

```bash
rm .resolver-helper.json
```

The API key is intentionally stored locally for convenience. Do not commit `.resolver-helper.json` to Git or include it in a shared archive.

## Team Photos

### Staging directory

Photo folders are separated by contest:

```text
staging-photos/
├── ncna26/
│   ├── 975249 - MSUM 2 - North Dakota State U./
│   └── 975311 - void box - Marquette University/
└── ncna26practice/
    └── ...
```

Each folder name contains:

1. Contest-specific team ID
2. Team name
3. Physical contest site

### Photo pause

After the folders are created or verified, the helper:

- prints the staging path
- opens the folder on supported systems
- displays a macOS popup when appropriate
- waits for a Y/N confirmation

Folders may be left empty.

### Photo selection

If a folder contains multiple supported images, the first filename alphabetically is selected. The summary reports the selected and ignored files.

### Supported input formats

The helper accepts common formats including:

- `.jpg`
- `.jpeg`
- `.png`
- `.webp`
- `.gif`
- `.heic`
- `.heif`

The selected image is converted to an RGB JPEG and copied into the package as:

```text
<contest-id>-package/teams/<team-id>/photo.jpg
```

The staged original is preserved.

### Photo summary

Before continuing, the helper reports:

```text
Team photo summary
  Installed: 14
  Empty folders: 55
  Invalid/skipped: 0
  Multiple-image folders: 2
```

The operator must confirm the selections before award generation continues.

## Awards

Kattis-generated awards are replaced because Kattis award data may contain incorrect recipients or contest-specific IDs from another contest.

If no root `awards.json` exists, the helper creates a default policy automatically.

### Default award policy

| Award | Rule |
|---|---|
| Winner | First-place team in the scoreboard. |
| Second Place | Second-place team in the scoreboard. |
| Third Place | Third-place team in the scoreboard. |
| Top Team from Each University | Highest-ranked team from each organization, requiring at least one solve by default. |
| Expected to Advance | Top four teams from the one-team-per-university list. At most one team per university is included. |
| Small-Site Winner | Highest-ranked team with at least one solve at a site with fewer than six registered teams. The citation explicitly includes the word `Site`. |
| Major-Site First, Second, and Third | Top three teams with at least one solve at a site with six or more registered teams. Citations explicitly include the word `Site`. |
| First to Solve Each Problem | Earliest accepted submission for each solved problem. |
| Fastest Start | Earliest accepted submission in the contest, merged with the corresponding First to Solve award by default. |
| Last Accepted Submission | Latest accepted contest submission in the available data. |
| Cleanest Run | Qualifying team with the fewest rejected submissions; three solves are required by default. |
| Persistence Award | Most rejected attempts on a problem before that problem was eventually solved; three rejected attempts are required by default. |
| Most Submissions | Team with the largest total number of submissions, regardless of correctness or judgement. Ties share the award. |
| Biggest Comeback | Largest improvement from estimated frozen rank to final rank. Generated only when finalization and freeze information are available. |
| Freeze Breaker | Most accepted problems from submissions made after the scoreboard freeze. Generated only when finalization and freeze information are available. |

### Default policy settings

The generated `awards.json` contains settings equivalent to:

```json
{
  "top_overall": 3,
  "top_per_site": true,
  "top_per_school": true,
  "require_solve_for_site_school": true,
  "expected_to_advance": true,
  "expected_to_advance_count": 4,
  "major_site_placements": true,
  "major_site_minimum_teams": 6,
  "major_site_places": 3,
  "first_to_solve": true,
  "last_accepted": true,
  "biggest_comeback": true,
  "freeze_breaker": true,
  "cleanest_run": true,
  "persistence_award": true,
  "most_submissions": true,
  "fastest_start": true,
  "cleanest_run_minimum_solves": 3,
  "biggest_comeback_minimum_places": 3,
  "persistence_minimum_rejected_attempts": 3,
  "suppress_duplicate_fastest_start": true,
  "fun_awards_require_finalized": true
}
```

Existing policy files are merged with built-in defaults, so newly introduced default settings remain available even if an older `awards.json` omits them.

### Expected to Advance

This is a list award. The helper:

1. Orders teams by official scoreboard rank.
2. Keeps only the highest-ranked team from each university.
3. Selects the first four entries from that one-team-per-university list.

The citation uses the word `Expected` because appeals or advancement allocations may change later.

### Site placement eligibility

A site's size is based on all registered teams assigned to the site.

- Fewer than six teams: one Top Team at `<name>` Site award.
- Six or more teams: First, Second, and Third Place at `<name>` Site.
- A team must have at least one solved problem to receive a site award.
- If only one or two teams at a major site have a solve, only First Place, or First and Second Place, are generated.

### Provisional awards

When the contest is unfinished, the helper displays a prominent warning:

```text
PROVISIONAL AWARDS: Kattis does not report finalized results.
Recipients may change. Resolver will run in TEST mode.
```

### Award overlap summary

Teams can legitimately receive multiple awards. The helper prints an overlap summary so the operator can see repeated presentation moments before launching Resolver.

### Award audit files

The helper writes:

```text
<contest-id>-package/awards.json
<contest-id>-package/award-debug.json
<contest-id>-package/fun-award-debug.json
<contest-id>-package/site-debug.json
```

These files explain recipients, rankings, sites, submission counts, contest times, rejected attempts, and other selection evidence.

## Site Discovery

The helper uses the following sources:

1. Standard CLICS groups whose type is `site`.
2. The Kattis Teams page and its `Competing at site` column.
3. An optional `sites.json` override, if present.

The helper reports mapping coverage:

```text
site mapping coverage: 69/69 teams (100.0%)
```

### Safety rules

- Below 95% coverage: site award generation stops.
- Between 95% and 100%: unmatched teams are listed and confirmation is required.
- A team mapped to multiple sites causes the run to stop.
- At 100% coverage: processing continues automatically.

The site audit records each site's source, participating teams, official ranks, solved counts, total times, and award recipients.

## Package Validation and Backups

### Temporary package

The helper builds into a temporary directory such as:

```text
.ncna26-package-building/
```

The existing valid package is not replaced until the new package passes validation.

### Validation checks

The helper checks:

- required package files exist
- JSON files parse correctly
- event-feed lines are valid JSON
- award IDs are unique
- every award recipient is a known team
- every submission references a known team and problem
- every judgement references a known submission
- scoreboard rows are available

The validation report is written to:

```text
<contest-id>-package/validation-report.json
```

Resolver is not launched when validation fails.

### Backups

When a new package passes validation, the previous package is retained as:

```text
<contest-id>-package-backup-YYYYMMDD-HHMMSS/
```

The three newest backups are retained.

### Atomic writes

Important JSON and event-feed files are written to temporary `.download` files and then atomically renamed. This reduces the risk of leaving a partially written package after interruption.

## Command-Line Options

### Normal interactive run

```bash
python3 resolver_helper.py
```

### Build and validate without launching Resolver

```bash
python3 resolver_helper.py --download-only
```

### Validate an existing package

```bash
python3 resolver_helper.py --validate-only ncna26-package
```

### Validate and launch an existing package

```bash
python3 resolver_helper.py --launch-only ncna26-package
```

### Disable graphical folder opening and popups

```bash
python3 resolver_helper.py --no-popup
```

Terminal confirmations remain available.

### Run offline tests

```bash
python3 resolver_helper.py --self-test
```

### Display version

```bash
python3 resolver_helper.py --version
```

### Create a diagnostic bundle

```bash
python3 resolver_helper.py --diagnose
```

The helper creates:

```text
resolver-helper-diagnostics-YYYYMMDD-HHMMSS.zip
```

The bundle contains sanitized configuration, environment information, package validation reports, and Resolver logs. API keys and similar secret fields are removed from the diagnostic configuration.

## Generated Files and Directories

A typical Resolver directory contains:

```text
resolver-2.x.xxxx/
├── resolver_helper.py
├── resolver.sh
├── resolver.jar
├── presentations.jar
├── awards.json
├── .resolver-helper.json
├── staging-photos/
│   ├── ncna26/
│   │   ├── <team-id> - <team-name> - <site>/
│   │   └── team-photo-folders.json
│   └── ncna26practice/
├── ncna26-package/
│   ├── contest.json
│   ├── teams.json
│   ├── organizations.json
│   ├── submissions.json
│   ├── judgements.json
│   ├── scoreboard.json
│   ├── awards.json
│   ├── award-debug.json
│   ├── fun-award-debug.json
│   ├── site-debug.json
│   ├── validation-report.json
│   ├── event-feed.ndjson
│   ├── event-feed.fixed.ndjson
│   ├── event-feed.kattis.<timestamp>.ndjson
│   └── teams/
│       └── <team-id>/
│           └── photo.jpg
└── ncna26-package-backup-<timestamp>/
```

## Troubleshooting

### `languages/runner:null`

Some Kattis language records contain null `runner` or `compiler` objects that older Resolver versions cannot parse. The helper removes these null fields from both `languages.json` and the event feed.

Expected helper output:

```text
sanitized 3 null language command field(s) in languages.json
```

### `Unknown property ignored: organizations/country_subdivision`

Older Resolver versions may not recognize the newer `country_subdivision` organization property. Resolver logs the warning and continues. This warning does not normally invalidate the package.

### Unjudged submissions discarded

In `--test` mode, Resolver removes unjudged submissions:

```text
Warning: 2 unjudged submissions discarded.
```

This is expected while the contest is unfinished.

### Zero pending submissions

Before the scoreboard freeze, or when no frozen submissions remain, Resolver may report:

```text
Resolving 0 pending submissions
```

This does not indicate a package error.

### Optional API collection returns 404

Messages such as these are normally harmless:

```text
skipped runs (HTTP 404)
skipped clarifications (HTTP 404)
skipped commentary (HTTP 404)
```

The collections are optional or unavailable for that Kattis contest.

### Site mapping below 95%

The helper stops rather than generate potentially incorrect site awards. Review `teams.json`, `groups.json`, the Kattis Teams page, and `site-debug.json`.

### Photo appears incorrect

Verify that the staging folder contains the intended photo and rerun the helper. The final package file must be:

```text
teams/<team-id>/photo.jpg
```

### Package validation fails

Open:

```text
<contest-id>-package/validation-report.json
```

The previous working package is preserved when the temporary build fails validation.

### Resolver version differences

The helper can run beside multiple Resolver versions, but presentation features and supported organization properties may differ. Use the same Resolver JARs that will be used during the actual ceremony.

## Recommended Final-Contest Procedure

1. Use the production Resolver directory and JAR files.
2. Run the offline tests:

   ```bash
   python3 resolver_helper.py --self-test
   ```

3. Build without launching:

   ```bash
   python3 resolver_helper.py --download-only
   ```

4. Add and review team photos at the photo pause.
5. Confirm site mapping reaches 100%, or review every unmatched team.
6. Review:

   ```text
   awards.json
   award-debug.json
   fun-award-debug.json
   site-debug.json
   validation-report.json
   ```

7. Confirm Kattis reports the contest as finalized.
8. Confirm no important submissions remain unjudged.
9. Validate the package again:

   ```bash
   python3 resolver_helper.py --validate-only ncna26-package
   ```

10. Launch the validated package:

    ```bash
    python3 resolver_helper.py --launch-only ncna26-package
    ```

11. Preview the complete resolution before the public ceremony.
12. Keep the generated package backup and audit files with the contest records.

## Security Notes

- The helper uses the Kattis API in a read-only workflow.
- The saved API key is stored in `.resolver-helper.json` for convenience.
- Do not commit `.resolver-helper.json` to source control.
- Do not include `.resolver-helper.json` in diagnostic archives, email attachments, or shared Resolver packages.
- The `--diagnose` command removes expected secret fields from the diagnostic configuration.

## Support Checklist

When reporting a problem, include:

- helper version from `python3 resolver_helper.py --version`
- Resolver version
- operating system
- terminal error message
- `validation-report.json`
- relevant Resolver log
- `site-debug.json` for site-award problems
- `award-debug.json` or `fun-award-debug.json` for award problems

Do not include the API key.

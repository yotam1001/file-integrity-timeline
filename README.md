# FileIntegrityTimeline

**Find out when files in your archives changed.** Save a trusted SHA-256 baseline of one or more folders, then rescan later to see which files were added, went missing, or changed bytes. The desktop interface shows a scan history and opens a standalone HTML report. Source files are only read.

This is an integrity **detection** tool. It does not know whether a change was intentional, identify the cause of corruption, restore files, or replace a backup.

## Why this exists

A [September 2026 discussion](https://www.reddit.com/r/DataHoarder/comments/1w7e5vf/is_periodically_checking_sha256_hashes_enough_to/) asked whether recurring SHA-256 checks would detect silent changes, and commenters highlighted the need to detect files that disappear. Another [September discussion](https://www.reddit.com/r/DataHoarder/comments/1w8rm2u/how_do_you_handle_backups_when_you_dont_know_when/) asked how to know when corruption happened before later backups replace an earlier good copy. A [July request in r/Backup](https://www.reddit.com/r/Backup/comments/1v73mmu/comparing_history_of_file_hash_values/) specifically asked for a Windows GUI that remembers hash baselines across several drives and network folders.

[BitCheck](https://github.com/AlanBarber/bitcheck) already offers a cross-platform CLI for recurring integrity checks, including strict mode. [QuickHash GUI](https://github.com/tedsmith/quickhash) hashes and compares folders, and [Beyond Compare](https://www.scootersoftware.com/kb/crc) supports CRC snapshots. FileIntegrityTimeline focuses on a small Windows GUI and CLI workflow: multiple roots in one project, explicit trusted SHA-256 baselines, dated checks, and a history of differences.

## Download and run

For Windows 10/11 x64, [download the latest release ZIP](https://github.com/yotam1001/file-integrity-timeline/releases/latest/download/FileIntegrityTimeline-windows-x64.zip). It contains two self-contained executables:

- `FileIntegrityTimeline.exe` — desktop interface; no Python install needed.
- `fit-cli.exe` — command line and built-in self-test.

The ZIP is unsigned. Windows SmartScreen may ask you to review it. Verify the SHA-256 listed beside the release asset before running it. No account, network service, or administrator access is needed for scans of folders you can already read.

From source, install Python 3.10 or later with Tk support, then run:

```sh
python -m file_integrity_timeline
```

The source version uses only the Python standard library. On some Linux distributions, Tk is a separate OS package; the CLI still works without it.

## Desktop workflow

1. Choose **New project**, add each folder, and save the `.fit` project database **outside** the scanned folders.
2. Select **Create baseline / Check now**. The first successful scan becomes the trusted baseline.
3. Run the same button later. The scan reads and hashes every file again, including files whose size and timestamp appear unchanged.
4. Select a completed check in **Scan history**, then **Open selected report** to review additions, missing files, and changed hashes.
5. If you deliberately changed files and verified the current state, select a complete scan and choose **Trust selected scan**. Previous scans remain in history.

If an external drive gets a different drive letter, select its folder and choose **Change selected folder location**. This changes where future scans read; it does not change prior hashes.

## Command line

Create a project with two roots:

```powershell
python -m file_integrity_timeline init archive.fit --root 'Photos=D:\Photos' --root 'Backup=E:\Backup'
python -m file_integrity_timeline scan archive.fit
```

The first `scan` creates the baseline. Later scans compare against it and write a numbered HTML report beside `archive.fit`.

```powershell
python -m file_integrity_timeline history archive.fit
python -m file_integrity_timeline roots archive.fit
python -m file_integrity_timeline remap archive.fit 2 'F:\Backup'
python -m file_integrity_timeline trust archive.fit 3
python -m file_integrity_timeline report archive.fit 3 review.html
python -m file_integrity_timeline self-test
```

The CLI returns `0` for a complete scan with no differences (and for first baseline creation), `1` for a complete scan with differences, and `2` for a cancelled, incomplete, or failed scan. It will not report missing files if any file or folder could not be read during that scan.

## What it reads and stores

Files are read in 1 MiB chunks and hashed with SHA-256 on **every** scan; previous hash values are not used to skip a file. Each scan is saved to a local SQLite `.fit` database with relative file paths, sizes, modification times, and hashes. The database also stores full root paths and a dated scan history. HTML reports include full current root paths and should be reviewed before sharing.

Symbolic links are skipped. Unsupported non-regular files, a file changed during hashing, an unreadable file, or an unreadable directory make the scan **incomplete**, with no integrity verdict. A disconnected root stops the scan before it starts. The app cannot read a file locked against access by another program. Scanning multiple terabytes may take hours and can put sustained load on the disks. The scan is not an atomic filesystem snapshot; keep actively changing folders out of a project when you need a stable check.

An unchanged SHA-256 value means the bytes read during the check matched the trusted scan's bytes for that path. It does not prove that the trusted copy was good, that a backup can restore, or that files did not change and change back between scans.

## Development

```sh
python -m unittest discover -s tests -v
python -m file_integrity_timeline self-test
python -m compileall -q file_integrity_timeline
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

MIT licensed. Copyright © 2026 yotam1001.

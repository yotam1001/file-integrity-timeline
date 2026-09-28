# Security

FileIntegrityTimeline reads selected source folders and writes only the project database and requested reports. It does not delete, rename, upload, or repair source files. Do not use it as your only backup.

Project databases and HTML reports include full local paths and file hashes. Keep them private and review them before sharing. The program skips symbolic links and marks scans with read errors incomplete; it never labels files missing when a scan is incomplete.

To report a vulnerability privately, use the repository's GitHub Security Advisory **Report a vulnerability** button after publication. Please do not post sensitive example databases or local paths in a public issue.

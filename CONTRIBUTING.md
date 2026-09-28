# Contributing

Please open an issue before a large change. Small bug fixes and documentation improvements are welcome.

## Local checks

```sh
python -m unittest discover -s tests -v
python -m file_integrity_timeline self-test
python -m compileall -q file_integrity_timeline
```

Keep source folders read-only. New scan or report behavior should have a test showing what happens when a file cannot be read or changes during hashing. Do not include real project databases, reports, private paths, or sample personal files in issues or pull requests.

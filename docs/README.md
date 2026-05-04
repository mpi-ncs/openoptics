---
orphan: true
---

# Building the docs locally

This directory holds the Sphinx sources for the OpenOptics documentation
site. To build and browse it:

```bash
make html                   # writes _build/html/
python3 -m http.server -d _build/html
```

Then open <http://localhost:8000>.

The published site is hosted at the URLs configured in `publish2dev.sh`
and `publish2mpi.sh`.

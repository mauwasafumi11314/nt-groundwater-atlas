# data/

**Nothing in this directory is ever committed.** See CLAUDE.md.

Expected layout:

```
data/
  raw/        # source extracts, exactly as received — never edited in place
  interim/    # intermediate products
  processed/  # outputs staged for load/export
```

`data/README.md` and `data/.gitkeep` are the only tracked files here.

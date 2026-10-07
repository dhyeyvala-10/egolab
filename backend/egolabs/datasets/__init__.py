"""
Datasets, versioning, exports, and lineage (spec Phase 6).

- `build`: resolve a version's samples from its spec and pinned inputs, as the data stood at its `as_of`;
  splits; the content hash; the build and rebuild-check jobs.
- `export`: write a version out as COCO, JSON Lines, Parquet, WebDataset, or the native Ego Labs format.
- `lineage`: walk from a sample back to the raw file and frames it came from.
"""

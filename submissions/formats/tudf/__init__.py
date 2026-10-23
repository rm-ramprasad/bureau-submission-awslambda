"""Generic TUDF file engine: a layout (YAML) describes the format; the engine renders snapshots with it.

  layout.py      the layout model, loaded and checked from YAML
  formatters.py  named value formatters a layout refers to
  encoding.py    primitives (printable ASCII, TLV, fixed width, amounts, dates, word fitting)
  snapshot.py    reading a validated snapshot (accepted records, validation drops)
  engine.py      rendering the header, records and trailer
  parser.py      reading a file back (checks and tests)
"""

"""LBD Viewer: a local web app that lists and plots .lbd files."""

__version__ = "1.3.0.dev0"
# As people see it: 1.2.0, or 1.2.0-dev while 1.2.0 is in development (__version__ is then
# 1.2.0.dev0, the Python spelling; see scripts/check_versions.py).
VERSION = __version__.replace(".dev0", "-dev")

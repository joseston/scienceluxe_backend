"""Core helpers for Proceso 1.

Keep this package init lightweight so Flask can import the blueprint even when
optional runtime dependencies for specific extractors/providers are missing.
Import concrete helpers from their submodules directly.
"""

__all__: list[str] = []

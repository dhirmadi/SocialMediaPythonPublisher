"""Compatibility re-export (#96): the parser lives in services now.

The sidecar format is a service-layer concern; importing it here kept a
services → web dependency alive. Import from
``publisher_v2.services.sidecar_parser`` in new code.
"""

from publisher_v2.services.sidecar_parser import parse_sidecar_text, rehydrate_sidecar_view

__all__ = ["parse_sidecar_text", "rehydrate_sidecar_view"]

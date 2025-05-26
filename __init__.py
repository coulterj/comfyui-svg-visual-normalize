# In custom_nodes/my_svg_pack/__init__.py

# And that file defines NODE_CLASS_MAPPINGS and NODE_DISPLAY_NAME_MAPPINGS
from .svg_visual_normalize_node import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']

import lxml.etree as ET
import re
import io # For in-memory byte streams

# --- Dependency Check ---
try:
    import cairosvg
    CAIROSVG_AVAILABLE = True
except ImportError:
    CAIROSVG_AVAILABLE = False

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
# ----------------------

class SVGVisualBoundsNormalize:
    def __init__(self):
        if not CAIROSVG_AVAILABLE:
            print("\n\n\033[31m[ERROR] SVGVisualBoundsNormalize Node:\033[0m The required 'CairoSVG' library is not installed.")
            print("\033[33m[ERROR] Please run 'pip install CairoSVG' and ensure system Cairo libraries are installed.\033[0m\n\n")
        if not PILLOW_AVAILABLE:
            print("\n\n\033[31m[ERROR] SVGVisualBoundsNormalize Node:\033[0m The required 'Pillow' library is not installed.")
            print("\033[33m[ERROR] Please run 'pip install Pillow'.\033[0m\n\n")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "svg_string": ("STRING", {"multiline": True, "default": ""}),
                "margin_percent": ("FLOAT", {
                    "default": 0.00, "min": 0.0, "max": 0.499, "step": 0.001,
                    "display": "number", "precision": 4
                }),
                "visual_bbox_padding_percent": ("FLOAT", { # Padding for the visual bbox
                    "default": 0.00, "min": 0.0, "max": 0.1, # Usually less padding needed if visual bbox is accurate
                    "step": 0.001, "display": "number", "precision": 4
                }),
                # Manual center offsets are kept as a final fallback if needed
                "center_offset_x_percent": ("FLOAT", { 
                    "default": 0.0, "min": -0.5, "max": 0.5, "step": 0.001,
                    "display": "number", "precision": 4
                }),
                "center_offset_y_percent": ("FLOAT", { 
                    "default": 0.0, "min": -0.5, "max": 0.5, "step": 0.001,
                    "display": "number", "precision": 4
                }),
                "output_width": ("INT", {"default": 0, "min": 0, "max": 8192, "step": 1}),
                "output_height": ("INT", {"default": 0, "min": 0, "max": 8192, "step": 1}),
                "render_scale_for_bbox": ("FLOAT", { # Scale factor for temporary rendering
                    "default": 1.0, "min": 0.5, "max": 4.0, "step": 0.1,
                    "display": "number", "precision": 2
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "process"
    CATEGORY = "svg"

    def _parse_dimension(self, dim_str):
        if dim_str is None: return None
        cleaned_dim_str = re.sub(r"[^\d\.\-]", "", dim_str)
        if not cleaned_dim_str: return None
        try: return float(cleaned_dim_str)
        except ValueError: return None

    def _get_visual_bbox(self, svg_string_content, declared_width, declared_height, render_scale):
        if not CAIROSVG_AVAILABLE or not PILLOW_AVAILABLE:
            print("SVGVisualBoundsNormalize: Missing CairoSVG or Pillow for visual bbox calculation.")
            return None

        try:
            # Determine rendering dimensions
            # If declared_width/height are valid, use them scaled by render_scale
            # Otherwise, CairoSVG will use intrinsic size or a default
            render_w, render_h = None, None
            if declared_width > 0 and declared_height > 0:
                render_w = int(declared_width * render_scale)
                render_h = int(declared_height * render_scale)
            
            # print(f"DEBUG: Rendering SVG at {render_w}x{render_h} (scale: {render_scale}) for bbox detection.")

            png_bytes = cairosvg.svg2png(
                bytestring=svg_string_content.encode('utf-8'),
                output_width=render_w if render_w else None, # Pass None if not determined, CairoSVG will decide
                output_height=render_h if render_h else None
            )
            
            img = Image.open(io.BytesIO(png_bytes))
            
            # Ensure image is RGBA to get accurate bbox based on transparency
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            pixel_bbox = img.getbbox() # Returns (left, upper, right, lower) or None

            if pixel_bbox is None:
                print("SVGVisualBoundsNormalize: Pillow getbbox returned None (image might be empty/fully transparent).")
                return None # Could default to full canvas: (0, 0, declared_width, declared_height)

            left, upper, right, lower = pixel_bbox
            
            # Map pixel bbox back to SVG units
            # If we rendered at scaled dimensions, we need to scale back
            # The coordinate system of the rendered PNG is 0,0 at top-left.
            # This should map directly to SVG units if the SVG's viewBox is effectively 0,0 to declared_width, declared_height
            
            svg_bbox_x = left / render_scale
            svg_bbox_y = upper / render_scale
            svg_bbox_w = (right - left) / render_scale
            svg_bbox_h = (lower - upper) / render_scale
            
            return (svg_bbox_x, svg_bbox_y, svg_bbox_w, svg_bbox_h)

        except Exception as e:
            print(f"SVGVisualBoundsNormalize: Error during visual bbox calculation: {e}")
            return None

    def process(self, svg_string, margin_percent, visual_bbox_padding_percent,
                center_offset_x_percent, center_offset_y_percent,
                output_width, output_height, render_scale_for_bbox):
        
        print("\n--- SVGVisualBoundsNormalize: Process Start ---") # DEBUG
        if not CAIROSVG_AVAILABLE or not PILLOW_AVAILABLE:
            print("SVGVisualBoundsNormalize: ERROR - CairoSVG or Pillow library is missing.")
            return (svg_string,)
        if not svg_string.strip(): return ("<svg></svg>",)

        # Original SVG string needed for rendering if lxml modifies it too much (e.g. strips comments)
        original_svg_for_render = svg_string 

        processed_svg_string = svg_string
        if processed_svg_string.startswith("<?xml"):
            declaration_end = processed_svg_string.find("?>")
            if declaration_end != -1:
                processed_svg_string = processed_svg_string[declaration_end + 2:].lstrip()
        if not processed_svg_string.strip(): return ("<svg></svg>",)

        root = None
        try:
            byte_input = processed_svg_string.encode('utf-8')
            parser = ET.XMLParser(remove_blank_text=True, recover=True)
            root = ET.fromstring(byte_input, parser=parser)
            if not isinstance(root, ET._Element): return (svg_string,)
        except ET.XMLSyntaxError: return (svg_string,)
        
        if root is None or ET.QName(root).localname != 'svg': return (svg_string,)
        
        # Determine initial canvas_w/h (these define the viewBox coordinate system)
        # These are also used as the base for rendering scale if render_scale_for_bbox is 1.0
        initial_canvas_w_str, initial_canvas_h_str = root.get('width'), root.get('height')
        initial_canvas_w, initial_canvas_h = 0.0, 0.0
        parsed_from_attrs = False

        if initial_canvas_w_str and initial_canvas_h_str:
            w = self._parse_dimension(initial_canvas_w_str)
            h = self._parse_dimension(initial_canvas_h_str)
            if w is not None and h is not None and w > 0 and h > 0:
                initial_canvas_w, initial_canvas_h = w, h
                parsed_from_attrs = True
        
        if not parsed_from_attrs:
            viewbox_str = root.get('viewBox')
            if viewbox_str:
                parts = [p.strip() for p in viewbox_str.replace(',', ' ').split()]
                if len(parts) == 4:
                    try: 
                        _, _, vb_w, vb_h = map(float, parts)
                        if vb_w > 0 and vb_h > 0:
                            initial_canvas_w, initial_canvas_h = vb_w, vb_h
                    except ValueError: pass 
            if initial_canvas_w <= 0 or initial_canvas_h <= 0:
                print("SVGVisualBoundsNormalize: Error determining initial canvas dimensions for rendering/viewBox.")
                return (svg_string,)
        print(f"DEBUG: Initial SVG canvas (viewBox system) w={initial_canvas_w}, h={initial_canvas_h}")

        # --- Get VISUAL Bounding Box ---
        vis_bbox = self._get_visual_bbox(original_svg_for_render, initial_canvas_w, initial_canvas_h, render_scale_for_bbox)
        if vis_bbox is None:
            print("SVGVisualBoundsNormalize: EXITING - Visual Bbox could not be determined.")
            return (svg_string,)
        
        vis_bbox_x, vis_bbox_y, vis_bbox_w, vis_bbox_h = vis_bbox
        print(f"DEBUG: Visual Bbox (SVG units): x={vis_bbox_x:.2f}, y={vis_bbox_y:.2f}, w={vis_bbox_w:.2f}, h={vis_bbox_h:.2f}")

        # Effective visual bbox after padding
        eff_vis_bbox_x, eff_vis_bbox_y, eff_vis_bbox_w, eff_vis_bbox_h = vis_bbox_x, vis_bbox_y, vis_bbox_w, vis_bbox_h
        if visual_bbox_padding_percent > 0.0:
            padding_offset_w = vis_bbox_w * visual_bbox_padding_percent
            padding_offset_h = vis_bbox_h * visual_bbox_padding_percent
            eff_vis_bbox_x = vis_bbox_x - padding_offset_w
            eff_vis_bbox_y = vis_bbox_y - padding_offset_h
            eff_vis_bbox_w = vis_bbox_w + (2 * padding_offset_w)
            eff_vis_bbox_h = vis_bbox_h + (2 * padding_offset_h)
        print(f"DEBUG: Effective Visual Bbox (padding {visual_bbox_padding_percent*100:.1f}%): x={eff_vis_bbox_x:.2f}, y={eff_vis_bbox_y:.2f}, w={eff_vis_bbox_w:.2f}, h={eff_vis_bbox_h:.2f}")

        if eff_vis_bbox_w <= 0 or eff_vis_bbox_h <= 0:
            print(f"SVGVisualBoundsNormalize: EXITING - Effective Visual Bbox width or height is <= 0.")
            return (svg_string,)
            
        # Target area for content *within the viewBox coordinate system*
        viewbox_margin_x = initial_canvas_w * margin_percent
        viewbox_margin_y = initial_canvas_h * margin_percent
        viewbox_target_w = initial_canvas_w - (2 * viewbox_margin_x)
        viewbox_target_h = initial_canvas_h - (2 * viewbox_margin_y)
        print(f"DEBUG: ViewBox target area: w={viewbox_target_w:.2f}, h={viewbox_target_h:.2f}")


        if viewbox_target_w <=0 or viewbox_target_h <=0: return (svg_string,) # Margin too large

        # Scale to fit the effective VISUAL bbox into the target area
        scale_x_fit = viewbox_target_w / eff_vis_bbox_w
        scale_y_fit = viewbox_target_h / eff_vis_bbox_h
        scale = min(scale_x_fit, scale_y_fit)
        print(f"DEBUG: Final Scale (to fit eff_vis_bbox into viewbox_target): {scale:.4f}")

        if scale <= 0: return (svg_string,)

        scaled_content_w = eff_vis_bbox_w * scale
        scaled_content_h = eff_vis_bbox_h * scale
        
        # Translate to center the scaled effective VISUAL bbox
        base_translate_x = viewbox_margin_x + (viewbox_target_w - scaled_content_w) / 2.0 - (eff_vis_bbox_x * scale)
        base_translate_y = viewbox_margin_y + (viewbox_target_h - scaled_content_h) / 2.0 - (eff_vis_bbox_y * scale)
        
        manual_offset_x = viewbox_target_w * center_offset_x_percent
        manual_offset_y = viewbox_target_h * center_offset_y_percent
        final_translate_x = base_translate_x + manual_offset_x
        final_translate_y = base_translate_y + manual_offset_y
        print(f"DEBUG: Final Translate: tx={final_translate_x:.2f}, ty={final_translate_y:.2f}")
        
        transform_str = f"translate({final_translate_x} {final_translate_y}) scale({scale})"
        print(f"DEBUG: Final <g> transform string: {transform_str}")
        
        all_children = list(root)
        nsmap = root.nsmap if hasattr(root, 'nsmap') and root.nsmap else {None: "http://www.w3.org/2000/svg"}
        group_tag_name = ET.QName(nsmap.get(None, "http://www.w3.org/2000/svg"), "g")
        group = ET.Element(group_tag_name, nsmap=nsmap)
        group.set("transform", transform_str)

        for child in all_children:
            root.remove(child)
            group.append(child)
        root.append(group)

        # Final output dimensions and viewBox
        final_output_w, final_output_h = initial_canvas_w, initial_canvas_h
        if output_width > 0 and output_height > 0:
            final_output_w, final_output_h = float(output_width), float(output_height)
        elif output_width > 0:
            final_output_w = float(output_width)
            if initial_canvas_w > 0: final_output_h = float(output_width * (initial_canvas_h / initial_canvas_w))
            else: final_output_h = float(output_width)
        elif output_height > 0:
            final_output_h = float(output_height)
            if initial_canvas_h > 0: final_output_w = float(output_height * (initial_canvas_w / initial_canvas_h))
            else: final_output_w = float(output_height)

        root.set('viewBox', f"0 0 {initial_canvas_w} {initial_canvas_h}") 
        root.set('width', str(final_output_w))
        root.set('height', str(final_output_h))
        
        final_svg_string = ET.tostring(root, encoding="unicode", xml_declaration=False)
        print("--- SVGVisualBoundsNormalize: Process End ---") # DEBUG
        return (final_svg_string,)

NODE_CLASS_MAPPINGS = {
    "SVGVisualBoundsNormalize": SVGVisualBoundsNormalize
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "SVGVisualBoundsNormalize": "SVG Visual Normalize & Margin" 
}

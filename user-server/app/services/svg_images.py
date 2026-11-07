"""Validate passive SVG images without rewriting their vector data."""

import math
import re
from xml.parsers import expat

import tinycss2

from app.core.exceptions import BusinessError

SVG_MIME = "image/svg+xml"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_ELEMENTS = frozenset("""
svg g defs symbol use switch title desc metadata path rect circle ellipse line
polyline polygon text tspan textPath linearGradient radialGradient stop pattern
clipPath mask marker filter feBlend feColorMatrix feComponentTransfer feComposite
feConvolveMatrix feDiffuseLighting feDisplacementMap feDistantLight feDropShadow
feFlood feFuncA feFuncB feFuncG feFuncR feGaussianBlur feMerge feMergeNode
feMorphology feOffset fePointLight feSpecularLighting feSpotLight feTile feTurbulence
style image
""".split())
_LOCAL_REFERENCE = re.compile(r"#[^\s<>\"']+\Z")
_CSS_ATTRIBUTES = frozenset({
    "style", "fill", "stroke", "filter", "clip-path", "mask", "cursor",
    "marker", "marker-start", "marker-mid", "marker-end", "color-profile",
})
_UNSAFE_CSS_FUNCTIONS = frozenset({
    "expression", "image", "image-set", "-webkit-image-set", "src", "paint",
})
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_LENGTH = re.compile(rf"\s*({_NUMBER})(px|in|cm|mm|q|pt|pc)?\s*", re.I)
_PIXELS_PER_UNIT = {"": 1, "px": 1, "in": 96, "cm": 96 / 2.54, "mm": 96 / 25.4,
                    "q": 96 / 101.6, "pt": 96 / 72, "pc": 16}
_MAX_DIMENSION = 2_147_483_647


def _invalid_svg() -> BusinessError:
    return BusinessError("模型返回的 SVG 无效或包含不支持的活动内容", code=50031, status_code=500)


def _passive_css(value: str) -> None:
    # Parse CSS escapes, comments and quoted strings as browsers do. Inspect
    # tokens only; never rewrite the original SVG or its styles.
    pending = [(tinycss2.parse_component_value_list(value, skip_comments=True), 0)]
    while pending:
        tokens, depth = pending.pop()
        if depth > 128:
            raise _invalid_svg()
        for index, token in enumerate(tokens):
            kind = token.type
            if kind == "error":
                raise _invalid_svg()
            if kind == "at-keyword" and token.lower_value not in {"media", "supports", "layer", "container"}:
                raise _invalid_svg()
            if kind == "ident" and token.lower_value in {"behavior", "-moz-binding"}:
                following = next((t for t in tokens[index + 1:] if t.type != "whitespace"), None)
                if following and following.type == "literal" and following.value == ":":
                    raise _invalid_svg()
            if kind == "url" and not _LOCAL_REFERENCE.fullmatch(token.value):
                raise _invalid_svg()
            if kind == "function":
                if token.lower_name in _UNSAFE_CSS_FUNCTIONS:
                    raise _invalid_svg()
                if token.lower_name == "url":
                    arguments = [t for t in token.arguments if t.type != "whitespace"]
                    if len(arguments) != 1 or arguments[0].type != "string" or not _LOCAL_REFERENCE.fullmatch(arguments[0].value):
                        raise _invalid_svg()
                else:
                    pending.append((token.arguments, depth + 1))
            elif kind in {"{} block", "[] block", "() block"}:
                pending.append((token.content, depth + 1))


def _dimension(value: str | None) -> float | None:
    match = _LENGTH.fullmatch(value or "")
    if not match:
        return None
    number = float(match[1]) * _PIXELS_PER_UNIT[(match[2] or "").lower()]
    return number if math.isfinite(number) and 0 < number <= _MAX_DIMENSION else None


def svg_dimensions(content: bytes, *, required: bool = False) -> tuple[int | None, int | None] | None:
    """Return dimensions for a complete passive SVG, or None for non-XML bytes.

    DTDs, entities, processing instructions, executable elements, event handlers
    and external references are rejected before same-origin object storage.
    The streaming parser does not build an XML tree or fetch external resources.
    """
    prefix = content.removeprefix(b"\xef\xbb\xbf").lstrip()
    if not prefix.startswith((b"<", b"\xff\xfe", b"\xfe\xff", b"\x00<")):
        if required:
            raise _invalid_svg()
        return None
    parser = expat.ParserCreate(namespace_separator="}")
    root_attributes: dict | None = None
    style_parts: list[str] | None = None
    depth = 0

    def reject(*_):
        raise _invalid_svg()

    def start(name, attributes):
        nonlocal root_attributes, style_parts, depth
        namespace, _, local = name.rpartition("}")
        if namespace != SVG_NAMESPACE or local not in _ELEMENTS:
            reject()
        if root_attributes is None:
            if local != "svg":
                reject()
            root_attributes = attributes
        depth += 1
        if depth > 128 or style_parts is not None:
            reject()
        for key, value in attributes.items():
            attr_namespace, _, attr = key.rpartition("}")
            if attr_namespace and not (
                attr_namespace == "http://www.w3.org/1999/xlink" and attr == "href"
                or attr_namespace == "http://www.w3.org/XML/1998/namespace" and attr in {"lang", "space"}
            ):
                reject()
            if attr.lower().startswith("on") or attr.lower() in {"base", "src"}:
                reject()
            if attr == "href" and not _LOCAL_REFERENCE.fullmatch(value.strip()):
                reject()
            if attr in _CSS_ATTRIBUTES:
                _passive_css(value)
        if local == "style":
            style_parts = []

    def end(name):
        nonlocal depth, style_parts
        if name == SVG_NAMESPACE + "}style":
            _passive_css("".join(style_parts or []))
            style_parts = None
        depth -= 1

    def characters(value):
        if style_parts is not None:
            style_parts.append(value)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters
    parser.StartDoctypeDeclHandler = reject
    parser.EntityDeclHandler = reject
    parser.ExternalEntityRefHandler = reject
    parser.ProcessingInstructionHandler = reject
    try:
        parser.Parse(content, True)
    except (expat.ExpatError, ValueError) as exc:
        raise _invalid_svg() from exc
    if root_attributes is None:
        raise _invalid_svg()

    width = _dimension(root_attributes.get("width"))
    height = _dimension(root_attributes.get("height"))
    viewbox = re.split(r"[\s,]+", root_attributes.get("viewBox", "").strip())
    if len(viewbox) == 4 and all(re.fullmatch(_NUMBER, value) for value in viewbox):
        box = tuple(float(value) for value in viewbox)
        box_width, box_height = box[2:]
        if all(math.isfinite(value) for value in box) and 0 < box_width <= _MAX_DIMENSION and 0 < box_height <= _MAX_DIMENSION:
            if width and not height:
                height = width * box_height / box_width
            elif height and not width:
                width = height * box_width / box_height
            elif not width and not height:
                width, height = box_width, box_height

    def integer(value):
        return max(1, round(value)) if value and math.isfinite(value) and value <= _MAX_DIMENSION else None

    return integer(width), integer(height)

"""
bomk/icon.py – Generate and inject app icons at various Android densities.
"""

from pathlib import Path
from PIL import Image
from .lib import Logger


# Android launcher icon sizes (px) by screen density
ICON_SIZES: dict[str, int] = {
    "mdpi":    48,
    "hdpi":    72,
    "xhdpi":   96,
    "xxhdpi":  144,
    "xxxhdpi": 192,
}

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def inject_icon(
    template_path: Path,
    icon_path: str,
    logger: Logger | None = None,
) -> None:
    """
    Resize a single icon image to all required Android launcher densities
    and place the results in the template's mipmap-* directories.

    Raises:
        FileNotFoundError  – icon_path does not exist
        ValueError         – unsupported format or image cannot be opened
    """
    icon_file = Path(icon_path)
    if not icon_file.exists():
        raise FileNotFoundError(f"Icon file not found: {icon_path}")

    if icon_file.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported icon format: {icon_file.suffix}\n"
            f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS)).upper()}"
        )

    try:
        img = Image.open(icon_file)
        # Normalise: always keep alpha channel when present, otherwise RGB
        img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "PA", "P") else "RGB")
    except Exception as exc:
        raise ValueError(f"Failed to open icon image: {exc}") from exc

    logger and logger.step(f"Resizing icon: {icon_file.name}")

    for density, size in ICON_SIZES.items():
        mipmap_dir = (
            template_path / "app" / "src" / "main" / "res" / f"mipmap-{density}"
        )
        if not mipmap_dir.exists():
            mipmap_dir.mkdir(parents=True, exist_ok=True)
            logger and logger.verbose(f"  Created: {mipmap_dir.relative_to(template_path)}")

        resized      = img.resize((size, size), Image.Resampling.LANCZOS)
        output_path  = mipmap_dir / "ic_launcher.png"

        # BUG FIX: the original had identical if/else branches — both saved as PNG.
        # PNG always supports both RGBA and RGB, so a single save call is correct.
        resized.save(output_path, "PNG")

        logger and logger.debug(f"  {density}: {size}×{size} → {output_path.name}")

    logger and logger.success("Icon injected into all densities (mipmap-*)")
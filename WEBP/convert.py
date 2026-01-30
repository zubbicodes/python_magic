from __future__ import annotations

import argparse
import sys
from pathlib import Path


TARGET_DIR = Path(r"d:\StratonAlly\PyhtonScripts\WEBP\target")
OUTPUT_DIR = Path(r"d:\StratonAlly\PyhtonScripts\WEBP\output")


SUPPORTED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
    ".webp",
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert images in target/ to WEBP in output/.")
    parser.add_argument("--target", type=Path, default=TARGET_DIR, help="Input folder to scan.")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR, help="Output folder for WEBP files.")
    parser.add_argument("--quality", type=int, default=80, help="WEBP quality (0-100).")
    parser.add_argument("--method", type=int, default=6, help="WEBP method (0-6).")
    parser.add_argument(
        "--lossless",
        action="store_true",
        help="Use lossless WEBP (often best for logos/PNGs).",
    )
    parser.add_argument("--no-recursive", action="store_true", help="Do not scan subfolders.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output files.")
    return parser.parse_args(argv)


def iter_images(target_dir: Path, recursive: bool) -> list[Path]:
    if not target_dir.exists():
        raise FileNotFoundError(f"Target folder does not exist: {target_dir}")
    if not target_dir.is_dir():
        raise NotADirectoryError(f"Target path is not a folder: {target_dir}")

    iterator = target_dir.rglob("*") if recursive else target_dir.glob("*")
    images: list[Path] = []
    for p in iterator:
        if not p.is_file():
            continue
        if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        images.append(p)
    return images


def output_path_for(input_path: Path, target_dir: Path, output_dir: Path) -> Path:
    rel = input_path.relative_to(target_dir)
    return (output_dir / rel).with_suffix(".webp")


def should_skip(input_path: Path, output_path: Path, force: bool) -> bool:
    if force:
        return False
    if not output_path.exists():
        return False
    try:
        return output_path.stat().st_mtime >= input_path.stat().st_mtime
    except OSError:
        return False


def open_pillow() -> tuple[object, object]:
    try:
        from PIL import Image, UnidentifiedImageError  # type: ignore
    except Exception:
        print(
            "Missing dependency: Pillow.\n\nInstall it with:\n  py -m pip install pillow\n",
            file=sys.stderr,
        )
        raise
    return Image, UnidentifiedImageError


def convert_one(
    Image: object,
    UnidentifiedImageError: object,
    input_path: Path,
    output_path: Path,
    *,
    quality: int,
    method: int,
    lossless: bool,
) -> None:
    try:
        with Image.open(input_path) as im:  # type: ignore[attr-defined]
            if getattr(im, "is_animated", False):
                try:
                    im.seek(0)
                except Exception:
                    pass

            save_kwargs: dict[str, object] = {
                "format": "WEBP",
                "quality": quality,
                "method": method,
                "lossless": lossless,
            }

            output_path.parent.mkdir(parents=True, exist_ok=True)
            im.save(output_path, **save_kwargs)
    except UnidentifiedImageError as e:  # type: ignore[misc]
        raise ValueError(f"Unsupported or corrupted image: {input_path}") from e


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    target_dir: Path = args.target
    output_dir: Path = args.output
    quality: int = int(args.quality)
    method: int = int(args.method)
    lossless: bool = bool(args.lossless)
    recursive: bool = not bool(args.no_recursive)
    force: bool = bool(args.force)

    if not (0 <= quality <= 100):
        print("--quality must be between 0 and 100.", file=sys.stderr)
        return 2
    if not (0 <= method <= 6):
        print("--method must be between 0 and 6.", file=sys.stderr)
        return 2

    try:
        Image, UnidentifiedImageError = open_pillow()
    except Exception:
        return 1

    try:
        images = iter_images(target_dir, recursive=recursive)
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 2

    if not images:
        print(f"No supported images found in: {target_dir}")
        return 0

    converted = 0
    skipped = 0
    failed = 0

    total = len(images)

    for idx, input_path in enumerate(images, start=1):
        out_path = output_path_for(input_path, target_dir=target_dir, output_dir=output_dir)
        try:
            rel = str(input_path.relative_to(target_dir))
        except Exception:
            rel = str(input_path.name)

        if should_skip(input_path, out_path, force=force):
            skipped += 1
            print(f"[{idx}/{total}] Skipped: {rel}", flush=True)
            continue

        try:
            convert_one(
                Image,
                UnidentifiedImageError,
                input_path,
                out_path,
                quality=quality,
                method=method,
                lossless=lossless,
            )
            converted += 1
            print(f"[{idx}/{total}] Converted: {rel}", flush=True)
        except Exception as e:
            failed += 1
            print(f"[{idx}/{total}] Failed: {rel}\n  {e}", file=sys.stderr)

    print(
        f"Done. Converted: {converted}, Skipped: {skipped}, Failed: {failed}\n"
        f"Output folder: {output_dir}"
    )

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

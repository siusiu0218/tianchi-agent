"""Generate build artwork and copy installed dependency license notices."""
from importlib import metadata
from pathlib import Path

from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
target = root / ".scratch" / "desktop-assets"
target.mkdir(parents=True, exist_ok=True)
image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((8, 8, 248, 248), radius=54, fill="#2864d8")
draw.rounded_rectangle((45, 56, 211, 176), radius=28, fill="white")
draw.polygon([(69, 160), (69, 208), (112, 173)], fill="white")
for x in (82, 128, 174):
    draw.ellipse((x - 10, 105, x + 10, 125), fill="#2864d8")
image.save(target / "icon.png")
image.save(target / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
packages = ["PySide6", "PySide6_Essentials", "shiboken6", "pandas", "numpy", "openpyxl", "Pillow",
            "requests", "certifi", "charset-normalizer", "idna", "urllib3", "python-dateutil",
            "pytz", "tzdata", "et-xmlfile", "six", "packaging"]
manifest = []
for name in packages:
    dist = metadata.distribution(name)
    manifest.append(f"{name}=={dist.version}")
    for file in dist.files or []:
        if any(word in str(file).lower() for word in ("license", "copying", "copyright", "notice")):
            source = dist.locate_file(file)
            if source.is_file() and source.suffix.lower() not in (".py", ".pyc", ".pyd", ".dll"):
                # Use package-relative paths only; RECORD entries may point outside site-packages.
                parts = [part for part in Path(str(file)).parts if part not in ("..", ".")]
                destination = target / "licenses" / name / Path(*parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
(target / "dependencies.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
(target / "THIRD-PARTY-NOTICES.txt").write_text(
    "EmpathyCopilot bundles third-party libraries. See dependencies.txt and licenses/.\n"
    "Qt / PySide6 project and source: https://code.qt.io/pyside/pyside-setup.git/\n"
    "Qt source: https://download.qt.io/archive/qt/\n"
    "Qt is dynamically linked; its libraries reside in _internal/PySide6.\n"
    "This application does not restrict replacement of Qt libraries or reverse engineering\n"
    "for debugging modifications to those libraries under their applicable license.\n", encoding="utf-8")

"""Compila la APK de Android de forma reproducible.

La app vive en `mobile/` como paquete (`mobile.*`), pero `flet build apk`
empaqueta el contenido de la carpeta del proyecto en la raíz de la app.
Por eso se arma una carpeta temporal con `main.py` en la raíz y el paquete
`mobile/` completo, que es la estructura que espera el APK.

Uso:
    python mobile/build_apk.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

MOBILE = Path(__file__).resolve().parent
REPO = MOBILE.parent
STAGE = REPO / ".apk_build"
DEST = REPO / "backend" / "static" / "downloads" / "TuPedidoJR.apk"

SKIP_DIRS = {"build", "__pycache__", ".flet", ".dart_tool"}
PACKAGE_DIRS = {"screens", "components"}


def stage() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    shutil.copy2(MOBILE / "main.py", STAGE / "main.py")

    package = STAGE / "mobile"
    package.mkdir()
    for item in MOBILE.iterdir():
        if item.name in SKIP_DIRS or item.name == "main.py":
            continue
        if item.is_dir() and item.name in PACKAGE_DIRS:
            shutil.copytree(
                item, package / item.name, ignore=shutil.ignore_patterns("__pycache__")
            )
        elif item.is_file() and (item.suffix == ".py" or item.name.endswith(".txt")):
            shutil.copy2(item, package / item.name)

    shutil.copytree(
        MOBILE / "assets", STAGE / "assets", ignore=shutil.ignore_patterns("__pycache__")
    )

    pyproject = (MOBILE / "pyproject.toml").read_text(encoding="utf-8")
    if "flet-local-auth" in pyproject:
        pyproject = "\n".join(
            line for line in pyproject.splitlines() if "flet-local-auth" not in line
        )
        pyproject += "\n"
    (STAGE / "pyproject.toml").write_text(pyproject, encoding="utf-8")


def build() -> Path:
    flet = shutil.which("flet")
    if not flet:
        raise SystemExit("No se encontró el comando 'flet'. Instala flet 0.85.2.")
    subprocess.run(
        [
            flet,
            "build",
            "apk",
            "--verbose",
            "--splash-color",
            "#FFFFFF",
            "--splash-dark-color",
            "#0B1A45",
        ],
        cwd=STAGE,
        check=True,
    )
    output_dir = STAGE / "build" / "apk"
    candidates = [output_dir / "TuPedidoJR.apk", output_dir / "mobile.apk"]
    apk = next((path for path in candidates if path.is_file()), None)
    if apk is None:
        raise SystemExit(f"No se generó la APK en {output_dir}")
    return apk


def main() -> None:
    stage()
    apk = build()
    DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(apk, DEST)
    print(f"APK lista: {DEST} ({DEST.stat().st_size} bytes)")


if __name__ == "__main__":
    sys.exit(main())

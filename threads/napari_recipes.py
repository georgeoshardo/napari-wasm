"""Make build/threads/napari-recipes: pyodide-recipes, with napari's unused dependencies dropped.

Usage: python threads/napari_recipes.py

Pyodide's builder builds every runtime dependency a recipe declares. Some of
those are never imported by napari: scikit-image lists pywavelets (only
skimage.restoration uses it) and networkx, whose recipe lists matplotlib.
Every recipe is linked from build/threads/recipes/packages except the ones
rewritten here; the dropped packages are registered as installed when napari
is installed (wasm_shims.install_napari), and pure-Python ones come from PyPI.
The recipes in threads/recipes (newer versions, and packages pyodide-recipes
doesn't have) take the place of pyodide-recipes' own.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "build" / "threads" / "recipes" / "packages"
OWN = ROOT / "threads" / "recipes"
TARGET = ROOT / "build" / "threads" / "napari-recipes"

# recipe -> runtime dependencies to keep (the compiled ones napari needs)
RUN_DEPENDENCIES = {
    "scikit-image": ["numpy", "scipy"],
}

TARGET.mkdir(parents=True, exist_ok=True)
for recipe in sorted(SOURCE.iterdir()):
    if not (recipe / "meta.yaml").exists():
        continue
    link = TARGET / recipe.name
    if recipe.name in RUN_DEPENDENCIES:
        if link.is_symlink():
            link.unlink()
        link.mkdir(exist_ok=True)
        for item in recipe.iterdir():
            if item.name != "meta.yaml" and not (link / item.name).exists():
                (link / item.name).symlink_to(item)
        meta = (recipe / "meta.yaml").read_text()
        keep = "".join(f"    - {name}\n" for name in RUN_DEPENDENCIES[recipe.name])
        meta, count = re.subn(r"(  run:\n)(    - .*\n)+", rf"\g<1>{keep}", meta)
        assert count == 1, recipe.name
        (link / "meta.yaml").write_text(meta)
        print(f"{recipe.name}: run dependencies {RUN_DEPENDENCIES[recipe.name]}")
    elif not link.exists():
        link.symlink_to(recipe)
for recipe in sorted(OWN.iterdir()):
    if not (recipe / "meta.yaml").exists():
        continue
    link = TARGET / recipe.name
    if link.is_symlink() and link.resolve() != recipe:
        link.unlink()
    if not link.exists():
        link.symlink_to(recipe)
print(TARGET)

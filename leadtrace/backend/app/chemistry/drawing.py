from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from io import BytesIO
import json

from rdkit import Chem, rdBase
from rdkit.Chem import Draw

from app.chemistry.validation import ChemistryValidationError, validate_structure


DEFAULT_RENDER_VERSION = "leadtrace-rdkit-v1"


@dataclass(frozen=True, slots=True)
class DrawingOptions:
    width: int = 600
    height: int = 420
    atom_indices: bool = False
    transparent_background: bool = False

    def __post_init__(self) -> None:
        if self.width < 120 or self.width > 2400 or self.height < 120 or self.height > 2400:
            raise ValueError("Drawing dimensions must be between 120 and 2400 pixels")


def drawing_key(
    smiles: str,
    *,
    options: DrawingOptions = DrawingOptions(),
    rdkit_version: str = rdBase.rdkitVersion,
    render_version: str = DEFAULT_RENDER_VERSION,
) -> str:
    validation = validate_structure(smiles)
    if not validation.parseable or validation.canonical_isomeric_smiles is None:
        raise ChemistryValidationError("A parseable SMILES is required for drawing")
    payload = {
        "canonical_isomeric_smiles": validation.canonical_isomeric_smiles,
        "drawing_options": asdict(options),
        "rdkit_version": rdkit_version,
        "render_version": render_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def render_structure_png(
    smiles: str,
    *,
    options: DrawingOptions = DrawingOptions(),
) -> bytes:
    validation = validate_structure(smiles)
    if not validation.parseable or validation.canonical_isomeric_smiles is None:
        raise ChemistryValidationError("A parseable SMILES is required for drawing")
    molecule = Chem.MolFromSmiles(validation.canonical_isomeric_smiles)
    if molecule is None:
        raise ChemistryValidationError("A parseable SMILES is required for drawing")
    if options.atom_indices:
        for atom in molecule.GetAtoms():
            atom.SetProp("atomNote", str(atom.GetIdx()))
    image = Draw.MolToImage(
        molecule,
        size=(options.width, options.height),
        kekulize=True,
        fitImage=True,
    )
    if options.transparent_background:
        image = image.convert("RGBA")
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                red, green, blue, alpha = pixels[x, y]
                if red > 250 and green > 250 and blue > 250:
                    pixels[x, y] = (red, green, blue, 0)
                else:
                    pixels[x, y] = (red, green, blue, alpha)
    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()

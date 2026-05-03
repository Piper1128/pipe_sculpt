from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    voxel_size_factor: float
    use_symmetry_x: bool
    use_symmetry_y: bool
    use_symmetry_z: bool
    multires_levels: int
    target_faces_attr: str


PRESETS: tuple[Preset, ...] = (
    Preset(
        id='CHARACTER',
        label='Character',
        voxel_size_factor=0.025,
        use_symmetry_x=True,
        use_symmetry_y=False,
        use_symmetry_z=False,
        multires_levels=4,
        target_faces_attr='target_faces_character',
    ),
    Preset(
        id='BUST',
        label='Bust + Face',
        voxel_size_factor=0.012,
        use_symmetry_x=True,
        use_symmetry_y=False,
        use_symmetry_z=False,
        multires_levels=5,
        target_faces_attr='target_faces_bust',
    ),
    Preset(
        id='PROP',
        label='Prop',
        voxel_size_factor=0.030,
        use_symmetry_x=False,
        use_symmetry_y=False,
        use_symmetry_z=False,
        multires_levels=3,
        target_faces_attr='target_faces_prop',
    ),
)


PRESETS_BY_ID = {p.id: p for p in PRESETS}


def preset_enum_items():
    return tuple((p.id, p.label, "") for p in PRESETS)


DEFAULT_PRESET_ID = 'BUST'

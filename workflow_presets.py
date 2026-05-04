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
    target_faces_default: int


PRESETS: tuple[Preset, ...] = (
    Preset(
        id='CHARACTER',
        label='Character',
        # 0.010 = ~2.4 cm voxel on a 2.4 m humanoid; fine enough for fingers
        # and face features to survive remesh (was 0.025 = 6 cm, too coarse).
        voxel_size_factor=0.010,
        use_symmetry_x=True,
        use_symmetry_y=False,
        use_symmetry_z=False,
        multires_levels=4,
        target_faces_attr='target_faces_character',
        target_faces_default=22000,
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
        target_faces_default=14000,
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
        target_faces_default=8000,
    ),
)


PRESETS_BY_ID = {p.id: p for p in PRESETS}


def preset_enum_items():
    return tuple((p.id, p.label, "") for p in PRESETS)


DEFAULT_PRESET_ID = 'BUST'

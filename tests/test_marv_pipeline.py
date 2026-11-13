"""tools/marv_pipeline.py: the mv-cli script, the pose parser, Blender's command line."""
import pytest

import marv_pipeline as mp

# The script that reproduced the viewmodel body of 2026-11-13 byte for byte
# (OBJ md5 404854baca776ddbd39285beb0c7754d, joints 2b83eb7a2f47447c0f0a65cbdaccda77,
# mv-cli at marv 204e909): the Marv lab's cube, cell, budget and floor.
KNOWN_MALE = (
    "joints j.json male 1756.2\n"
    "exterior B male 1756.2\n"
    "mesh M B -891.805 888.725 -3.13 1777.3999999999999 -859.855 920.675"
    " 7.024747265625 1000000\n"
    "collapse C M 0.2\n"
    "obj C b.obj\n")


def test_script_reproduces_the_known_body():
    assert mp.marv_script("male", 1756.2, "", "j.json", "b.obj") == KNOWN_MALE


def test_pose_goes_on_joints_and_exterior_only():
    s = mp.marv_script("female", 1628.5, mp.parse_pose("legs 20 arms 12"), "j", "o")
    lines = s.splitlines()
    assert lines[0].endswith("1628.5 arms 12.0 legs 20.0")
    assert lines[1].endswith("1628.5 arms 12.0 legs 20.0")
    assert "arms" not in lines[2] and "arms" not in lines[3]


@pytest.mark.parametrize("bad", ["arms", "arms x", "hands 3", "arms 1 arms 2"])
def test_pose_refuses(bad):
    with pytest.raises(ValueError):
        mp.parse_pose(bad)


def test_unknown_sex_refused():
    with pytest.raises(ValueError):
        mp.marv_script("other", 1700.0, "", "j", "o")


def test_blender_exit_code_flag_precedes_python():
    cmd = mp.blender_cmd("blender.exe", "t.py", ["a", "b"])
    assert cmd.index("--python-exit-code") < cmd.index("--python")
    assert cmd[cmd.index("--") + 1:] == ["a", "b"]


def test_split_flag_passed_only_when_asked():
    assert "--split-viewmodel" in mp.to_unity_args("j", "f", "o", "r", True)
    assert "--split-viewmodel" not in mp.to_unity_args("j", "f", "o", "r", False)


def test_required_quantity():
    doc = {"quantities": [{"name": "stature"}, {"name": mp.DEFAULT_REQUIRED_QUANTITY}]}
    assert mp.has_quantity(doc, mp.DEFAULT_REQUIRED_QUANTITY)
    assert not mp.has_quantity({"quantities": [{"name": "stature"}]},
                               mp.DEFAULT_REQUIRED_QUANTITY)
    assert not mp.has_quantity({}, "stature")


def test_missing_mv_cli_could_not_run(tmp_path):
    assert mp.main([str(tmp_path), "--mv-cli", str(tmp_path / "nope"),
                    "--blender", "x"]) == 2

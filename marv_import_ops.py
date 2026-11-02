"""Marv import — Blender operator for marv_import_core.

Reads a Marv body (OBJ with one group per bone + joints.json), builds the
mesh, writes the GTR bone-tag attribute and the bone metadata, and leaves
the object ready for Retopo / Generate Rig exactly like a starter would.
"""
from __future__ import annotations

import json
import os

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from . import marv_import_core as core
from . import rigging


PROVENANCE_PROP = "pipe_sculpt_marv_provenance"
REST_POSE_PROP = "pipe_sculpt_marv_rest_pose"


def build_object(context, body: core.MarvBody, name: str):
    """Create the mesh object for a MarvBody and attach GTR tags + metadata."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(body.vertices, [], body.faces)
    mesh.validate(clean_customdata=False)
    if len(mesh.vertices) != len(body.vertices):
        # validate() merged or dropped vertices: the tags would no longer line up.
        bpy.data.meshes.remove(mesh)
        raise core.MarvImportError(
            f"Blender changed the vertex count on validate "
            f"({len(body.vertices)} -> {len(mesh.vertices)}); OBJ has degenerate geometry"
        )
    obj = bpy.data.objects.new(name, mesh)
    context.collection.objects.link(obj)

    attr = mesh.attributes.new(name=rigging.VERTEX_ATTR, type='INT', domain='POINT')
    attr.data.foreach_set("value", body.vertex_tags)

    obj[rigging.META_PROP] = json.dumps({"bones": body.bones, "ik": []})
    obj[rigging.RIG_TYPE_PROP] = 'HUMANOID'
    obj[PROVENANCE_PROP] = json.dumps(body.provenance)
    if body.rest_pose is not None:
        obj[REST_POSE_PROP] = str(body.rest_pose)
    return obj


def import_files(context, joints_path: str, obj_path: str):
    with open(joints_path, encoding="utf-8") as f:
        doc = json.load(f)
    with open(obj_path, encoding="utf-8") as f:
        obj_text = f.read()
    body = core.build_body(doc, obj_text, rigging.BONE_NAME_TO_INDEX)
    name = os.path.splitext(os.path.basename(obj_path))[0]
    return build_object(context, body, name)


class PIPESCULPT_OT_import_marv(Operator, ImportHelper):
    bl_idname = "pipe_sculpt.import_marv"
    bl_label = "Import Marv Body"
    bl_description = (
        "Import a Marv body: OBJ with one group per bone + joints.json. "
        "The groups become GTR bone tags and the joint centres become the "
        "armature, so Retopo and Generate Rig work as on a starter"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})
    obj_path: StringProperty(
        name="OBJ",
        description="Body mesh. Empty = 'mesh' field in joints.json, relative to it",
        subtype='FILE_PATH',
        default="",
    )

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        joints_path = bpy.path.abspath(self.filepath)
        obj_path = bpy.path.abspath(self.obj_path) if self.obj_path else ""
        try:
            if not obj_path:
                with open(joints_path, encoding="utf-8") as f:
                    rel = json.load(f).get("mesh")
                if not rel:
                    raise core.MarvImportError("no OBJ given and joints.json has no 'mesh' field")
                obj_path = os.path.join(os.path.dirname(joints_path), rel)
            obj = import_files(context, joints_path, obj_path)
        except (OSError, ValueError) as e:  # MarvImportError and JSON errors are ValueErrors
            self.report({'ERROR'}, f"Marv import failed: {e}")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        n_bones = sum(1 for b in json.loads(obj[rigging.META_PROP])["bones"] if b["kind"] == 'D')
        self.report(
            {'INFO'},
            f"Imported '{obj.name}': {len(obj.data.vertices):,} verts, {n_bones} bones",
        )
        return {'FINISHED'}


_classes = (PIPESCULPT_OT_import_marv,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

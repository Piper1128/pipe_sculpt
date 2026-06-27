"""Project setup wizard — bpy adapter for project_core."""
from __future__ import annotations

import os

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from . import project_core


class PIPESCULPT_OT_project_setup(Operator):
    bl_idname = "pipe_sculpt.project_setup"
    bl_label = "New PipeSculpt Project"
    bl_description = (
        "Create a new project folder with PipeSculpt's standard layout "
        "(sculpt/, low/, textures/, exports/, references/) and save a "
        "fresh .blend file inside it"
    )
    bl_options = {'REGISTER'}

    project_name: StringProperty(
        name="Project Name",
        description="Folder name for the new project. Letters/digits/underscore/hyphen/space",
        default="MyCharacter",
    )
    parent_dir: StringProperty(
        name="Parent Folder",
        description="The new <project name>/ folder will be created here",
        default="",
        subtype='DIR_PATH',
    )
    save_blend: BoolProperty(
        name="Save .blend File",
        description="Save a fresh .blend inside the project folder. Disabling lets you keep the current scene",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        if not self.parent_dir:
            current_blend = bpy.data.filepath
            if current_blend:
                self.parent_dir = os.path.dirname(current_blend)
            else:
                self.parent_dir = os.path.expanduser("~")
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "project_name")
        layout.prop(self, "parent_dir")
        layout.prop(self, "save_blend")

        # Validation feedback
        err = project_core.validate_project_name(self.project_name)
        if err is not None:
            layout.label(text=err, icon='ERROR')
            return
        if not project_core.is_directory_writeable(bpy.path.abspath(self.parent_dir)):
            layout.label(text="Parent folder doesn't exist / isn't writeable", icon='ERROR')
            return

        # Preview the layout
        box = layout.box()
        box.label(text="Will create:", icon='FILE_FOLDER')
        summary = project_core.project_summary(
            bpy.path.abspath(self.parent_dir), self.project_name.strip(),
        )
        for line in summary.split("\n"):
            box.label(text=line)

    def execute(self, context):
        name = self.project_name.strip()
        parent = bpy.path.abspath(self.parent_dir)

        err = project_core.validate_project_name(name)
        if err is not None:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        if not project_core.is_directory_writeable(parent):
            self.report(
                {'ERROR'},
                f"Parent folder doesn't exist or isn't writeable: {parent}",
            )
            return {'CANCELLED'}

        paths = project_core.project_paths(parent, name)
        if os.path.exists(paths['root']):
            self.report({'ERROR'}, f"Project folder already exists: {paths['root']}")
            return {'CANCELLED'}

        # Create the layout
        os.makedirs(paths['root'])
        for sub_path in paths['subfolders'].values():
            os.makedirs(sub_path)

        # Save .blend file inside project root
        if self.save_blend:
            try:
                bpy.ops.wm.save_as_mainfile(filepath=paths['blend_file'])
            except RuntimeError as e:
                self.report({'WARNING'}, f"Project folders created but .blend save failed: {e}")
                return {'FINISHED'}

        self.report(
            {'INFO'},
            f"Project '{name}' created at {paths['root']} "
            f"({len(paths['subfolders'])} subfolders, .blend saved)",
        )
        return {'FINISHED'}


_classes = (PIPESCULPT_OT_project_setup,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

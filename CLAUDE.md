# PipeSculpt

Personligt Blender **5.x** addon (`blender_version_min = 5.0.0`): sculpt → retopo →
rig → animate → hair. **Ikke IronCore** — men bygget efter husets Born Clean-regler.

## Arkitekturen der gør det testbart
`*_core.py` = ren Python, ingen `bpy`. `*_ops.py` = Blender-operatorerne.
`__init__.py` importerer **lazy** inde i `_modules()`, så pytest-discovery ikke
crasher uden for Blender. Bryd aldrig det split — det er hele grunden til at
kernen kan unit-testes.

```bash
pytest                    # tests/ importerer core-modulerne via conftest.py's importlib-loader
python tools/api_audit.py # bpy-API-audit
```

Blender 5.x API'et er stadig i bevægelse: **verificér hvert kald mod den faktiske
version** — antag ikke at et 4.x-mønster stadig virker. SculptKit/GTR-teknikken er
novel og uden prior art; verificér hvert step (`feedback_unknown_territory.md`).

Designnoter ligger som `*_PLAN.md` / `*_TEST.md` / `*_REVIEW.md` i roden.
`blender_manifest.toml` bærer versionen — bump den ved udgivelse, `pack.py` pakker.

# PipeSculpt Animation Module — feature-plan til koderen

**Til:** koderen på PipeSculpt
**Formål:** gøre selve det at *lave animationer* i Blender hurtigere og mindre smertefuldt på vores egne (GTR-)rigs, eksporterbart til Unity 6. Internt holdværktøj — målet er "samme som de etablerede tools, og bedre på vores pipeline", ikke salg.
**Status:** plan, ingen kode skrevet endnu. Faseinddelt efter indsats/risiko.

---

## 0. TL;DR + anbefaling

Vi bygger ét nyt modul `anim_ops.py` + en "Animate"-sektion i N-panelet, i præcis samme mønster som resten af addon'et (operators, panel, evt. pie, headless smoke-tests).

**Anbefalet rækkefølge:**

1. **FASE 1 (byg nu): Pose + Keying + Loop quick-tools.** Ren operator-kode, nul afhængighed af ustabil ny API, headless-testbar fra commit #1, højeste daglige gevinst pr. indsats. Dette er kilen.
2. **FASE 2: Auto-genereret bone-picker.** Største enkelt-løft af *følelsen* af at animere. Billigere for os end for nogen anden fordi GTR-metadataen kender bone-navnene.
3. **FASE 3: Clip/action-manager + additive layers + onion skinning.** Kræver et **spike på slotted-actions API'en (Blender 4.4+/5.1) FØR planlægning** — vi antager ikke at det virker. Højere risiko.

Byg ikke fase 3 før fase 1 + et spike-notat ligger. Se §6.

---

## 1. Modulets form (konsistent med addon'et)

```
anim_core.py        # POCO-agtig logik: pose-math, loop-validering, mirror-mapping.
                    #   Ingen bpy.ops — tager data ind, returnerer data. Headless-unit-testbar.
anim_ops.py         # Operators (PIPESCULPT_OT_anim_*). Tynd bpy-shell over anim_core.
anim_panel.py       # "Animate"-sektion i N-panelet (eller udvid workflow_panel.py).
tests/test_anim_core.py   # pytest, samme stil som test_validator_core.py / test_project_core.py
```

Hvorfor `anim_core.py` adskilt: vi har allerede `validator_core.py`, `project_core.py`, `palette_core.py`, `hair_core.py` med tilhørende `tests/test_*_core.py`. Følg det. Al logik der KAN testes uden Blender (mirror-bone-navne, loop first==last-sammenligning, frame-range-math) lægges i `anim_core.py` og unit-testes headless. `anim_ops.py` holder kun bpy-kald.

Panel-placering: ny "Animate"-sektion mellem "Rigging" og "Export" i `workflow_panel.py` (animation kommer efter rig, før export i pipelinen).

---

## 2. FASE 1 — Pose + Keying + Loop (byg nu)

Alle operators herunder er ren `bpy`-kode uden ny anim-API. Pie-genvej (valgfri): en "Animate"-pie på en ledig tast i samme stil som Q/Shift+Q.

### 2.1 Pose quick-tools

| Operator | bl_idname | Gør | Headless-testbar del |
|---|---|---|---|
| Copy Pose | `pipe_sculpt.anim_copy_pose` | Kopiér transform på valgte (eller alle) pose-bones til en intern buffer | — |
| Paste Pose | `pipe_sculpt.anim_paste_pose` | Indsæt buffer på samme bones | — |
| Paste Mirrored | `pipe_sculpt.anim_paste_pose_mirror` | Indsæt buffer spejlet over X (`.L`↔`.R`) | **mirror-navne-mapping** |
| Mirror Pose | `pipe_sculpt.anim_mirror_pose` | Spejl nuværende pose i ét klik (L↔R) | **mirror-mapping** |
| Reset to Rest | `pipe_sculpt.anim_reset_pose` | Nulstil valgte/alle bones til rest (loc/rot/scale identity) | — |
| Breakdown Slider | `pipe_sculpt.anim_breakdown` | Modal: træk for at blende valgte bones mod forrige↔næste key (tween machine) | **blend-interpolation-math** |

Mirror-mapping (`.L`↔`.R`) lever i `anim_core.py` og dækker GTR's navnekonvention (`upper_arm.L`, `index_02.R`, …). Det er den eneste ikke-trivielle del — unit-test den mod den fulde `DEFORM_BONE_NAMES`-liste fra `rigging.py` så vi ved at hver bone har en korrekt modpart (eller eksplicit "centerline, ingen mirror" for pelvis/spine/chest/neck/head/jaw/root/tail/beak).

Breakdown-slideren er det højest værdsatte enkelt-værktøj (Maya "tween machine"-ækvivalent). Math: `result = lerp(prev_key_value, next_key_value, t)` pr. kanal, hvor `t` styres af musen. Den rene lerp + key-lookup hører i core; kun den modale musehåndtering i ops.

### 2.2 Keying helpers

| Operator | bl_idname | Gør |
|---|---|---|
| Key Whole Rig | `pipe_sculpt.anim_key_rig` | Insert keyframe på ALLE deform+control pose-bones (loc/rot/scale) på current frame |
| Key Selected | `pipe_sculpt.anim_key_selected` | Insert keyframe kun på valgte bones |
| Toggle Stepped/Spline | `pipe_sculpt.anim_toggle_interp` | Skift alle keys på aktiv action mellem CONSTANT (blocking) og BEZIER (spline) |
| Fit Preview Range | `pipe_sculpt.anim_fit_range` | Sæt scene preview-range til aktiv actions frame_range (så loop-preview rammer præcist) |

Disse er små, men er det man rører hvert minut. `Toggle Stepped/Spline` er kritisk for blocking→spline-workflowet og findes ikke som ét-klik native.

### 2.3 Loop authoring (rammer Unity-export direkte)

| Operator | bl_idname | Gør | Headless-testbar |
|---|---|---|---|
| Make Cyclic | `pipe_sculpt.anim_make_cyclic` | Kopiér frame N's pose til frame 1 (eller omvendt) så cyklen lukker, og sæt Cycles-modifier (`make_cyclic`) på alle F-curves | **first==last sammenligning** |
| Validate Loop | `pipe_sculpt.anim_validate_loop` | Rapportér pr. kanal om frame 1 == frame N inden for tolerance; highlight de bones der "popper" | **diff-rapport** |
| Bake In-Place | `pipe_sculpt.anim_bake_in_place` | Fjern root-bones XY-translation (behold Z hvis ønsket) så cyklen ikke driver — til Unity "Bake Into Pose" | **translation-strip-logik** |

`Validate Loop` er svaret på Blenders egen åbne issue #54724 ("looping føles som magiske besværgelser"). Den gør loop-fejl *synlige* i stedet for at man opdager dem i Unity. Diff-logikken (sammenlign to frames' bone-transforms inden for epsilon) er ren math → core + unit-test.

`Bake In-Place` kobler direkte til vores export: Unity vil have root-motion enten i en root-bone eller fjernet. Vi har allerede `root` som separat control-bone i GTR — perfekt, vi kan beslutte pr. clip om root-translation beholdes (root motion) eller bages væk (in-place loop).

---

## 3. FASE 2 — Auto-genereret bone-picker

**Type:** [Interface] + [Kode]. **Indsats:** M-L. **Risiko:** lav-med.

Blender har ingen native klikbar bone-picker (Maya/3ds Max har). For en hvilken som helst anden rig skal man konfigurere den manuelt. **Vi kan auto-bygge den**, fordi GTR-metadataen (`META_PROP` JSON på meshet) allerede indeholder hele bone-hierarkiet med `kind` og navne.

**Design:**
- Et N-panel-afsnit (eller popup, `invoke_popup`) der tegner en knap-grid: én knap pr. control/deform-bone, grupperet (krop / venstre arm / højre arm / ben / hænder / ansigt).
- Klik = select den pose-bone (Shift-klik = add to selection). Det fjerner viewport-jagten efter små bones.
- Layout udledes af bone-navne: alt med `.L` i venstre kolonne, `.R` i højre, centerline i midten — spejlet grid der ligner kroppen.
- Genereres pr. rig-type (humanoid/quadruped/bird/mech) ud fra `_RIG_TABLES`, så den virker for alle vores rigs uden manuel opsætning.

**Begrænsning at være ærlig om:** Blenders UI tegner knap-grids fint, men en *fri 2D-picker med vilkårligt placerede knapper* (som Maya) kræver enten `UILayout`-grid (begrænset) eller en GPU-tegnet overlay (mere arbejde). Start med grid-versionen; GPU-overlay er en mulig senere opgradering, ikke fase 2.

---

## 4. FASE 3 — Clip-manager, layers, onion skinning (spike først)

Disse er de mest værdifulde "rigtige animator"-features, men de **rører den nye animations-datamodel** (slotted/layered actions, Blender 4.4+, og den gamle F-curve-API er deprecated og fjernes i 5.0). Vi bygger dem ikke før et spike bekræfter hvad API'en faktisk kan i 5.1. Se §6.

| Feature | Type | Indsats | Risiko | Noter |
|---|---|---|---|---|
| **E. Clip/action-manager** | [Interface]+[Kode] | M | Med | Liste over alle actions på karakteren: ét-klik aktivér / dup / rename / push-til-NLA / batch-export. Bør bygges på **slot**-modellen så flere clips på samme rig håndteres rent. Erstatter NLA-smerten for clip-styring |
| **G. Additive layers** | [Kode] | L | Høj | Recoil/breathing/flinch oven på en base-cyklus uden NLA-tweak-mode-helvedet. Slotted/layered actions er bygget til netop dette, men API'en stabiliserer stadig |
| **F. Onion skinning for rigs** | [Kode] | L | Høj | Ghost-poser N frames før/efter. Native kun for grease pencil. Kræver depsgraph-mesh-eval pr. ghost-frame eller GPU-overlay. Stor efterspørgsel, men dyrt — uden klar prior art for deform-rigs |

**Prioritet inden for fase 3:** E (clip-manager) før G (layers) før F (onion skinning). E giver mest værdi for mindst risiko; F er den dyreste og mest usikre.

---

## 5. Unity 6 export-hensyn (gælder alle faser)

- **Loop:** in-place cyklusser skal lukke (frame1==frameN) → fase 1 `Validate Loop` + `Bake In-Place`. Unity-side: "Bake Into Pose" på root position, "Based Upon: Body Orientation" på rotation.
- **Root motion:** behold `root`-bones translation for root-motion-clips, strip for in-place. GTR's separate `root`-bone gør begge dele mulige fra samme rig.
- **Deform-only:** export skal droppe `kind='C'` bones (jf. GTR_RIG_REVIEW.md fund C) — animation-clips på control-bones skal bages ned på deform-bones før FBX, ellers eksporterer vi tomme deform-kurver.
- **Humanoid vs Generic:** humanoid-clips retargeter via Unity Avatar (roll irrelevant); quadruped/bird/mech er Generic (roll + lokale akser betyder noget — jf. fund A).

---

## 6. Born Clean + spike-krav

**Born Clean for dette modul:**
- `anim_core.py` = ren logik, ingen `bpy.ops`, ingen global state → headless unit-tests fra commit #1 (følg `tests/test_validator_core.py`-mønstret).
- `anim_ops.py` = tynde operator-shells. Hver operator har en `poll()` der tjekker at der er en armatur i pose-mode.
- Idempotens: operators der bygger/ændrer (Make Cyclic, Bake In-Place) skal kunne køres to gange uden at akkumulere fejl — samme princip som Generate Rig's idempotens.

**Spike FØR fase 3 (obligatorisk, "unknown territory"):**
Skriv et lille headless-script (samme stil som `tests/verify_rig_axes.py`) der i Blender 5.1 svarer på:
1. Kan vi oprette/aflæse **slots** på en Action via den nye Python-API? (`action.slots`, `action.layers`, channelbags)
2. Kan vi lægge en **additiv layer** og blande den? Hvad er den faktiske API-overflade i 5.1 (ikke docs — kør det)?
3. Er den gamle F-curve-API stadig nødvendig for noget vi har brug for, og hvornår forsvinder den?

Først når spiket svarer, planlægger vi E/G konkret. Indtil da: fase 1 og 2 bruger den stabile, eksisterende API og er ikke blokeret.

---

## 7. Anbefalet næste skridt

1. Byg **fase 1** som ét `anim_core.py` + `anim_ops.py` + "Animate"-panel + `tests/test_anim_core.py`. Start med pose-mirror-mapping og loop-validering (de to ting med reel logik at unit-teste).
2. Kør **spiket** (§6) parallelt eller umiddelbart efter — det afgør om fase 3 overhovedet er realistisk i 5.1.
3. **Fase 2** (bone-picker) når fase 1 er i brug og vi ved hvilke bones folk faktisk vælger oftest.

Mindste meningsfulde første commit: `anim_core.mirror_bone_name()` + dens unit-test + `Mirror Pose`-operatoren. Det er nyttigt fra dag 1 og etablerer modulets struktur.

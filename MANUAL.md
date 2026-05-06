# PipeSculpt — Manual for nybegyndere

Denne guide forudsætter at du **aldrig har sculptet i Blender før**. Den tager
dig fra installation til en færdig Unity-klar karakter.

> **Forudsætninger:** Blender 5.0 eller nyere. Hent den fra
> [blender.org/download](https://www.blender.org/download/).

---

## 1. Installation

1. Hent eller byg `pipe_sculpt.zip` (kør `python pack.py` i addon-mappen).
2. Åbn Blender.
3. Gå til **Edit → Preferences → Get Extensions → Install from Disk** (klik
   nedpilen øverst til højre i Extensions-vinduet).
4. Vælg `pipe_sculpt.zip`.
5. Sæt flueben ud for "PipeSculpt" på listen.

Du skulle nu se en **"PipeSculpt"-fane** i N-panelet i 3D Viewport. Hvis du
ikke kan se N-panelet, tryk `N` mens musen er over viewport.

---

## 2. Blender-grundlag (kun det du SKAL vide)

| Tast | Funktion |
|---|---|
| `Mellemrum + scroll-musen` | Zoom |
| `Mid-mus drag` | Roter view |
| `Shift + mid-mus drag` | Pan view |
| `Tab` | Skift mellem Object Mode og Edit/Sculpt |
| `N` | Vis/skjul side-panel (her ligger PipeSculpt) |
| `Ctrl+Z` | Fortryd |
| `Ctrl+S` | Gem fil |

**Vigtigt:** Gem din .blend-fil **før** du starter — bake'd textures gemmes
ved siden af .blend-filen, så hvis filen ikke er gemt nogensteder, gemmes
texturerne kun pakket inde i .blend.

---

## 3. Den korte version af workflowet

```
Vælg starter  →  Start Sculpt  →  Sculpt  →  Add Detail  →  Sculpt mere
                                                  ↓
                                              Retopo (auto eller manuel)
                                                  ↓
                                              Generate Rig (kun humanoid)
                                                  ↓
                                              Bake Maps
                                                  ↓
                                              Export FBX → Unity
```

Hver knap findes i **N-panel → PipeSculpt → Workflow Pipeline**.

---

## 4. Trin 1 — Vælg en starter

I **N-panel → PipeSculpt → Starter Meshes** har du to grupper:

**Generic** (ingen rig-tags):
- **Sphere** — generisk start. Bruges til abstrakte former, idéskitser.
- **Head** — æg-formet sphere, til ansigts-sculpt med single head-pivot.

**Tagged (GTR — Generate Rig works)**:
- **Bust** — hoved + nakke + skuldre. 7-bone rig til portrætter.
- **Humanoid** — fuld krop i T-pose med fingre. 50+ bones, IK på arme/ben.
- **Quadruped** — firbenet dyr (hund/varg/kat). 17-bone rig.
- **Bird** — fugl med spredte vinger. 16-bone rig (vinger + ben + næb).
- **Mech** — humanoid robot uden fingre/kæbe/ører. 17-bone rig + IK.

**Anbefaling for første gang:** klik **Sphere**. Det er den mindst forvirrende.

> ⚠️ **Bust og Humanoid** ser ud som klumper af mange overlappende kugler
> indtil du klikker **Start Sculpt** — det er meningen. Voxel-remesh
> smelter dem sammen.

---

## 5. Trin 2 — Vælg preset og klik Start Sculpt

I **Workflow Pipeline-panelet**:

1. Vælg preset (**Character / Bust+Face / Prop**) — dette styrer voxel-størrelse
   og sculpting-detaljeniveau.
2. Klik **Start Sculpt**.

Hvad sker der bag kulisserne:
- Du bliver sat i Sculpt Mode.
- Voxel-remesh kører og smelter starter-kugler sammen til ÉN sammenhængende
  mesh.
- Symmetri sættes op (X-spejling for karakterer/buster, ingen for props).

**Hvis du ikke ser noget:** zoom ud (scroll-hjul). Voxel-remesh kan have
"krympet" mesh til at virke meget lille i viewport.

---

## 6. Trin 3 — Sculpt med pie-menuerne

Du er nu i Sculpt Mode. Tryk:

- **`Q`** for primary brush-pie (8 brushes — Draw, Clay Strips, Grab,
  Smooth, Crease Sharp, Inflate/Deflate, Flatten/Contrast, Mask)
- **`Shift+Q`** for secondary brush-pie (Clay, Blob, Snake Hook, Pinch/Magnify,
  Scrape/Fill, Fill/Deepen, Elastic Grab, Draw Sharp)

**Vigtige sculpt-kontroller:**
| Input | Funktion |
|---|---|
| Venstre-klik + træk | Sculpt med aktiv brush |
| `[` / `]` | Mindre / større brush |
| `Shift + venstre-klik` | Smooth (uanset hvilken brush) |
| `Ctrl + venstre-klik` | Inverter brush (Draw bliver til "anti-Draw") |
| `F` + bevæg mus | Justér brush-størrelse interaktivt |
| `Shift+F` + bevæg mus | Justér brush-styrke |

**Sculpt-tip for nybegyndere:** start med store brushes til den grove form
(Clay Strips, Grab), zoom ind senere med små brushes til detaljer (Crease
Sharp, Draw Sharp).

---

## 7. Trin 4 — Add Detail når mesh bliver for low-poly

Når du har sculptet den grove form, vil du komme til et punkt hvor brushes
ikke kan tilføje finere detaljer fordi mesh ikke har polygoner nok. Klik
**Add Detail**.

Det opretter en **Multires modifier** og subdivider mesh ét niveau ad
gangen. Klik flere gange for mere detalje. Preset bestemmer maksimum:

- Character: 4 niveauer
- Bust+Face: 5 niveauer
- Prop: 3 niveauer

> ⚠️ Hver Add Detail multiplicerer polygontallet med 4. Niveau 5 = 1024×
> flere polygoner end niveau 0. Stop når detaljer er tilstrækkelige —
> niveau 4 er nok til de fleste karakterer.

---

## 8. Trin 5 — Retopo (lav low-poly version)

Når sculpting er færdig har du en mesh med måske millioner af polygoner.
Til Unity skal vi have ~5.000-30.000. Det kaldes **retopology**.

Du har **to valg**:

### A) Auto-retopo (hurtigst)

Klik **Retopo** i Workflow Pipeline. Vælg metode i pop-up:
- **Quadriflow** (default): Auto quad-retopo. Bedst til organiske former
  (karakterer, kropsdele).
- **Decimate (Collapse)**: Hurtig triangulering. OK til props, **ALDRIG
  til karakterer**.

Resultatet er en ny mesh kaldet `<navn>_retopo`. Original gemmes (skjult).

### B) Manuel retopo (bedst kvalitet, men tidskrævende)

Bruges når Quadriflow giver dårlig topologi (typisk på ansigter eller
mekaniske former).

1. Sørg for high-poly er aktive mesh.
2. Klik **Setup Manual Retopo** under "Manual Retopo".
3. Du er nu i Edit Mode på en lille plane med **Mirror + Shrinkwrap**
   modifiers. Plane er retopo'ens start.
4. **Snap er sat til Face Project** — vertices snapper til high-poly's
   overflade automatisk når du flytter dem (ingen "snap chaos").
5. Sculpt nye polygoner ved at:
   - **Extrude** (`E`) eksisterende edges/faces til nye vertices
   - **Knife** (`K`) til at skære nye edge-loops
   - **Loop cut** (`Ctrl+R`) til loops langs eksisterende geometri
6. Når du har dækket hele high-poly med din lavpolygontopologi, klik
   **Finish Manual Retopo**.

> 💡 **Hvis topologi bliver "klumpet":** vælg de buntede områder, klik
> **Relax Geometry** under Manual Retopo. Det skifter til Sculpt Mode
> med Relax Slide-brush, så du kan male jævnhed uden at ændre formen.

---

## 9. Trin 6 — Generate Rig (Humanoid / Bust / Head)

Alle tre tagged starters har nu bone-hierarchier. Klik **Generate Rig**:

| Starter | Bones | IK |
|---|---|---|
| Humanoid | 50+ (root, spine, hoved, kæbe, ører, kraveben, arme, ben, 30 fingre, 4 IK targets + 4 pole bones) | arme + ben |
| Bust | 7 (root, spine, nakke, hoved, kæbe, ear.L/R) | ingen |
| Head | 2 (root, hoved-pivot) | ingen |

Plus:
- Skin-weights tildeles fra bone-tags (hver vertex får én bone, vægt 1.0).
- Weights smoothes (3 iterationer) så bevægelser ser naturlige ud.
- Bone roll pinned til 0 for forudsigeligt IK (Humanoid).

**Test riggen (Humanoid):**
1. Vælg armature i Outliner.
2. Tryk `Ctrl+Tab` → vælg Pose Mode.
3. Vælg fx `hand_ik.L` og tryk `G` for at flytte den. Armen bør følge.

**Re-run:** Hvis du klikker Generate Rig igen på samme mesh, den gamle
armature ryddes automatisk væk — ingen orphan rigs efterlades.

> ⚠️ Hvis du gjorde Retopo først (auto eller manuel), tags overføres
> automatisk til retopo-mesh via evaluated mesh (multires applied), så
> Generate Rig fungerer på low-poly med korrekte weights selv efter
> aggressive sculpts.

---

## 10. Trin 7 — Bake Maps (normal map + AO)

Klik **Bake Maps** i Workflow Pipeline. Det baker:

- **Normal map** — den høj-poly's detaljer indfanget som RGB-data der
  kan vise fake-detail på low-poly i Unity.
- **AO** (ambient occlusion) — skygger i sprækker, til texturing.
- **Position** (valgfri) — verdens-koordinater per pixel, til mask-arbejde.

**Forudsætning:** mesh skal hedde `<navn>_retopo` ELLER der skal være en
high-poly source mesh selected sammen med low-poly.

PNG'er gemmes i `<din-blend-fil>/textures/`. Standard er 2048×2048 (2K) —
juster i Preferences hvis du vil have 1K, 4K eller 8K.

> ⚠️ Bake kan tage flere minutter på en humanoid med høj multires-niveau.
> Blender's UI fryser under bake — vent til "Baked NORMAL, AO" vises i
> bunden.

---

## 11. Trin 8 — Export til Unity

Klik **Export FBX (Unity)**. Vælg destination.

Settings du skal forstå:

- **Axis Mode:**
  - **Baked** (default): Bare drop FBX'en i Unity, det virker.
  - **Declared**: Du SKAL aktivere "Bake Axis Conversion" på Unity-importeren
    bagefter. Bedre hvis du senere vil eksportere animationer.
- **Triangulate**: Tilføjer triangulering så Unity ikke gør det forskelligt
  fra hvad bake'n forventede. **Lad det være tændt.**
- **Apply Modifiers**: Baker modifiers ind. Armature undtages — den
  eksporteres som rig. **Lad det være tændt.**

I Unity:
1. Drop `.fbx` ind i `Assets/`.
2. Drop også PNG'erne fra `textures/` ind.
3. Vælg FBX'en, sæt Inspector → Rig → "Humanoid" hvis du vil bruge Mecanim.
4. Lav et material, sæt din baked normal map som Normal Map (sørg for
   "Marked as Normal Map" er tjekket).

---

## Pie-menu cheat sheet

### Q (primary)
```
        Smooth
          ↑
Grab ←  •  → Crease Sharp
          ↓
       Mask + 4 ydre slots
```

### Shift+Q (secondary)
```
       Pinch/Magnify
          ↑
Snake ← • → Scrape/Fill
Hook       
          ↓
       Draw Sharp + 4 ydre slots
```

Slots kan customizes i **Edit → Preferences → Add-ons → PipeSculpt → Brush
Slots**. Skriv brush-asset navnet (fx "Clay Strips") i et slot for at
binde det.

---

## Troubleshooting

**"Voxel remesh failed"**
Mesh er for stor / for lille relativt til voxel-size. Sørg for du har
klikket **Apply Scale** (`Ctrl+A → Scale`) før Start Sculpt.

**Brushes virker ikke når jeg trykker Q**
Du skal være i **Sculpt Mode**, ikke Object Mode eller Edit Mode. Klik
Start Sculpt eller `Ctrl+Tab` → Sculpt.

**Quadriflow gør hele mesh til en grim klump**
Det sker på sharp-edge mekaniske former. Brug **Decimate** i stedet, eller
manuel retopo.

**Bake giver flat blå normal map**
Du har valgt low-poly som BÅDE source og target. Sørg for high-poly er
selected sammen med low-poly, eller at low-poly hedder `<base>_retopo`
hvor `<base>` er en eksisterende high-poly i scenen.

**Generate Rig: "Bone metadata missing"**
Du startede ikke med en Humanoid-starter. Generate Rig kræver per-vertex
tags (GTR), som kun Humanoid har for nu.

**Eksport til Unity: karakter er roteret 90° forkert**
Du har brugt Declared axis mode uden at slå "Bake Axis Conversion" til
i Unity-importeren. Enten slå den til, eller eksporter igen med Baked.

**Unity: normal map ser pudset/fejlagtigt ud**
Sørg for at PNG'en er sat til "Normal map" type i Unity-importeren. Også
verificér at Unity Color Space er Linear (Project Settings → Player).

---

## Kendte begrænsninger (v0.9.1)

Disse er ikke bugs men ting der ikke understøttes endnu:

- **Tag-overførsel gennem retopo** bruger nu evaluated mesh (multires
  applied), så aggressive sculpts overlever korrekt. Hvis weights stadig
  ser mærkelige ud, klik Generate Rig FØR du retopo'er som backup.
- **Generate Rig på samme mesh igen** rydder nu den gamle armature
  automatisk op — du behøver ikke længere slette den manuelt.
- **Bust og Head har nu bone-hierarchier:** Bust = 7 bones (root, spine,
  neck, head, jaw, ear.L/R, ingen IK), Head = 2 bones (root + head pivot).
- **Kun humanoid/bust/head-rigs** — ingen support for fugle, dyr, robotter.
- **DECLARED axis-mode i FBX export** kan nu verifiees: klik
  **Verify Axis Mode** under Export. Det skriver to test-FBX'er og en
  README med Unity-procedure til en mappe.
- **IK pole-angle** er empirisk derived for default Humanoid rest pose.
  Hvis du redigerer bones manuelt før Generate Rig, kan IK twiste.

---

## Hvor er filerne?

- **Addon-kode:** `C:\Users\Piper\BlenderAddons\pipe_sculpt\` (Windows)
- **Bake-output:** `<din-blend-fil>/textures/`
- **FBX-output:** dér du vælger i export-dialog
- **Build-script:** `pack.py` (kør for at lave install-zip)
- **Brush-presets:** `Edit → Preferences → Add-ons → PipeSculpt`

---

Held og lykke. Hvis noget er uklart, kig i `README.md` for technical reference,
eller åbn en issue på din git repo.

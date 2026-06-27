# GTR Rig Review — roll=0 og single-spine + alt andet fundet i `rigging.py`

**Til:** koderen på PipeSculpt
**Fra:** rig/anim-gennemgang af `rigging.py` (hele filen læst)
**Formål:** før vi bygger animation-modulet skal vi vide hvor GTR-skelettet afviger fra et "standard" game-skelet, hvad der bider i Unity 6-export, og hvad der er en reel bug vs. en kosmetisk afvigelse.
**Scope:** kun `rigging.py`. Ingen ændringer lavet — dette er en review + en plan + et test-script du selv kan køre.

---

## 0. TL;DR

GTR's **skelet-topologi og bone-navne er faktisk tæt på Unity Humanoid** (pelvis/spine/neck/head/clavicle/upper_arm/forearm/hand/upper_leg/lower_leg/foot/toes + `.L`/`.R`). Det novelle i GTR er **skinning-metoden** (vertex-tag-sporet vægtning), ikke skelettet. Så retarget er *lettere* end først antaget. Men der er to ting der skal fikses før animation-modulet, og en håndfuld mindre afvigelser:

| # | Fund | Alvor | Rammer | Status |
|---|------|-------|--------|--------|
| A | `roll = 0.0` på alle bones | **Medium** | Generic-export + cross-rig curve-copy + IK-pole-robusthed. **IKKE** Unity Humanoid. | Verificeret analytisk; test-script vedlagt |
| B | Kun **én** spine-bone | **Høj** | Deformations-kvalitet + retarget fra 3-spine mocap | Verificeret mod Unity Humanoid-krav |
| C | Deform + control + IK i samme armatur | Medium | FBX-export forurener Unity-avataren med ikke-deform-bones | Verificeret i kode |
| D | Ingen twist-bones | Lav | Deformation af underarm/lår ved vrid | Verificeret i kode |
| E | Hardkodet rest-pose + proportioner | Medium | Skelet matcher ikke den faktiske sculpt | Verificeret i kode |
| F | `_calc_pole_angle` kun gyldig for hardkodet rest-pose | Medium | IK twister hvis bones redigeres før Generate Rig | **Allerede flagget `UNVERIFIED` i kildens docstring** |
| G | Quadruped/Bird/Mech kan ikke være Unity Humanoid | Info | Skal eksporteres som Generic | By design |

---

## 1. Hvordan GTR virker (så vi taler om det samme)

GTR = "Genesis-Tracked Rigging". Det er **ikke en skelet-topologi — det er en skinning-metode.** Flow (`rigging.py`):

1. **Tag:** hver primitiv-vertex får et bone-index i en INT-attribut `pipe_sculpt_bone` *før* sculpting (`tag_primitive`, linje 381).
2. **Spor:** tagget overlever voxel-remesh og retopo via KDTree nearest-neighbour-transfer (`smart_voxel_remesh` linje 484, `transfer_bone_tags_from_high` linje 521). Brug af evalueret high-poly mesh (multires) er korrekt håndteret.
3. **Skind:** `Generate Rig` (linje 580) bygger armatur fra JSON-metadata, giver hver vertex weight **1.0 til præcis én bone** (`'REPLACE'`, linje 687), og kører derefter 3 udjævnings-passes (`vertex_group_smooth`, factor 0.5, repeat 3, linje 705).

Det er det centrale: **vægte kommer fra sporet primitiv-identitet, ikke fra heat-map/voxel-diffuse auto-skinning.** Det er dér nyhedsværdien ligger — og det er fint. Skelettet, derimod, er konventionelt, og det er konventionerne vi reviewer her.

---

## 2. Fund A — `roll = 0.0` på alle bones

### Hvad koden gør
`Generate Rig` sætter `eb.roll = 0.0` på *hver* edit-bone (linje 661) med kommentaren *"Pin roll=0 so the X-axis is predictable and IK pole math is too."*

### Hvad det betyder
En bones lokale **Y-akse** = retningen head→tail (altid). **Roll** bestemmer hvordan lokal X og Z roteres om Y. `roll=0` betyder at Blender bruger sin default-konvention (lokal Z lægges så tæt på verdens +Z som muligt for ikke-lodrette bones).

For en GTR-arm der peger langs verdens +X (f.eks. `forearm.L`: head `(0.70,0,0.40)` → tail `(1.05,0,0.40)`) giver `roll=0`: lokal Y≈`(+1,0,0)`, lokal Z≈`(0,0,+1)`, lokal X≈`(0,∓1,0)`.

### Hvad det IKKE bryder — vigtig korrektion
**Unity Humanoid-retarget bruger ikke bone-roll.** Unity bygger en Avatar der mapper hver bone ind i et normaliseret "muscle space" defineret af T-posen + hierarkiet, og re-udtrykker bevægelsen på target. Source-FBX'ens lokale akser/roll abstraheres væk. → **`roll=0` ødelægger IKKE Humanoid-retarget.** (Dette var en overdrivelse i min første mundtlige vurdering — rettet her.)

### Hvad det FAKTISK rammer
1. **Generic-retarget / direkte curve-copy.** Enhver retarget der kopierer rotation i lokal bone-space (Unity Generic, Blender Copy-Rotation mellem rigs, BVH-genbrug). GTR's lokale akser ≠ et standard-rigs → kurver overføres forkert. **Gælder dermed Quadruped/Bird/Mech, som *skal* være Generic.**
2. **IK-pole-robusthed i Blender** (se Fund F). `_calc_pole_angle` (linje 204) bruger `base_bone.matrix_local.col[0]` = lokal X = roll-afhængig. roll=0 er fint *for den hardkodede rest-pose*, men ikke generelt.
3. **FK-animations-følelse.** Animator der roterer i lokal space får akser der ikke flugter med den anatomiske bøje-plan. For vandrette arme med roll=0 (lokal Z=op) er "rotér om lokal X" = albue-bøj — det virker, men er ikke den game-rig-konvention de fleste forventer.

### Finger-detalje (mindre slem end frygtet)
Fingre peger langs ±X (`FINGER_KNUCKLE_X`, linje 44) og curler om verdens Y. Med roll=0 på en X-bone bliver verdens Y ≈ lokal X → finger-curl er en *ren enkelt-akse-rotation*. Så fingrene er faktisk OK for curl.

### Verifikations-status
**Analytisk verificeret ud fra koden. Ikke empirisk kørt** — Blender 5.1 er installeret (config findes i `%APPDATA%\Blender Foundation\Blender\5.1`) men `blender.exe` lå ikke på memory-stien `C:\Program Files\Blender Foundation\Blender 5.1\` længere, og en fuld C:-søgning blev afbrudt. **Kør `tests/verify_rig_axes.py` (vedlagt) når du har binæren** — den printer faktiske roll- og akse-værdier pr. bone, så vi får tal i stedet for ræsonnement.

### Anbefaling
- Behold roll=0 **eller** sæt eksplicitte rolls — men *kun* hvis vi får brug for ren Generic-curve-copy. For Humanoid-pathen er det irrelevant.
- Vigtigere: gør `_calc_pole_angle` robust (Fund F), for det er dér roll=0 reelt kan give en bug.

---

## 3. Fund B — kun ÉN spine-bone (HØJ)

### Hvad koden gør
Humanoid-kæden er `pelvis → spine → neck → head` (linje 139-142). Der er **én** spine-bone mellem pelvis og nakke. Kravben (clavicle) parentes direkte til `spine` (linje 145, 151).

### Unity Humanoid-mapping
Unity Humanoid kræver minimum Hips + Spine; Chest og UpperChest er optional. GTR mapper:
`pelvis→Hips`, `spine→Spine`, `neck→Neck`, `head→Head`. **Det opfylder minimumskravet — det importerer fint som Humanoid.** Problemet er ikke import, det er kvalitet:

1. **Retarget fra rigere kilde komprimerer.** Et Mixamo/mocap-clip animerer typisk Spine/Spine1/Spine2 (3 segmenter). Retarget ned på ét spine-led kollapser al rygbøjning til ét punkt → torsoen knækker stift om én pivot. Tydeligst ved aim-lean, reload-twist, crouch, death-fold — præcis IronCore-combatant-bevægelserne.
2. **Deformation.** Én bone for hele torsoen = mesh fra pelvis til nakke deformerer som to stive sektioner med ét bøjepunkt. Spine-twist (skuldre roteret ift. hofter) kan ikke fordeles.
3. **Ingen chest/skulder-uafhængighed.** Uden chest-bone kan skulder-bevægelse og torso ikke separeres; clavicles hænger på samme bone som hele ryggen.
4. **Skæv fidelitet.** GTR har **30 finger-bones** (3 falanger × 5 × 2) men **1 spine**. For game-karakterer betyder spine-artikulation mere end 3-leds-fingre i de fleste animationer. Prioriteringen er omvendt af hvad gameplay kræver.

### Anbefaling (lille kode-ændring)
Indsæt en **chest**-bone: `pelvis → spine → chest → neck → head`, og reparent clavicles + neck til `chest`. Det mapper til Unity `Hips→Spine→Chest→Neck→Head` og fjerner det meste af komprimerings-problemet. Konkret i `HUMANOID_BONES`:

```python
("spine",   "pelvis", (0.00, 0.00, -0.082), (0.00, 0.00,  0.250), 'D'),  # split
("chest",   "spine",  (0.00, 0.00,  0.250), (0.00, 0.00,  0.585), 'D'),  # NY
("neck",    "chest",  (0.00, 0.00,  0.585), (0.00, 0.00,  0.625), 'D'),  # reparent
("clavicle.L", "chest", ...),   # reparent L+R fra "spine" til "chest"
```
Husk: `chest` skal tilføjes til `DEFORM_BONE_NAMES` (linje 90) — **i enden, ikke i midten**, ellers skifter alle efterfølgende bone-indekser og gamle tags peger på forkerte bones (kommentaren på linje 88-89 advarer netop om dette). Bone-index-rækkefølge og navne-rækkefølge i hierarkiet behøver ikke matche, så det er sikkert at appende.

Overvej samme split for `MECH_BONES` (linje 342) hvis mechs skal lave torso-bevægelse.

---

## 4. Fund C — deform + control + IK i samme armatur

`HUMANOID_BONES` blander `kind='D'` (deform) og `kind='C'` (root, `hand_ik`, `foot_ik`, `elbow_pole`, `knee_pole`). De `'C'`-bones får `use_deform=False` (linje 656) → ingen vægte, korrekt. **Men de eksporteres stadig til FBX** medmindre de filtreres fra. Unity-avataren ser så ekstra ikke-deform-bones; Humanoid-mapping bliver støjende, og Generic-skelettet bliver større end nødvendigt.

**Anbefaling:** animation/export-modulet skal have et **deform-only export-filter** der dropper alle `kind='C'` bones (og evt. flytter dem til en bone-collection der ikke eksporteres). `kind`-flaget ligger allerede i metadataen, så filteret er trivielt.

---

## 5. Fund D — ingen twist-bones

Ingen forearm-/upper-arm-/thigh-twist. ARP/Rigify tilføjer dem for ren deformation ved vrid; Unity Humanoid har dem som optional roll-bones. Lav prioritet — ikke en blocker, men noteret for deformations-kvalitet hvis håndvrid/skuldervrid ser candy-wrapper-agtigt ud.

---

## 6. Fund E — hardkodet rest-pose og proportioner

Alle bone-koordinater er faste tal (arm i z=0.40, faste segment-længder). Skelettet er **ikke parametrisk til den faktiske sculpt.** Sculpter brugeren andre proportioner (kortere ben, bredere torso), matcher bones ikke meshet → både vægte (nearest-neighbour på tags) og enhver retarget lider. A_POSE/IDLE-presets (linje 441) roterer kun arme, ikke proportioner.

**Anbefaling:** uden for scope for animation-modulet, men værd at notere: en "fit bones to mesh bounds"-pre-pass ville hjælpe alt downstream. Ikke kritisk nu.

---

## 7. Fund F — `_calc_pole_angle` er rest-pose-specifik

Kildens egen docstring (linje 7-12) flagger det allerede som `UNVERIFIED`: pole-matematikken er *"derived empirically against rest-pose bbox preservation — but only for the hardcoded HUMANOID rest pose. If the user manually edits bones before Generate Rig, the pole math can twist."*

Dette er det sted hvor roll=0 (Fund A) reelt kan blive til en synlig bug. Det er allerede kendt — vi skal bare ikke bygge animation-IK ovenpå uden at adressere det.

**Anbefaling:** verificér pole-vinklen med en deformations-test (ikke en bbox-test) — bøj IK-target og tjek at kæden ikke ruller. Dækkes delvist af det vedlagte test-script (akse-rapporten gør problemet synligt).

---

## 8. Fund G — Quadruped / Bird / Mech er ikke Humanoid

Unity Humanoid accepterer kun biped. `QUADRUPED_BONES`, `BIRD_BONES` (og delvist `MECH_BONES`) **skal** eksporteres som **Generic** avatar. For Generic gælder Fund A (roll) og Fund C (deform-filter) *fuldt ud*, fordi Generic-retarget bruger lokal bone-space direkte. Så for ikke-humanoid er roll-spørgsmålet ikke kosmetisk.

---

## 9. Konsekvens for animation-modulet (hvad vi bygger ovenpå)

1. **Deform-only export-filter** (Fund C) — drop `kind='C'` fra FBX. Lille, gør Humanoid- og Generic-export rene på én gang.
2. **Chest-bone** (Fund B) — én bone-table-edit, stor gevinst på torso-deformation og mocap-retarget.
3. **Pole-angle deformations-verifikation** (Fund F) før IK-authoring.
4. **roll=0 er OK for Humanoid-pathen**; håndtér det kun hvis vi laver Generic-curve-copy (quad/bird).

---

## 10. Sådan verificerer du selv (test-script vedlagt)

Empirisk verifikation kunne ikke køres i denne omgang (binæren ikke fundet på memory-stien). Kør i stedet det vedlagte script — det bygger humanoid-armaturet headless og printer faktiske roll/akse/spine-tal, så vi får data:

```
"<sti til blender.exe>" --background --python tests\verify_rig_axes.py
```

Find din binær først, f.eks.:
```powershell
Get-ChildItem C:\,D:\ -Filter blender.exe -Recurse -ErrorAction SilentlyContinue -File | Select FullName
```
(eller åbn Blender → den står i "About"-stien). Scriptet rapporterer:
- roll pr. bone (bekræft at de er 0)
- lokale X/Y/Z-akser pr. bend-bone (forearm, lower_leg, finger)
- om bend-aksen flugter med en ren lokal akse
- spine-kædens længde (bekræfter Fund B)
- liste over `kind='C'` bones der vil forurene FBX (Fund C)

**Status på dette dokument:** Fund A og F er *analytisk* verificeret + flagget i koden; B, C, D, E, G er verificeret direkte i kildekoden. Ingen påstand her hviler på antagelse om Blender-runtime-adfærd uden at være markeret som sådan.

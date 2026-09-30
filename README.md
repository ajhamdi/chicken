# Chicken Farm 3D ([play here](https://abdullahamdi.com/chicken/))

Welcome to **Chicken Farm**, a browser game where your quick reflexes and timing are put to the test! Use your hammer (and, later, a machine gun, a rocket launcher and a laser cannon) to stop chickens, crabs, hornets and dragons before they overrun the farm.

The game is now fully **3D**: it is rendered with [three.js](https://threejs.org/) and every model (creatures, weapons, power-ups and the whole farm) is generated procedurally in **Blender** by [`blender/build_assets.py`](blender/build_assets.py). The original 2D canvas game is still available as [`classic.html`](classic.html).

## Table of Contents

- [Features](#features)
- [Getting Started](#getting-started)
- [How to Play](#how-to-play)
- [Controls](#controls)
- [Scoring and Multipliers](#scoring-and-multipliers)
- [Game Over Conditions](#game-over-conditions)
- [3D Asset Pipeline (Blender)](#3d-asset-pipeline-blender)
- [Project Layout](#project-layout)
- [Credits](#credits)
- [License](#license)

## Features

- **3D farm arena**: a low poly farm with a barn, silo, windmill, fences, trees, hay bales, hills and drifting clouds, lit by a sun with real time shadows.
- **Animated 3D creatures**: waddling chickens, sideways scuttling crabs, buzzing hornets and flapping dragons, each animated from named Blender parts (wings, legs, claws, tail, head).
- **Four weapons**: the hammer swings down onto the target; the machine gun, rocket launcher and laser cannon are turrets that track your aim and fire tracers, arcing rockets and beams.
- **Progressive difficulty**: new waves every 25 seconds, faster spawns and tougher enemies (crabs at wave 4, hornets at wave 6, dragons at wave 8).
- **Combos and multipliers**, golden chickens (with a crown) worth 10x, and 3D power-ups: Freeze (snowfall and icy creatures), Bomb and Double Points.
- **Effects**: feather and debris particles, explosions with shockwaves, muzzle flashes, camera shake, floating score text.
- **Audio**: background music that escalates with the waves plus synthesized weapon sounds.
- **Responsive**: works with mouse or touch; on portrait phones the camera turns to look along the field so the arena fills the screen.

## Getting Started

### Prerequisites

- A modern browser with WebGL (Chrome, Firefox, Safari, Edge).
- An internet connection the first time (three.js is loaded from the jsDelivr CDN).

### Run it

1. Clone the repository:

   ```bash
   git clone https://github.com/ajhamdi/chicken.git
   cd chicken
   ```

2. Open `index.html` in your browser. That's it: the 3D models are bundled in `assets/models.js`, so the game also works straight from disk. You can also serve the folder with any static server, for example `python3 -m http.server`, and open `http://localhost:8000`.

If WebGL is unavailable, the page offers a link to the classic 2D version.

## How to Play

### Objective

Hit as many creatures as possible before they overrun the farm. They spawn inside the fenced field and wander around; flying enemies (hornets and dragons) hover above it.

## Controls

### Desktop
- **Mouse movement**: aim (the hammer hovers over the target; turrets rotate toward it).
- **Left click**: swing the hammer, fire a rocket, or hold to auto-fire the machine gun / laser.
- **1 to 4**: switch weapons (hammer, machine gun, rocket launcher, laser cannon) once they are unlocked.

### Mobile / Touch
- **Tap**: aim and use the current weapon; **touch and drag** to keep firing with the machine gun or laser.
- **Weapon bar**: tap a slot to switch weapons.

Click or tap a floating power-up to collect it with any weapon.

## Scoring and Multipliers

- Each creature hit increases your score by the current multiplier.
- The multiplier grows by 1 for every hit within 2 seconds of the previous one and resets on a miss or after 2 seconds.
- Golden chickens are worth 10x; Double Points doubles everything for 8 seconds.
- Rockets must kill 2 or more creatures in one blast to keep the combo going.
- Hornets take 2 hits, dragons take 4 (the laser kills a dragon in one shot).

## Game Over Conditions

- The game ends when 20 live creatures are on the field.
- Your final score, wave and total hits are shown, together with a new high score badge when you beat your best (stored in the browser).
- Click **Play Again** to restart.

## 3D Asset Pipeline (Blender)

All models in `assets/models/*.glb` are authored as code in [`blender/build_assets.py`](blender/build_assets.py), using Blender's Python API (`bpy`, `bmesh`). The script:

1. builds each model from primitives with flat shaded, stylized PBR materials,
2. keeps the parts the game animates as separate objects with pivots at their joints (`WingL`, `WingR`, `LegL`, `LegR`, `ClawL`, `ClawR`, `Head`, `Tail`, turret `Gun`, `Muzzle` empties, the windmill rotor),
3. exports every model as a binary glTF (`.glb`) and packs them into `assets/models.js` (base64) for the game.

Regenerate the assets after editing the script with any of:

```bash
# with Blender installed
blender -b -P blender/build_assets.py

# or with Blender as a Python module
pip install bpy
python3 blender/build_assets.py

# rebuild only some models (the bundle is always rewritten)
python3 blender/build_assets.py -- chicken dragon
```

The script can also be run inside a live Blender session, for example through a Blender MCP server's "execute code" tool; set the `CHICKEN_ASSET_DIR` environment variable (or `OUT_DIR` in the script) to the repository's `assets/models` folder first.

| Model | Used for |
| --- | --- |
| `chicken`, `crab`, `hornet`, `dragon` | enemies (waves 1, 4, 6, 8) |
| `crown` | marker above golden chickens |
| `hammer`, `machinegun`, `rocket_launcher`, `rocket`, `laser` | weapons and projectiles |
| `powerup_freeze`, `powerup_bomb`, `powerup_double` | power-ups |
| `farm` | barn, silo, windmill, fence, trees, props, hills, clouds |

## Project Layout

```
index.html               3D game (three.js, loaded via an import map)
classic.html             original 2D canvas game
assets/models/*.glb      Blender generated models
assets/models.js         the same models bundled as base64 (generated)
blender/build_assets.py  procedural Blender asset pipeline
*.mp3, *.wav             music and sound effects
*.png, *.svg, *.jpg      2D art (classic game, crosshair cursors)
```

## Credits

- **Game Development**: Abduallah Hamdi
- **Concept and Design**: Abduallah Hamdi

## License

This project is licensed under the MIT License.

---

Enjoy playing Chicken Farm! If you have any suggestions or encounter any issues, please feel free to open an issue or submit a pull request.

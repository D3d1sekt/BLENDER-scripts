# BLENDER-scripts

## `sao_labyrinth_traps_loot.py`

Генератор модульного готичного лабіринту (1-й поверх вежі) з пастками та скарбами
для Blender 5.3 (сумісний з 4.2+), оптимізований під Roblox Studio.

```bash
# у фоні, з експортом у вказаний файл
blender -b -P sao_labyrinth_traps_loot.py -- --output ./sao_maze_traps.fbx
# лише побудувати сцену без експорту
blender -b -P sao_labyrinth_traps_loot.py -- --no-export
```

Або: Blender → Scripting → Open → Run Script. Усі параметри (розміри, пастки,
матеріали, план лабіринту, шлях експорту) — у блоці констант на початку файлу.

* **Maze_Layout**: 3×3 секції по 8 м (прохід 6 м, стіни 7 м). Для кожної секції
  окремо створюються підлога, стіни та хрестове стрілчасте склепіння; також є
  гвинтові кам'яні сходи вгору.
* **Traps**: `Trap_Floor_Spikes` + `Spikes_Moving` (16 шипів), `Trap_Pendulum_Axe`
  + `Axe_Swinging` (origin на осі підвісу), `Trap_Pressure_Plate` (2×2 м, +0.1 м).
* **Loot_And_Props**: 3 скрині (`Chest_Base_NN` / `Chest_Lid_NN`, origin кришки на
  задніх завісах) на постаментах, золото, факели в залізних тримачах, колони.
* Кожен об'єкт має ≤ 5000 трикутників (скрипт це перевіряє); матеріали — лише Principled BSDF.

## `sao_long_corridors.py`

Система довгих готичних коридорів (48/40/32 м) з T-розвилками та поворотами.
Кожен коридор розбитий на підлогу, стіни та склепіння, щоб у Roblox була коректна колізія.
Результат експортується у `sao_long_corridors.fbx`.

## `sao_boss_room_1st_floor.py`

Зала Кімнати Боса 36 × 56 × 18 м.

* **Boss_Arena_Structure**:
  * мармурова підлога з зеленою доріжкою 8 × 44 м і кельтським орнаментом;
  * смуги, що світяться біля стін;
  * вітражні стіни та стеля з балками;
  * подіум 16 × 8 × 2.2 м зі сходами та троном.
* **Arena_Pillars**: 14 колон висотою 18 м.
* **Boss_Entrance_Gate**: арка 8 × 11 м, стулки `Gate_Door_Left` / `Gate_Door_Right` (Origin на осі петель) з неоновою окантовкою, бар'єр `Gate_Barrier_Field`.
* **Gameplay_Markers**: `Boss_Spawn_Point`, `Minion_Spawn_1..3`, `Arena_Trigger_Zone` (24 × 30 м).

Багатоколірні елементи (вітражі, орнамент) розбиті на окремі об'єкти за кольором, бо MeshPart у Roblox має один матеріал.
Результат експортується у `sao_boss_room_1st_floor.fbx`.

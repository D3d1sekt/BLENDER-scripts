# BLENDER-scripts
## sao_boss_entrance_gate.py

Процедурна сцена передбанника та двостулкової брами Кімнати Боса 1-го поверху Айнкраду
(Blender 5.x, лише `bpy` data-API + `bmesh`; 1 BU = 1 м).

| Колекція | Об'єкти |
|---|---|
| `Prep_Hall_Structure` | `Prep_Floor`, `Prep_Walls_And_Columns`, `Prep_Ceiling_Beams` |
| `Boss_Doors_Animatable` | `Boss_Door_Arch_Frame`, `Boss_Door_Left`, `Boss_Door_Right` |
| `Braziers_And_Markers` | `Brazier_Left`/`_Flame`, `Brazier_Right`/`_Flame`, `Threshold_Blue_Markers` |
| `Preview_Camera_And_Lights` | камера та світло лише для превʼю (не експортуються) |

Запуск:

```bash
blender --background --python sao_boss_entrance_gate.py -- --export-path ./sao_boss_gate.fbx
```

або відкрийте файл у Scripting → Run Script (експорт вмикається `EXPORT_FBX = True`).

* Origin стулок: `Boss_Door_Left` → (-3.6, 0, 0), `Boss_Door_Right` → (+3.6, 0, 0), обертання (0, 0, 0).
* FBX: Forward `-Z`, Up `Y`, Apply Transform → вісь петель = вісь **Y** у Roblox Studio.
  Стулки відчиняються всередину Кімнати Боса (ліва +100°, права −100° навколо Y).
* Скрипт друкує бюджет трикутників (≤ 5 000 на об'єкт) і перевіряє петлі перед експортом.

Приклад відкриття в Roblox (Luau, двері — `Model`/`MeshPart` з pivot на петлі):

```lua
local TweenService = game:GetService("TweenService")
local function openDoor(door: BasePart, angleDeg: number)
	local hinge = door:GetPivot()
	local value = Instance.new("CFrameValue")
	value.Value = hinge
	value.Changed:Connect(function(cf) door:PivotTo(cf) end)
	TweenService:Create(value, TweenInfo.new(3, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut),
		{ Value = hinge * CFrame.Angles(0, math.rad(angleDeg), 0) }):Play()
end
openDoor(workspace.BossGate.Boss_Door_Left, 100)
openDoor(workspace.BossGate.Boss_Door_Right, -100)
workspace.BossGate.Threshold_Blue_Markers.Transparency = 1
```

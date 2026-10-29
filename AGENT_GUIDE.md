# csd_to_prefab — Cocos Studio `.csd` 轉 Cocos Creator 3.8 prefab

把 Inanna 的 Cocos Studio 版面轉成 Aerith 的 prefab，含圖檔／點陣字複製、`.meta`
產生、巢狀 prefab、動畫，以及一組會擋下錯誤的驗證。

相鄰工具：`tools/csd_to_anim/` 只轉動畫時間軸。本工具的動畫是整體轉換的一部分，
兩者不互相依賴。

## 動手前先讀「已知地雷」那一節

這份程式裡有幾個看起來很隨意的常數，每一個都是追過一次畫面 bug 才定下來的。
改動之前先確認你知道它為什麼是那個值。

---

## 用法

```bash
cd tools/csd_to_prefab

# 1) 產生設定檔草稿（掃描該資料夾所有 .csd）
python csd_to_prefab.py init <module> [--csd-dir <folder>] [--csd-root <cocosstudio>]

# 2) 檢查／調整 configs/<module>.json（見下方「設定檔」）

# 3) 轉換
python csd_to_prefab.py convert configs/<module>.json

# 4) 驗證（一定要跑）
python csd_to_prefab.py verify configs/<module>.json

# 5) 之後若有人在 Cocos Creator 裡開過這些 prefab，用這個檢查有沒有被改壞
python csd_to_prefab.py drift configs/<module>.json          # 只回報
python csd_to_prefab.py drift configs/<module>.json --fix    # 依 .csd 重建
```

`verify` 通過會回傳 0，有問題回傳 1 並列出 `FAIL`。**沒跑過 verify 不要回報完成。**

需求：Python 3 + Pillow。`verify` 的幾何比對需要 `csdview` 在 PATH 上；沒有時會跳過
幾何檢查（其他檢查照跑），並在輸出中註明。

## 設定檔

```jsonc
{
  "csdRoot": ".../CocoStudioProject/Inanna/cocosstudio",
  "csdDir": "voucherCenter",              // csdRoot 底下的資料夾
  "module": "voucherCenter",
  "imagesOut": "assets/art-assets/modules/voucherCenter/images/main",
  "fontsOut":  "assets/art-assets/modules/voucherCenter/fnt",
  "copyAllModuleImages": true,            // 連沒被引用的模組圖也複製
  "reuse": {                              // 已存在的專案資產：只引用，不複製
    "vip/img/VIP_card_big/VIP_0.png": "assets/art-assets/modules/vip/images/VIP_0.png"
  },
  "externalPrefabs": {                    // 這批之外的 ProjectNode 目標
    "purchase/Addvalue/Csd/FX_star.csd": "assets/.../FX_star.prefab"
  },
  "placeholders": ["Default/ImageFile.png"],   // Cocos Studio 內建佔位圖，沒有實際資源
  "prefabs": [
    { "csd": "InfoPage_V.csd", "name": "InfoPage_V",
      "out": "assets/art-assets/modules/voucherCenter/prefabs/InfoPage_V.prefab",
      "root": "container" },
    { "csd": "MainView_H.csd", "name": "VoucherCenterView_H",
      "out": "assets/main-assets/voucherCenter/VoucherCenterView_H.prefab",
      "root": "view" }
  ]
}
```

- `prefabs` **依序處理**：被 ProjectNode 引用的子 prefab 必須排在引用它的前面
  （`init` 已把有畫布的 view 排到最後）。
- `root: "view"` → root 取畫布尺寸、錨點 `(0.5, 0.5)`、加上撐滿的 `cc.Widget`，
  與專案既有的 `MainView.prefab` / `AntitheftView.prefab` 一致。
- `root: "container"` → root 尺寸 0、錨點 `(0.5, 0.5)`，子節點保留 `.csd` 原座標。

放置慣例（沿用專案現況）：圖 → `art-assets/modules/<m>/images/`，
點陣字 → `art-assets/modules/<m>/fnt/`，
被 navigation／popup 開啟的 view → `main-assets/<m>/`，
內部重用的 cell／page → `art-assets/modules/<m>/prefabs/`。

## 路徑要可攜（換一台電腦也能用）

**這個資料夾裡不該出現任何機器特定的絕對路徑。** Cocos Studio 專案的位置依序這樣解析
（`csdprefab/locate.py`）：

1. 指令列 `--csd-root`
2. 設定檔的 `csdRoot`（存在才採用；別台機器的舊值會自動略過）
3. 環境變數 `INANNA_CSD_ROOT`
4. 從 repo 與呼叫目錄往上找 `*/TMD_CocosStudio_Inanna/CocoStudioProject/Inanna/cocosstudio`

所以 **committed 的設定檔不要寫 `csdRoot`**，`init` 產生的草稿也刻意不寫。四條路都找不到時
會明確告訴你可以怎麼指定，不會丟出難懂的錯誤。

換機器只要 checkout 兩個 repo，通常第 4 條就會找到；放在特殊位置就設 `INANNA_CSD_ROOT`。

> `CLAUDE.md` 裡那段 csdview 的絕對路徑不歸這裡管 —— 它在
> `<!-- csdview:begin -->` 區塊內，由 csdview 的 `設定AI助手.bat` 產生，換機器重跑一次即可。

## uuid 是決定性的

`ids.py` 用 `uuid5(固定 namespace, db://路徑)` 產生 uuid，fileId 用路徑的 md5。
**同一個輸出路徑重跑會得到同一組 id**，所以重跑不會弄斷已 commit 的引用。
`NAMESPACE` 一改，等於重發所有 uuid。

---

## 已知地雷

### 1. `cc.Sprite._type`：SLICED 是 **1**，不是 2

`SIMPLE=0, SLICED=1, TILED=2, FILLED=3`。填 2 會變成平鋪，圓角按鈕整個破圖。
判準：專案內 8000 多個 sprite 只出現過 0 / 1 / 3，**出現 2 就是 bug**。

### 2. `BlendFunc Src="1"` 不能照抄

`.csd` 的 `Src=GL_ONE` 意思是「貼圖已 premultiply」——cocos2d-x 載入 PNG 時會做，
Creator 不會。照抄會讓全透明像素裡殘留的顏色以全強度疊加，在圖周圍畫出一塊實心矩形。
`components.map_blend()` 把 `GL_ONE` 換成 `GL_SRC_ALPHA`。

### 3. 座標轉換

- `.csd` 的 `Position` 相對**父節點左下角**；Creator 的 `_lpos` 相對**父節點錨點**。
  → `_lpos = csdPos - parentAnchor * parentSize`
- `<AnchorPoint>` 元素不存在代表 `(0, 0)`（Cocos Studio 省略為 0 的屬性），
  而且它排在 `<Children>` **之後**。
- 旋轉反向：`euler.z = -RotationSkewX`。

### 4. 9-slice 內縮值不能照抄

cocos2d-x 的 `Scale9Sprite` 在 `left+right` 超過目標寬度時會把 caps 等比縮小；
Creator 則把中央格夾成 0 並把 caps 撐大——**畫面是滿的，但圓角會嚴重變形**。
`images.resolve_border()` 只在放不下時改值，改成 `measure_insets()` 量出的
「內部完全恆定」內縮值（被拉伸的區域本來就是同色，所以無損）。

`verify` 的 `check_sliced_insets` 會擋下超界的情況。**`reuse` 進來的外部資產，
本工具不會改它的 `.meta`**；若那張圖的邊界是 0 或過大，要手動修（verify 會指出來）。

### 5. 全透明像素的殘留顏色

`.csd` 旁的鬆散 PNG 在 alpha=0 的地方留著美術的舊背景色。Cocos Studio 自己打包
atlas 時會清掉。不清的話濾波時會把那個顏色吃進邊緣。`images.clean_transparent()`
會清掉，且對所有 alpha>0 的像素完全不動（已和出貨 atlas 逐位元對照過）。

### 6. `trimType`

九宮格圖用 `none`（邊界值要留在 raw 座標系），點陣字 atlas 也要 `none`
（`.fnt` 的 glyph rect 是 raw 座標），其餘用 `auto`。

### 7. `.fnt` 一定要正規化，不能原樣複製

Cocos Studio 匯出的字形行是 `char id= 48   x=0`，**`=` 後面有空格**。

- 我的解析器要容許空白，否則每個字都解析成 id 0 互相覆蓋。
- 更要緊的是 **Cocos Creator 自己的 `.fnt` importer 也讀不懂這個空格**。它會在匯入時
  重新解析 `.fnt` 並**覆寫我寫的 `_fntConfig`**，把每個字形都放進 `'undefined'` 這個 key
  互相覆蓋，最後只剩 1 筆，主控台報：
  `Can't find letter definition in texture atlas ... for letter:0`

所以光把 `.meta` 寫對沒用，**檔案本身必須可讀**。`fonts.normalise()` 會把
`key = value` 收緊成 `key=value`（專案裡原本就能用的 `Num_Mission.fnt` 正是這個格式）。

### 8. 點陣字 Label 的字級不能留 0

`cc.Label` 在 `_fontSize: 0` 時什麼都不畫。`TextBMFont` 節點在 `.csd` 裡沒有 `FontSize`
屬性（縮放靠節點的 `Scale`），所以要用 **`.fnt` 自己的原生字級**
（`_fntConfig.fontSize`）填 `_fontSize` 與 `_lineHeight`，這也是專案既有 BMFont
label 的做法。

### 9. `.csd` 是 UTF-8

沒有 XML 宣告，ElementTree 讀得正確。中文變亂碼是把它印到 cp950 主控台造成的，
不是解析錯——要檢查字串請寫進檔案再讀，或直接比對。

### 10. csdview 的兩個座標陷阱

- `screenRect` 是 `[左, 上, 寬, 高]` 且 y 軸向下。`.csd` root 的原點是它的**左下角**，
  所以換算要用 root 的 `上 + 高`。用上緣會讓每個節點都偏掉 root 的高度
  ——只要 root 有尺寸（有畫布的 GameLayer 就有）就會中。
- csdview **不模擬 ScrollView 的捲動位置**，它把內容容器畫在原點；引擎是頂端對齊。
  所以 ScrollView 內容和 csdview 差 `innerHeight - viewHeight` 是正常的，
  `verify` 已扣掉。

### 11. 不要用 `ImageChops.difference().getbbox()` 判斷兩張圖相同

對 RGBA 圖，`getbbox()` 會用 alpha 通道判定「空白」，所以**透明區域的顏色差異會被
無視**，回報成「完全相同」。要逐像素比。

### 12. `_isTrimmedMode` 要 `false`

`true` 會讓 Creator 把 auto-trim 後的區域**拉滿整個節點框**、丟掉該影格的 trim offset。
對緊裁的圖看不出來（`rect == originalSize` 時兩者相同），但只要圖有透明邊界就會位移＋放大；
在「每格外框大小都不同」的貼圖序列上災難性明顯——例如一段掃過去的光耀，
`flowlight_01` 裁完只剩 **1x1**，會被放大填滿 78x78。

專案慣例也是 `false`（7229 個 vs 430 個）。`verify` 的 `check_trim_mode` 會擋。

同一個坑的小號版本：`CardLobby_Btn_Close` 是 60x60 的實際內容裝在 62x62 裡，
用 `true` 會被畫大約 3%。

### 13. 圖 `.meta` 的 `uv` / `nuv` 不是照直覺算的

裁切後的 spriteFrame，Creator 寫的是：

```
rawPosition = 正負 w/2、正負 h/2      # 不含 offset，offset 另外記在 offsetX/offsetY
uv          y 從「底部」量：rh - ty 與 rh - ty - h
nuv         由裁切矩形直接算，不是從 uv 換算
```

用直覺的「由上往下」寫法在**裁切對稱時會碰巧正確**，只有非對稱裁切才會露餡（Creator 匯入時
會默默改掉，所以畫面看不出來，但全新 checkout 尚未匯入前 meta 是錯的）。

判準：拿 `images.image_meta()` 去重算專案裡 Creator 自己產生的 meta，應該**逐欄位完全相同**
（目前 168/168 吻合）。

### 14. 文字尺寸差異是正常的

csdview 量的是實際繪製的字框，`.csd` 存的是美術拉的框。`verify` 把 Label 的偏差
單獨列出、不當失敗。只有整段文字位移才是真問題。

---

## verify 檢查了什麼

| 檢查 | 抓什麼 |
| --- | --- |
| 幾何（對 csdview，絕對座標不做位移擬合） | 錨點／座標換算錯誤、整體位移 |
| 9-slice 內縮 | 內縮超過節點尺寸 → caps 變形 |
| Label 字串（多重集合比對） | 文字漏字、編碼、對錯節點 |
| `_isTrimmedMode` vs 實際裁切 | 貼圖被拉滿節點框 → 位移＋放大 |
| 貼圖序列的原始尺寸一致性 | 動畫中途換成不同尺寸的圖 |
| Label 字級與點陣字字形 | 字級 0 不繪製；`.fnt` 被 Creator 重新解析後字形 key 壞掉 |
| 參照完整性 | `__id__` 越界、未填的物件槽 |
| 資產參照 | prefab 指向不存在的 uuid |

`drift` 是獨立的一道：它把每個 prefab 在記憶體裡重建一次，逐字比對磁碟上的檔案，
所以任何「不是這個工具寫的」改動都會現形，不需要 csdview。

`view` root 的置中重錨（`csdPos - 0.5 * canvas`）是刻意的，`verify` 已把它算進去，
不會誤報成偏移。

## 不要在 Cocos Creator 裡存這些 prefab

產生出來的 prefab 是**衍生檔**，唯一的真相來源是 `.csd`。在 Creator 的 prefab 編輯器裡
存檔會改動它們，而且有一個會靜靜弄壞版面的模式：

> view root 上的撐滿 `cc.Widget` 會把 root 拉成**編輯器當下畫布**的尺寸。用橫版畫布
> 開啟直版 prefab 再存檔，root 就從 `640x1400` 被烘成 `1400x640`，`mask` 跟著變，
> 整個遮罩範圍就錯了。實際發生過，`verify` 以「`mask` 差 760px」抓到。

同一次存檔還會把每個 Label 的 `contentSize` 改成 Creator 量到的字框（例如 82x20 →
100.1x25.2）。那部分無害，Creator 每次載入都會重算，`convert` 也會還原。

**這無法從轉換工具端阻止** —— 是編輯器存檔的行為。作法是：

1. 不要在編輯器裡存這些檔；要改版面就改 `.csd` 再重跑 `convert`。
2. 真的開過就跑 `drift`；`--fix` 會依 `.csd` 重建。
3. 若 `drift --fix` 之後仍然回報漂移，代表 Creator 還開著那個 prefab 並把舊狀態寫回去
   —— 在編輯器裡關掉該 prefab 再跑一次。

## 效能：兩個「先小範圍、找不到再擴大」的設計

`verify` 原本要 6.3 秒，其中 2.2 秒花在**為了收集 uuid 而解析全專案 8978 個 `.meta`**。
現在的做法是：

- `check_references` 與 `FontIndex` **先只掃這次轉換會寫入／引用的資料夾**，
  只有在還有 uuid 沒對上時，才退回掃整棵 assets 樹。
- csdview 的 spec 呼叫**並行**發出（6 次各約 0.5 秒的子行程，改成一次等待）。

**不要把它們「簡化」成無條件全掃** —— 那正是先前 2.2 秒的來源。擴大搜尋的行為有測過：
就算給錯資料夾清單，資產仍然找得到（見 `fault_inject.py` 與可攜性測試）。

現況（voucherCenter，6 個 `.csd`）：

| 指令 | 之前 | 現在 |
| --- | ---: | ---: |
| `convert` | 0.59 s | **0.28 s** |
| `verify` | 6.31 s | **1.90 s** |
| `drift` | 0.05 s | **0.04 s** |

`verify` 剩下的 1.9 秒有 **75% 是 csdview 子行程本身**（已並行，那是外部下限），
Python 端只剩約 0.3 秒。想再快只能對 csdview 的結果做快取——但那會帶來過期風險，
以這個工具的用量不划算，所以沒做。

解析／產生的吞吐量是線性的：**約 1430 節點/秒**（0.70 ms/節點）。全專案最大的模組
（111 個 `.csd`、2506 個節點）約 1.55 秒，不會有規模問題。

## 競態：與 Cocos Creator 搶同一批檔案

Creator 監看 assets 資料夾，我們一寫它就重新匯入 —— 兩邊會同時碰同一個檔。實測過的三件事：

**1. 寫檔已改成原子操作。** 原本是「截斷再寫」，讀取端會讀到半個檔：

| | 無競爭 | 監看者每 5ms 讀一次 |
| --- | ---: | ---: |
| 截斷再寫 | 0.7 ms/寫 | **33.3% 撕裂讀取** |
| 現在（暫存檔＋rename） | 2.2 ms/寫 | **0%** |

**2. Windows 的 rename 會被拒絕。** 別的行程開著目標檔時 `os.replace` 會丟
`PermissionError`。天真的原子改名在壓力測試下 **300 次寫入失敗 297 次** —— 比原本更糟。
所以是「短暫重試（5 次 × 40ms），仍不行就退回原地寫」，永遠不會讓轉換整個失敗；
退回時 `convert` 會印出 note，因為那一刻 Creator 有可能讀到半個檔。

**3. 執行緒那邊沒有競態。** 執行緒池裡只跑 `csdview_rects`：各自開子行程、各自回傳
區域字典，沒有共享可變狀態，而且 `csdview spec` **不寫任何檔案**（實測寫出 0 個檔）。
模組層級只有兩個唯讀常數。`FontIndex` 的延遲擴大搜尋會改自己的 dict，但就算多執行緒同時
命中也只是重複掃描一次，不會壞資料。

讀取端也加了短重試：Creator 重寫 `.meta` / `.prefab` 時讀到一半，會退讓後重試，而不是
丟出看不懂的 `JSONDecodeError`。

## 節點型別覆蓋率

把 Inanna 全部 **1527 個 `.csd`（31474 個節點）**掃過一遍的結果：

| 已轉換 | 節點數 | | 尚未轉換（產生成空節點） | 節點數 |
| --- | ---: | --- | --- | ---: |
| Sprite / ImageView | 15051 | | Particle | 197 |
| SingleNode / GameNode / GameLayer | 5348 | | CheckBox | 143 |
| Text | 3417 | | ListView | 61 |
| Panel | 2410 | | LoadingBar | 25 |
| ProjectNode | 1890 | | PageView | 9 |
| Button | 1827 | | TextField | 7 |
| TextBMFont | 993 | | Slider | 7 |
| ScrollView | 89 | | | |
| **合計 31025（98.6%）** | | | **合計 449（1.4%）** | |

未轉換的型別會保留 transform 但不繪製任何東西，而且 `convert` 會逐一印出：

```
note: <路徑>: ParticleObjectData is not converted - emitted as an empty node
```

**轉換完要看這些 note**，不然那個節點會從畫面上安靜消失。

## 沒有涵蓋的部分

- 不會產生 TS 的 View / ViewProperties，prefab 上不掛任何腳本元件。
- 動畫的緩動曲線壓成線性（與專案既有轉檔 `.anim` 一致，全部 `easingMethod: 0`）。
- `AnchorPoint` / `CColor` / `BlendFunc` 這類單一常數關鍵影格已烘進節點，不另建軌道。
  出現多關鍵影格時 `convert` 會印 note。

## 已轉換的模組

- `configs/voucherCenter.json` — 6 個 `.csd`，含巢狀 `InfoPage` 與 `FX_star`、
  `VoucherIcon` 的 75 影格動畫。可當作寫新設定檔的範本。

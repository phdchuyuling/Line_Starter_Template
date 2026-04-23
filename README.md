# LINE 貼圖裁切工具（CLI + Web）

本專案為一款 **自動化 LINE 貼圖裁切、規格校驗與打包工具**，同時提供 **CLI 命令列工具** 與 **FastAPI 網頁介面**，讓你只需上傳圖片，就能自動產出符合 LINE Creator Market 上架規範的圖片包。

---

## 核心功能

- 自動偵測非透明內容的邊界框（Bounding Box），裁切到內容區域
- 套用 10px 邊距（Padding），確保圖案置中、不貼邊
- 強制輸出偶數寬高（LINE 貼圖規格要求）
- 可選的自動去背（`rembg`，可獨立安裝，不影響核心功能）
- 輸出三種規格：
  - `main.png`：240×240（主圖）
  - `tab.png`：96×74（標籤圖）
  - `01.png`…`NN.png`：貼圖（最大 370×320，偶數尺寸）
- 規格驗證：檔案大小 < 1 MB、解析度 >= 72 dpi、RGBA 格式、ZIP 總量 < 60 MB
- 啟發式檢查：長寬比過極端、圖片過亮（可能在白色背景上難以辨識）
- 自動打包成 ZIP

---

## 專案結構

```
Line_Starter_Template/
├── line_sticker_tool/        # 核心函式庫
│   ├── __init__.py
│   ├── __main__.py           # CLI 入口點
│   └── core.py               # 圖像處理、驗證、打包邏輯
├── web/
│   ├── __init__.py
│   └── app.py                # FastAPI 網頁應用
├── tests/
│   ├── test_core.py          # 核心邏輯單元測試
│   └── test_web.py           # Web API 測試
├── pyproject.toml            # 專案設定與相依套件
└── README.md
```

---

## 安裝

需要 Python 3.10 以上。

```bash
# 基本安裝（CLI + Web）
pip install -e .

# 含測試工具
pip install -e ".[dev]"

# 含自動去背（需要額外下載模型，第一次執行較慢）
pip install -e ".[rembg]"
```

---

## CLI 使用方式

```bash
# 基本用法（處理資料夾內的圖片，輸出 16 張貼圖的 ZIP）
line-sticker-tool --input ./my_images --output stickers.zip

# 或使用 python -m 呼叫
python -m line_sticker_tool --input ./my_images --output stickers.zip

# 指定貼圖張數
line-sticker-tool --input ./my_images --output stickers.zip --count 8

# 指定主圖與標籤圖的來源
line-sticker-tool --input ./my_images --output stickers.zip \
  --main ./my_images/logo.png --tab ./my_images/icon.png

# 關閉自動去背（離線環境或未安裝 rembg 時）
line-sticker-tool --input ./my_images --output stickers.zip --no-rembg

# 輸出 JSON 驗證報告
line-sticker-tool --input ./my_images --output stickers.zip --report report.json

# 查看說明
line-sticker-tool --help
```

### CLI 參數

| 參數 | 說明 | 預設值 |
|---|---|---|
| `--input FOLDER` | 來源圖片資料夾（PNG/JPG） | 必填 |
| `--output ZIP` | 輸出 ZIP 路徑 | 必填 |
| `--count {8,16,24,32,40}` | 貼圖張數 | `16` |
| `--main FILE` | 指定主圖來源檔案 | 自動使用第一張 |
| `--tab FILE` | 指定標籤圖來源檔案 | 自動使用第一張 |
| `--no-rembg` | 停用自動去背 | 已啟用 |
| `--report FILE` | 輸出 JSON 驗證報告（`-` 為 stdout） | 不輸出 |

---

## Web 介面使用方式

```bash
# 啟動 FastAPI 伺服器
uvicorn web.app:app --host 0.0.0.0 --port 8000 --reload

# 或直接執行
python web/app.py
```

啟動後開啟瀏覽器：

- **上傳頁面**：`http://localhost:8000/`
- **API 文件**：`http://localhost:8000/docs`（Swagger UI）
- **健康檢查**：`http://localhost:8000/health`

### Web API 端點

| 方法 | 路徑 | 說明 |
|---|---|---|
| `GET` | `/` | HTML 上傳頁面 |
| `POST` | `/process` | 接收圖片 + count，回傳 ZIP |
| `GET` | `/health` | 服務健康狀態 |

#### POST `/process` 請求格式

```
Content-Type: multipart/form-data
files: 一或多個圖片檔案（PNG/JPG）
count: 貼圖張數（8/16/24/32/40，預設 16）
```

---

## 執行測試

```bash
pytest tests/ -v
```

---

## LINE 貼圖規格說明

| 用途 | 尺寸 | 格式 | 大小限制 |
|---|---|---|---|
| 主要圖片（main） | 240x240 px | PNG（RGBA） | < 1 MB |
| 標籤圖（tab） | 96x74 px | PNG（RGBA） | < 1 MB |
| 貼圖（stickers） | 最大 370x320 px（偶數） | PNG（RGBA） | < 1 MB |
| ZIP 總包 | — | — | < 60 MB |
| 解析度 | >= 72 dpi | — | — |

---

## 功能規劃（對應規格 → 程式邏輯）

### 1) 精準尺寸模板與自動縮放

- **貼圖圖片模式**：最大寬 **370px** x 最大高 **320px**
- **主要圖片模式**：固定 **240px x 240px**
- **聊天室標籤模式**：固定 **96px x 74px**
- 輸出的寬與高會強制為 **偶數**（避免縮放時因取樣造成的失真或對齊問題）

### 2) 智慧裁切與留白（安全區）

- 在裁切介面顯示「安全區」框線
- 依準則建議，裁切後圖案與邊框保留約 **10px 留白**

### 3) 匯出規格自動校驗

匯出時自動檢查：

- **格式**：統一輸出 **PNG**
- **色彩**：強制 **RGBA**（透明背景）
- **解析度**：確保 **72dpi 以上**
- **檔案大小**：每張壓到 **1MB 以下**；批次匯出時自動打包 **ZIP**，總大小不超過 **60MB**

### 4) 內容合規性輔助

- **長寬比檢查**：偵測過於扁長或高窄的圖片並提示警告
- **色彩平衡偵測**：分析圖片亮度直方圖，警告全白或過亮的貼圖

---

## 待補內容（下一步）

- [ ] UI 流程圖（上傳 → 模式選擇 → 裁切 → 檢查 → 匯出）
- [ ] Demo 截圖或 GIF
- [ ] 更多測試案例（邊界情況）

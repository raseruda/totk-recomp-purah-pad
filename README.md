# Purah Pad — Second Screen Mod for Tears of the Kingdom PC Recomp

Interactive real-time second-screen (or mobile/LAN) companion mod for **The Legend of Zelda: Tears of the Kingdom** running on **totk-pc-recomp** (`valentderah/totk-pc-recomp`).

**Standalone Release — NO Python or external dependencies required!**  
Simply extract `winmm.dll` and the `PurahPad/` folder into your TotK Recomp installation folder and launch the game (`totk.exe`). Purah Pad starts automatically on **Monitor 2**, extracts maps, icons, quests, items, and dialogue texts locally from your own game files (`romfs/`) **matching your configured game language**, and syncs live with game memory and your active save slot.

---

## Automatic Game Language Sync / Sincronização Automática de Idioma

**English:**  
Purah Pad automatically follows your game's configured language — you do **not** need to configure anything manually after installation:
- **Detection order (matches TotK Recomp):** `TOTK_LANG` / `TOTK_LOCALE` env var → `totk.ini` (`lang` / `locale` under `[language]`) → `totk-install.json` → Windows system locale → `USen` fallback.
- **All 15 official TotK RomFS languages supported:** `USen` (English US), `EUen` (English EU), `USpt` (Português Brasil), `USes` (Español Latino), `EUes` (Español España), `USfr` (Français CA), `EUfr` (Français FR), `EUde` (Deutsch), `EUit` (Italiano), `EUnl` (Nederlands), `EUru` (Русский), `JPja` (日本語), `KRko` (한국어), `CNzh` (简体中文), and `TWzh` (繁體中文).
- **Both data & UI adapt automatically:** Item names, descriptions, shop inventories, currencies, quests, locations, Korok puzzles, monsters/animals/plants, and Compendium entries are extracted directly from your game's matching `Mals/<Code>` RomFS archive, while the interface automatically mirrors your language (full UI translations for English & Portuguese, plus localized navigation/tabs/layers/settings for all other supported languages).
- **Live reload & manual override:** If you change `lang` in `totk.ini` while playing, Purah Pad detects it automatically and rebuilds the cache; you can also override the language anytime via **⚙ Settings → Language**.

**Português (Brasil):**  
O mod já inclui o **runtime oficial do Python 3.12 embutido de forma 100% standalone (não precisa instalar Python nem nenhuma biblioteca externa!)** e **acompanha automaticamente o idioma do seu jogo**:
- **Ordem de detecção automática:** variável `TOTK_LANG` / `TOTK_LOCALE` → arquivo `totk.ini` (`lang` / `locale` em `[language]`) → `totk-install.json` → idioma do Windows → padrão `USen`.
- **Suporte aos 15 idiomas oficiais do RomFS do TotK:** `USpt`, `USen`, `EUen`, `USes`, `EUes`, `USfr`, `EUfr`, `EUde`, `EUit`, `EUnl`, `EUru`, `JPja`, `KRko`, `CNzh` e `TWzh`.
- **Textos do jogo e interface sincronizados:** Santuários, itens, lojas, moedas, missões, locais, monstros, animais, plantas e Enciclopédia são extraídos diretamente do arquivo de idioma oficial (`Mals/<Idioma>`) do seu próprio jogo, e toda a interface web acompanha o idioma detectado.
- **Troca automática ou manual:** Alterando `lang` no `totk.ini`, o Purah Pad detecta e reconstrói o cache no novo idioma; se preferir escolher outro idioma manualmente, basta abrir **⚙ Configurações → Idioma**.

---

## Features / Principais Recursos

- **Zero-Setup Auto-Start (`winmm.dll` + embedded official `python312.dll`)**: `winmm.dll` loads the official Python Software Foundation–signed `python312.dll` runtime directly in-process with open readable `.py` scripts — zero `.exe` files, zero PyInstaller wrappers, and zero external Python installation needed. Drop `winmm.dll` and `PurahPad/` next to `totk.exe`, and opening the game automatically launches Purah Pad borderless on Monitor 2 and closes cleanly when you exit.
- **Real-Time Interactive Map (Sky, Surface, Depths)**:
  - **Auto-Layer** tracking Link's vertical coordinate + smooth **Follow Link** tracking.
  - **3 Map Modes**: **Spoiler-Free** (only discovered regions/markers), **Assist / Radar** (`50 m – 1000 m`, default `200 m` reveal circle around Link), and **Completionist** (everything across Hyrule).
  - **Revealed Map Only (Fog of War)** & **Hide Completed** toggles.
  - **Nearby Radar Sidebar (`📡 Nearby` / `Por Perto`)**: Live drawer sorted by relevance and distance around Link across quests, towers, shrines, shops, chests, quest NPCs, monsters, animals, and plants.
  - **Bidirectional Pins & Stamps**: View, place, move, or remove in-game colored pins and stamps directly from your second screen, plus save custom browser notes.
  - **Shop Inventories & Quest NPC Badges**: Click any shop (including Bargainer Statues and Crystal Refineries) to inspect all items for sale with prices and currencies. NPCs with available side quests display a golden quest icon and link straight to the Adventure Log.
- **Complete Item Catalog / Wiki**: Browse weapons, bows, arrows, shields, armor, materials, recipes, Zonai devices, and key items showing **where to obtain** each item (shops, chests, Zonai dispensers, world gathering, monster drops, and Compendium regions) with **Show on Map** buttons.
- **Inventory, Quest Journal & Archives**: Live pouch & sage vows viewer, fused materials/bonuses, Quest Journal with steps & waypoints, Hyrule Compendium, Character Profiles, Recipes, Memories, and Photo Album lightbox.
- **Persistent User Settings (`v1.2.2+`)**: All last-used settings (Map Mode, Radar radius, Fog of War, Hide Completed, active map layers/filters, camera position/zoom, Living World toggles, Nearby drawer state, and active tab filters) are automatically saved to `PurahPad\data\settings.json` (plus `localStorage`) and restored cleanly across game restarts.
- **Mobile / Tablet Access (`--lan`)**: While `totk.exe` is running, open `PurahPad\Iniciar Purah Pad.bat` to bring back the window (or run `PurahPad\Iniciar Purah Pad.bat --lan` with local Python installed for Wi-Fi access).
- **Full Technical & Adaptation Docs**: See [ARCHITECTURE_BLUEPRINT.md](ARCHITECTURE_BLUEPRINT.md) for a complete record of every feature, module, and blueprint for adapting this architecture to other open-world PC games.

---

## Installation / Instalação

### Requirements / Pré-requisitos
- **The Legend of Zelda: Tears of the Kingdom — PC Recomp** with extracted `romfs/` game files present in the game folder.
- **No Python installation required** (the official PSF-signed `python312.dll` embedded runtime and required modules are bundled inside `PurahPad\python\`, alongside open readable `.py` scripts).
- **Microsoft Edge**, **Google Chrome**, **Brave**, or **Vivaldi** (uses App Mode for the dedicated second-screen window; falls back to your default browser if none are installed).

### Setup Steps / Passo a passo
1. Download `PurahPad_TotK_Recomp_v1.2.2.zip` from [Releases](../../releases).
2. Extract **`winmm.dll`** and the entire **`PurahPad/`** folder into your TotK Recomp installation folder (right next to `totk.exe` and `romfs/`).
3. Launch the game normally (`totk.exe`):
   - On first launch, Purah Pad automatically detects your game language and builds the local cache of map tiles, icons, quests, and items (~15–25 seconds).
   - Every launch afterwards opens instantly on Monitor 2.
4. *(Optional)* If you closed the Purah Pad window while playing, double-click `PurahPad\Iniciar Purah Pad.bat` to reopen it cleanly without restarting the game.
   - Troubleshooting logs are written to `PurahPad\data\purah_pad.log`.

---

## Building from Source / Compilando a partir do Código-Fonte

For developers modifying the mod (end users do NOT need any of these tools):
- Python **3.12+** with packages:
  ```bash
  pip install -r requirements.txt
  ```
- **Visual Studio 2022 Build Tools** (C++ x64) for `winmm.dll`
- Build both `winmm.dll` and the embedded standalone `PurahPad/python/` runtime:
  ```bash
  python mod_native/build_proxy.py
  ```
The ready-to-distribute standalone package (with zero `.exe` files and zero nested archives) is generated inside `mod_release/`.

---

## Legal Disclaimer / Aviso Legal

This project **does not contain or redistribute** any copyrighted assets, textures, models, audio, or game data from *The Legend of Zelda: Tears of the Kingdom* / Nintendo. All maps, icons, and localized texts are extracted locally at runtime from the user's own legitimate copy of the game.

---

## License

Released under the [MIT License](LICENSE).

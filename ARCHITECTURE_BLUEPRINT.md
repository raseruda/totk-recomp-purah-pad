# Arquitetura & Blueprint Completo — Purah Pad (TotK PC Recomp → Adaptável para Ghost Recon Wildlands)

Este documento registra **todas as funcionalidades implementadas**, a **arquitetura técnica completa** (backend, proxy nativo, runtime embarcado, frontend e persistência) e o **guia de adaptação para criar o mod equivalente de segunda tela para *Tom Clancy's Ghost Recon Wildlands***.

---

## 1. Catálogo Completo de Funcionalidades (`v1.2.2`)

### 1.1 Inicialização Automática & Janela Dedicada na Segunda Tela
- **Auto-start sem configuração (`winmm.dll`)**: ao colocar `winmm.dll` e a pasta `PurahPad/` na pasta do jogo (`totk.exe`), o jogo carrega automaticamente o runtime do mod sem precisar abrir terminais nem instalar Python.
- **Detecção de Monitor Secundário (`launcher.py`)**: enumera os monitores do Windows via `EnumDisplayMonitors`, escolhe o primeiro monitor não-primário (ou o primário se houver só uma tela) e abre o navegador em **App Mode** (`--app=http://127.0.0.1:PORT`, perfil isolado em `cache/edge_profile`, posicionado e maximizado na segunda tela). Suporta **Microsoft Edge**, **Google Chrome**, **Brave** e **Vivaldi** (por caminhos padrão e Registro `App Paths`), com fallback para `webbrowser.open()`.
- **Encerramento Limpo & Reabertura Rápida**:
  - No `DLL_PROCESS_DETACH` da `winmm.dll`, envia `WM_CLOSE` para a janela do navegador (`g_app_hwnd`) quando `totk.exe` fecha.
  - Se o jogador fechar a janela do Purah Pad durante a partida, executar `PurahPad/Iniciar Purah Pad.bat` detecta `totk.exe` ativo via `tasklist` e reabre a janela `--app=http://127.0.0.1:8765` sem reiniciar o servidor.
- **Modo Rede Local / Celular / Tablet (`--lan`)**: vincula o servidor HTTP em `0.0.0.0` e exibe o IP da LAN no modal de configurações para abrir em tablets ou smartphones (com suporte a touch pan/tap no Canvas).

### 1.2 Mapa Tático Interativo em 60 FPS (`web/map.js`)
- **Canvas Multi-LOD com 3 Camadas**: `sky` (Céu), `surface` (Superfície) e `depths` (Profundezas), com zoom contínuo (`0.06` a `2.6`), pan fluido por mouse/touch, atalho `Espaço` para centralizar no Link e tiles baixados/decodificados sob demanda do RomFS.
- **Auto-camada & Seguir Link**: troca automaticamente entre Céu / Superfície / Profundezas conforme a altura vertical e centraliza no jogador em tempo real (desativa o *Seguir Link* automaticamente ao arrastar o mapa com o mouse).
- **3 Modos de Visibilidade**:
  1. **Sem Spoilers (`spoiler_free`)**: oculta santuários, Koroks, baús, chefes e segredos ainda não descobertos/concluídos no save.
  2. **Auxílio / Radar (`assist`)**: exibe tudo já descoberto **mais** tudo o que estiver dentro de um raio configurável ao redor do Link (`50 m` a `1000 m`, padrão `200 m`).
  3. **Completista (`full`)**: exibe todos os marcadores de Hyrule sem restrição de descoberta.
- **Só Mapa Revelado (Fog of War — `#chk-fog`)**: aplica as máscaras reais das **15 Torres Panorâmicas** (`masks/region_TowerXX.png` e `border_TowerXX.png`) e região inicial (`BeginningIsland`) sobre os tiles para esconder regiões ainda não mapeadas nas torres ou não iluminadas nas Profundezas.
- **Ocultar Já Coletados (`#chk-hide-done`)**: esconde automaticamente santuários concluídos, Koroks pegos, baús abertos, raízes acesas, sapos Bubbul, poços, placas do Addison, chefes derrotados, etc.
- **29 Categorias de POIs + Contadores Dinâmicos**: `skyview_towers`, `shrines`, `lightroots`, `shops` (76 lojas/serviços), `stables`, `caves`, `bubbuls`, `wells`, `chasms`, `dispensers`, `locations`, `dragon_tears`, `great_fairies`, `hidden_koroks`, `carry_koroks`, `sages_wills`, `old_maps`, `schema_stones`, `yiga_schematics`, `addison_signposts`, `armor_chests`, `treasure_chests`, `hinoxes`, `taluses`, `moldugas`, `flux_constructs`, `froxes`, `gleeoks`, `lynels`. Inclui barra de busca global no mapa e botões *Todos* / *Limpar*.
- **Mundo Vivo (`entities.json`)**: exibição opcional sob demanda de **NPCs** (`1108`), **Animais** (`3305`), **Plantas** (`24717`) e **Monstros** (`7649`), respeitando estritamente o raio do Radar no modo `assist` ou as regiões descobertas no modo `spoiler_free`.
- **NPCs com Missão Secundária Destacada**: NPCs que possuem missões disponíveis/desbloqueáveis recebem ícone dourado exclusivo (`entity_npc_quest.png`) e listam as quests no painel lateral com atalho direto para a aba *Missões*.
- **Lojas & Estoques**: clicar em qualquer loja no mapa abre a lista completa de itens à venda, quantidades por lote, preço e moeda (*Rupees*, *Poes*, *Zonaite*, etc.), com clique direto para abrir o item no **Catálogo / Wiki**.
- **Drawer Lateral `Por Perto` / Radar (`#map-nearby`)**: painel dinâmico atualizado conforme o Link se move, ordenando pontos próximos no raio do radar por **relevância × proximidade** (`POI_WEIGHTS`, `ENTITY_WEIGHTS`, peso extra para missões ativas e NPCs de missão), com chips de filtro (`Todos`, `POIs`, `NPCs`, `Inimigos`, `Recursos`).
- **Caminho do Herói (`footprint.sav` + trilha da sessão)**: desenha o trajeto histórico gravado pelo jogo por camada + pontos de morte + trilha ao vivo da sessão atual.
- **Pinos Coloridos & Carimbos Bidirecionais + Marcadores Próprios**:
  - Lê e grava em tempo real na memória do jogo os pinos de telescópio (`Red`, `Blue`, `Yellow`, `Green`, `Purple`, `LightBlue` — 6 cores reais do jogo) e carimbos (`Sword`, `Pot`, `Human`, `Rhombus`, `Heart`, `Star`, `TreasureBox`, `Skull`, `Leaf`, `Ore` — 10 tipos).
  - Permite também salvar marcadores pessoais ilimitados (título, nota, cor, ícone, camada, coordenadas) persistidos localmente em `PurahPad/data/user_markers.json` (menu de contexto com botão direito no mapa ou botão `+ Marcador`).

### 1.3 Inventário, Missões, Arquivos & Catálogo/Wiki (`web/app.js`)
- **Aba Inventário**: status dos **5 Sábios** (bloqueado / convocado / dispensado), categorias da bolsa (`weapons`, `bows`, `shields`, `armor`, `materials`, `food`, `zonai`, `keyItems`, `arrows`), busca instantânea, selo de equipado, ícone de material fundido (*Fuse*), durabilidade, bônus/modificador de arma, receita/efeito/coração de pratos e tintura de armaduras.
- **Aba Missões (*Adventure Log*)**: filtros por categoria (`main_quest`, `side_adventure`, `shrine_quest`, `side_quest`), por estado (`active`, `available`, `complete`, `locked`, `all`), etapas completas com destaque na etapa atual e botão **Ver no mapa** apontando para o marcador da etapa.
- **Aba Arquivos**: 5 sub-abas — **Enciclopédia** (Compendium com filtro anti-spoiler), **Perfis de Personagens**, **Receitas**, **Memórias** e **Álbum de Fotos** (lê os JPEGs reais de `profile/save/<uid>/album/` com lightbox e metadados de localização/ator).
- **Aba Catálogo / Wiki (`1762` itens)**: enciclopédia pesquisável de todos os itens do jogo com filtro *Vendidos em lojas* e *Mostrar variantes / internos*, detalhando **onde conseguir** cada item (lojas + preços, baús com botão *Ver no mapa*, dispensadores Zonai, drops de monstros e spawns no mundo destacando no mapa com banner de filtro ativo).
- **HUD Superior Ao Vivo**: barra persistente exibindo modo de conexão (`AO VIVO` / `TELA TÍTULO` / `SAVE LOCAL` / `OFFLINE`), corações, stamina, células de bateria Zonai, Rupees, Poes, efeito ativo e coordenadas `(X, Z, Y)`.

### 1.4 Internacionalização & Persistência Completa (`config.py`, `server.py`, `web/i18n.js`, `web/app.js`)
- **Sincronização Automática de Idioma (15 idiomas oficiais do TotK)**:
  - Ordem de detecção em `detect_game_language()`: `TOTK_LANG` / `TOTK_LOCALE` → `totk.ini` → `totk-install.json` → Locale do Windows (`GetUserDefaultUILanguage`) → `USen`.
  - Reconhece dinamicamente alterações no `totk.ini` em tempo real ou seleção manual em `⚙ Configurações`, reconstruindo o cache no `Mals/<Code>` correspondente.
- **Persistência Integral das Configurações (`v1.2.2`)**:
  - Salvas automaticamente em **`PurahPad/data/settings.json`** (via `GET` / `POST /api/settings`) com espelho instantâneo em `localStorage` (`purahpad_prefs_v2`) e envio garantido no fechamento (`pagehide` / `beforeunload` + `navigator.sendBeacon`):
    - **Modo & Visibilidade:** `mapMode`, `assistRadius`, `fogOfWar`, `hideCompleted`.
    - **Câmera & Camada:** `layer`, `camX`, `camZ`, `zoom`, `autoLayer`, `followLink`.
    - **Exibição do Mapa:** `showHeroPath`, `showPins`, `showQuests`, `showCustom`, `enabledCats` (todas as categorias ligadas), `enabledEntities` (NPCs/Animais/Plantas/Monstros).
    - **Layout & Drawers:** `sidebarCollapsed`, `nearbyOpen`, `nearbyManuallyClosed`, `nearbyFilter`.
    - **Abas & Sub-filtros:** `activeTab`, `invCat`, `questCat`, `questStatus`, `archiveSub`, `archiveCat`, `archiveSpoiler`, `wikiCat`, `wikiShopsOnly`, `wikiAllRanks`.

---

## 2. Arquitetura Técnica & Mapa de Módulos

### 2.1 Estrutura de Arquivos
| Arquivo | Camada | Responsabilidade |
| :--- | :--- | :--- |
| `mod_native/build_proxy.py` | Build & Native Proxy | Compila `winmm.dll` (proxy x64 com `181` exports) e monta o runtime oficial embeddable do Python 3.12 + pacotes binários filtrados dentro de `mod_release/` |
| `launcher.py` | Bootstrap & Browser Host | Ponto de entrada (`main()` CLI / `run_embedded()` in-process); seleciona monitor secundário, abre navegador em App Mode, sincroniza `g_app_hwnd` com a DLL nativa e grava logs em `data/purah_pad.log` |
| `config.py` | Configuração & Paths | Resolve `ROOT_DIR`, detecta pasta do jogo e idioma (`totk.ini`), gerencia `load_settings()` / `save_settings()` atômicos com `threading.RLock()` e localiza `progress.sav` mais recente |
| `totk_formats.py` | Decodificadores RomFS | Descompactação `zstandard`, parsers `SARC`, `BYML`, `MSBT`, hash `MurmurHash3 (mmh3)` e decodificação de texturas `BNTX` (ASTC/BC1-7 via `texture2ddecoder` + `Pillow`) |
| `asset_builder.py` | Extrator & Cache v5 | Extrai em ~22s tiles, ícones, máscaras de torre, `map_data.json`, `entities.json`, `quests.json` e `catalog.json` diretamente do `romfs/` do usuário para `PurahPad/cache/` |
| `save_reader.py` | Leitor de Save Local | Lê `progress.sav` (`GameData` binário por hash `mmh3`), `footprint.sav` (Caminho do Herói) e álbum de fotos, avaliando progresso de POIs, inventário, missões e arquivos |
| `live_memory.py` | Leitor/Escritor de Memória | Conecta ao processo `totk.exe` (próprio PID quando embutido ou via `CreateToolhelp32Snapshot`) via `ReadProcessMemory` / `WriteProcessMemory`; valida hash de segurança `GUARD_SHA256_V143`, lê pose 10 Hz + inventário ao vivo e cria/remove pinos e carimbos no mapa do jogo |
| `server.py` | Servidor HTTP + SSE | `PurahPadHTTPServer` (`ThreadingHTTPServer`) servindo estáticos com compressão gzip, stream SSE `/api/stream`, polling 10 Hz ao vivo / fallback para save, marcadores customizados e API de settings |
| `Iniciar Purah Pad.bat` | Utilitário do Usuário | Se `totk.exe` estiver rodando, reabre a janela `--app`; se fechado e houver Python dev, inicia offline; caso contrário explica em EN/PT-BR que Python não é necessário |
| `Instalar Mod na Pasta do Jogo.bat` | Script Dev Local | Copia `mod_release/winmm.dll` e `PurahPad/` para a pasta do jogo para testes rápidos |
| `web/index.html`, `web/style.css` | UI Estrutural | Layout estilo *Purah Pad* / Sheikah-Zonai escuro, abas, drawers, modais de configuração e lightbox de fotos |
| `web/i18n.js` | Internacionalização UI | Traduções completas (`en`, `pt`, além de chaves mapeadas para os 15 códigos RomFS) aplicadas via atributos `data-i18n` |
| `web/map.js` | Motor Canvas 2D | `PurahMap.MapController` com carregamento sob demanda de tiles/ícones, composição de Fog of War via máscaras offscreen, hit-testing, pan/zoom e Caminho do Herói |
| `web/app.js` | Estado & Controlador Web | EventSource `/api/stream`, polling de snapshot, rendering de abas/drawers/wiki, editor de pinos/marcadores e sincronia bidirecional de preferências `ui_prefs` |

### 2.2 Superfície da API HTTP Local (`127.0.0.1:8765`)
- **GET:**
  - `/api/status`: estado do build do cache, modo de conexão (`live`/`title`/`save`/`offline`), idioma ativo/origem, slot de save e URL LAN.
  - `/api/settings`: retorna `{ lang, lang_setting, lang_source, ui_prefs }`.
  - `/api/live`, `/api/snapshot`, `/api/stream` (SSE `text/event-stream`).
  - `/api/footprint`, `/api/markers`.
  - `/api/static/{map_data,quests,catalog,entities}` (JSON gzipado).
  - `/api/tile/{layer}/{lod}/{col}/{row}.png`, `/api/icon/{kind}/{name}.png`, `/api/mask/{id}.png`, `/api/album/{file}.jpg`.
- **POST / PUT / DELETE:**
  - `POST /api/settings`: atualiza idioma (`{ "lang": "..." }`, dispara rebuild só se idioma mudar) e/ou persiste `{ "ui_prefs": { ... } }` em `settings.json`.
  - `POST /api/rebuild`: força reconstrução do cache do RomFS.
  - `POST /api/markers`, `PUT /api/markers/{id}`, `DELETE /api/markers/{id}`.
  - `POST /api/game/pins`, `DELETE /api/game/pins/{slot}`, `POST /api/game/stamps`, `DELETE /api/game/stamps/{slot}`.

---

## 3. Padrão Zero-Python, Zero-`.exe` e `0/67` no VirusTotal (Lição da v1.2.0 → v1.2.1)

Na **v1.2.0**, empacotar com **PyInstaller (`PurahPad.exe`)** causou **quarentena automática no Nexus Mods** por 3 motivos críticos:
1. Arquivos `.exe` soltos ou gerados por empacotadores (PyInstaller) ativam heurísticas pesadas (recebeu **9/67** no VirusTotal / família `Gen:Variant.Yogi.119680`, com `PurahPad.exe` marcando `11/71`).
2. O PyInstaller gera `base_library.zip`, que é um **`.zip` aninhado** — o scanner interno do Nexus Mods bloqueia arquivos contendo `.zip` dentro de `.zip`.
3. `winmm.dll` chamando `CreateProcessW` aumenta pontuação heurística de loaders.

### Solução Adotada (Padrão Recomendado para Futuros Projetos)
1. **`winmm.dll` em C/ASM puro (`cl /LD /MT` + `ml64`) sem `CreateProcessW`**:
   - Espelha exatamente os 181 exports da `System32\winmm.dll` via tabela `jmp [g_winmm_procs + idx*8]`.
   - Importa **apenas `KERNEL32.dll`** na tabela PE.
   - Em uma thread criada após `Sleep(250)`, pré-carrega as DLLs oficiais de `PurahPad/python/` com `LoadLibraryExW(..., LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)` na ordem: `vcruntime140.dll`, `vcruntime140_1.dll`, `libffi-8.dll`, `python3.dll`, `python312.dll`.
   - Resolve `Py_InitializeEx`, `Py_IsInitialized` e `PyRun_SimpleString`, inicializa com `Py_InitializeEx(0)` (sem sobrescrever handlers de sinal do jogo) e chama `launcher.run_embedded(game_dir, &g_app_hwnd)`.
   - No `DLL_PROCESS_DETACH`, usa `GetModuleHandleW(L"user32.dll")` + `GetProcAddress(..., "PostMessageW")` (sem `LoadLibrary` dentro de `DllMain`) para enviar `WM_CLOSE` à janela do navegador.
2. **Runtime Oficial Embarcado Limpo (`build_embedded_python()`)**:
   - Baixa `python-3.12.10-embed-amd64.zip` oficial (assinado pela **Python Software Foundation** e Microsoft), descompacta `python312.zip` dentro de `PurahPad/python/Lib/` e **apaga `python312.zip`, `python.exe` e `pythonw.exe`**.
   - Mantém **somente os `.pyd`/`.dll` estritamente usados**, descartando extensões não utilizadas (ex.: em Pillow, manteve apenas `_imaging.cp312-win_amd64.pyd`, removendo `_imagingmorph`, `_imagingtk`, `_avif`, `_webp`, `_ssl`, `_crypto`, etc. que geravam falsos positivos ou peso morto).
   - Configura `python312._pth` (`Lib`, `.`, `site-packages`, `..`) ignorando completamente `PYTHONHOME`/`PYTHONPATH` do sistema do usuário.
   - **Resultado comprovado na v1.2.1:** **`0` `.exe`**, **`0` arquivos aninhados**, **VirusTotal `0 / 67`** e selo verde **`Safe to use`** imediato no Nexus Mods.

---

## 4. Pipeline Legal & Distribuição de Assets

- Nenhum arquivo do jogo original (`.png`, `.byml`, `.sarc`, `.msbt`, `.sav`) é empacotado no `.zip` de release nem commitado no GitHub.
- O extrator roda **exclusivamente na máquina do jogador** na primeira abertura, lendo a instalação legítima local para popular `PurahPad/cache/`.
- Scripts de empacotamento devem sempre validar por `assert`: zero `cache/`, zero `data/`, zero `__pycache__/`, zero `.exe`, zero `.zip`/`.7z`/`.whl` internos e zero `.sav`/`.log`.

---

## 5. Blueprint para Adaptar este Mod ao *Tom Clancy's Ghost Recon Wildlands* (GRW)

A estrutura central do Purah Pad (servidor local `HTTP + SSE`, motor Canvas 2D multi-LOD, sistema de Radar + drawer `Por Perto`, persistência completa de `ui_prefs` em `data/settings.json`, internacionalização e empacotamento standalone embutido sem `.exe`) é **~75% reaproveitável diretamente**. Abaixo estão os pontos exatos do que muda para **Ghost Recon Wildlands**.

### 5.1 Alerta Crítico de Arquitetura: EasyAntiCheat (EAC)
> **Diferença fundamental em relação ao TotK PC Recomp:** O `totk.exe` não possui anti-cheat em nível de kernel, permitindo que `winmm.dll` carregue código no processo e leia `ReadProcessMemory` livremente. Já *Tom Clancy's Ghost Recon Wildlands* (`GRW.exe`) usa **EasyAntiCheat (EAC)** por padrão.
> - **Com EAC ativo:** O EAC **bloqueia** injeção de proxy DLL (`winmm.dll` / `dinput8.dll` / `dxgi.dll`) não assinada e nega `OpenProcess(PROCESS_VM_READ)` a partir de processos externos!
> - **Caminhos viáveis para o projeto de GRW:**
>   1. **Requisito explícito de Modo Offline / Single-Player sem EAC:** Como ocorre com outros mods de GRW no Nexus Mods (First Person Mod, mods `.forge`, Cheat/Trainer tables), o mod de segunda tela **deve ser documentado exclusivamente para jogo offline/single-player com EAC desabilitado** via launcher oficial offline/modding suportado pelo jogo/comunidade (nunca suportar nem tentar contornar EAC para multiplayer público!). Nesse modo offline sem o driver do EAC carregado, **exatamente o mesmo proxy `winmm.dll` ou `dxgi.dll` + runtime `python312.dll` + `ReadProcessMemory` funciona 100%**.
>   2. **Modo Passivo (sem memória ao vivo / somente leitura de save + mapa tático interativo):** Se o usuário jogar com EAC ligado, um inicializador opcional pode rodar apenas como companion estático/checklist lendo os arquivos de save locais (`.sav` na pasta `Ubisoft Game Launcher/savegames/<uid>/1771` ou equivalente Steam) + mapa tático completo da Bolívia, porém sem telemetria em tempo real de posição do jogador.

### 5.2 O Que Reaproveitar Direto vs. O Que Substituir
| Componente TotK | Aproveitamento no GRW | O Que Fazer no Novo Repositório |
| :--- | :--- | :--- |
| `mod_native/build_proxy.py` | **95% reutilizável** | Ajustar `ends_with_ci(exe_path, L"\\grw.exe")` (ou testar se GRW importa `winmm.dll` ou `version.dll` / `dxgi.dll` quando EAC está desligado); trocar pastas para `GhostReconPad/` |
| `launcher.py` & `Iniciar *.bat` | **95% reutilizável** | Trocar nomes/mutex (`Local\GRW_TacticalPad_...`) e título da janela para matching em `_find_app_window` |
| `config.py` (`_SETTINGS_LOCK`, `load/save_settings`) | **90% reutilizável** | Trocar detecção da pasta do jogo (`GRW.exe`, `DataPC*.forge`), detecção de idioma (`uplay` / arquivos `.ini` ou registro do jogo) e caminho do save Ubisoft |
| `server.py` (HTTP, SSE, `_sanitize_ui_prefs`) | **85% reutilizável** | Manter estrutura SSE 10 Hz, `/api/settings` com persistência completa de `ui_prefs`, marcadores do usuário e estáticos gzip; ajustar rotas específicas de marcadores/armas/províncias |
| `web/map.js` (Canvas 60 FPS) | **85% reutilizável** | Trocar sistema de **3 camadas** (Céu/Superfície/Profundezas) por **1 mapa único contínuo da Bolívia** com zoom multi-LOD e polígonos/máscaras das **21 Províncias** (Fog of War por província revelada) |
| `web/app.js` + `web/i18n.js` | **75% reutilizável** | Manter integralmente sistema de abas, `collectAllPrefs`/`applyAllPrefs`/`sendBeacon`, drawer `Por Perto` (Radar tático), busca, marcadores customizados e lightbox |
| `totk_formats.py` | **Substituir (`anvil_formats.py`)** | Implementar leitor de pacotes **AnvilNext 2.0 (`.forge`)** + descompressão LZ4/Oodle/Zlib usada nos arquivos do GRW (para extrair tiles do mapa, ícones DDS/DXT e tabelas localizadas direto da cópia do usuário) |
| `asset_builder.py` | **Substituir (`grw_asset_builder.py`)** | Extrair localmente do `.forge` os tiles do mapa satelital/topográfico da Bolívia, os ícones de missões/facções e o banco de dados de armas, acessórios, arquivos Kingslayer e colecionáveis |
| `save_reader.py` | **Substituir (`grw_save_reader.py`)** | Ler o progresso das 21 províncias (chefes do Cartel de Santa Blanca, missões principais, rebel ops, colecionáveis já pegos e loadout salvo) — caso o save seja criptografado/ofuscado pela Ubisoft, combinar leitura de flags em memória durante o jogo |
| `live_memory.py` | **Substituir (`grw_memory.py`)** | Resolver base de `GRW.exe` (via `EnumProcessModules` / `CreateToolhelp32Snapshot`), validar versão do executável e ler em 10 Hz os ponteiros ao vivo descritos abaixo |

### 5.3 Mapeamento Funcional (TotK → Ghost Recon Wildlands)
1. **Aba Mapa Tático (Bolívia — 21 Províncias)**:
   - **Camadas de Dados / Modos:** Manter os 3 modos (*Sem Spoilers*, *Auxílio/Radar* com raio em metros ao redor do Ghost/Drone, e *Completista*), mais **Só Regiões Reveladas** (províncias exploradas vs. névoa) e **Ocultar Já Coletados**.
   - **Categorias de POIs (equivalentes às 29 de Hyrule):**
     - Bases da **Unidad** e Postos Avançados **Santa Blanca** (com indicação de tamanho/nível de alerta e sistemas *SAM* / bloqueadores de drone *Jammer*!).
     - **Missões de História & Buchones** por ala do Cartel (Segurança, Contrabando, Produção, Influência).
     - **Rebel Ops** (Suporte de Morteiro, Distração, Avistamento, Entrega de Veículo, Spawns de Rebeldes).
     - **Colecionáveis:** **Caixas de Armas** (*Weapon Cases*), **Acessórios de Arma** (*Accessories* — miras, silenciadores, pentes, coronhas), **Medalhas de Bônus**, **Pontos de Habilidade** (*Skill Points*), **Documentos Kingslayer**, **Lendas**, **Comboios de Suprimento** (*Medicamentos / Comida / Combustível / Comunicações*) e **Spawn de Veículos** (helicópteros com míssil, blindados).
   - **Radar Tático / "Por Perto" & Entidades Ao Vivo (se lidos via memória no modo offline):**
     - Posição e orientação do **Ghost** (a pé, em veículo ou de paraquedas) **+ posição ao vivo do Drone / Binóculos**!
     - Inimigos **marcados (*Tagged Enemies*)**, atiradores de elite (*Snipers*), pesados, alarme (*Alarm Panel*), gerador (*Generator*), *Jammers* e baterias **SAM** próximas ordenados por distância e ameaça no drawer lateral `Por Perto`!
     - Indicador de estado tático no HUD superior: **`UNDETECTED`** / **`SUSPECTED`** / **`HUNTED`** / **`ENGAGED`**, vida/down-but-not-dead, munição, nível (*Tier One*) e coordenadas `(Lat / Long / Alt)`.
     - Marcadores customizados táticos (ex.: rota de infiltração, posição de sniper do jogador, ponto de extração) e sincronização com o *GPS Waypoint* do jogo, se mapeado na memória.
2. **Aba Arsenal / Loadout (equivalente a Inventário)**:
   - Visualização em tempo real ou do save das armas equipadas (Primária, Secundária, Pistola), anexos instalados em cada slot (Mira, Cano, Trilho, Boca, Carregador, Coronha, Pintura), equipamentos (*Gadgets*: Drone EMP/Explosivo/Médico, C4, Minas, Granada de Clarão, Flare) e árvore de **Habilidades (*Skills*)**.
3. **Aba Cartel & Missões (equivalente a Missões)**:
   - Árvore hierárquica do **Cartel de Santa Blanca** (El Sueño + os 4 chefes de ala + todos os *Buchones* por província), status de conclusão de missões principais, operações especiais (Silent Spade, Watchman, Archangel, Oracle) e botão **Ver no mapa**.
4. **Aba Arquivos & Inteligência (equivalente a Arquivos)**:
   - **Arquivos Kingslayer** completos (áudios transcritos / dossiês / lendas), gravações do Cartel e perfis dos alvos e operadores.
5. **Aba Catálogo / Armeiro Wiki (equivalente ao Catálogo)**:
   - Banco pesquisável de **todas as Armas e Acessórios** do GRW com estatísticas (Dano, Precisão, Manuseio, Alcance, Cadência, Penetração, Redução de Ruído) e **onde encontrar exatamente cada peça** (província + base específica) com botão **Ver no mapa** levando direto ao baú/caixa correspondente!

### 5.4 Checklist Obrigatório antes de Publicar o Projeto de GRW no Nexus Mods
1. Confirmar explicitamente na página e README o requisito de **Modo Offline / Single-Player sem EasyAntiCheat** para telemetria em memória.
2. Distribuir **apenas via runtime oficial PSF `python312.dll` + proxy `.dll` nativo sem `.exe` e sem `.zip`/`.7z` aninhados** (sem PyInstaller!).
3. Conferir que o `.zip` final passa em **`0 / 67`** no VirusTotal e recebe selo verde **`Safe to use`** no Nexus Mods antes de divulgar.
4. Garantir **persistência integral (`data/settings.json` + `localStorage` + `sendBeacon`)** desde a `v1.0.0`.
5. Nunca empacotar assets extraídos dos arquivos `.forge` da Ubisoft no repositório nem no download do Nexus Mods — sempre extrair localmente do jogo do usuário no primeiro uso.

# Purah Pad — Second Screen Mod for Tears of the Kingdom PC Recomp

Companion interativo em tempo real (segunda tela / LAN) para **The Legend of Zelda: Tears of the Kingdom** rodando no **totk-pc-recomp** (`valentderah/totk-pc-recomp`).

Abre automaticamente no **Monitor 2** ao iniciar o jogo via proxy nativo `winmm.dll`, extrai localmente mapas, ícones, missões e textos diretamente da sua própria cópia do jogo (RomFS) e sincroniza ao vivo com a memória do processo e com o save ativo.

---

## Principais Recursos / Key Features

- **Auto-start no Monitor 2 (`winmm.dll`)**: Basta colocar `winmm.dll` e a pasta `PurahPad/` na raiz do jogo; ao abrir `totk.exe`, o Purah Pad abre automaticamente em janela sem bordas no segundo monitor (e fecha com segurança quando o jogo termina).
- **Mapa Interativo em Tempo Real**:
  - **Camadas Céu, Superfície e Profundezas** com troca automática seguindo a altitude do Link (`Auto-camada`).
  - **3 Modos de Visualização**:
    - **Sem Spoilers**: Mostra apenas santuários, torres, koroks e áreas que você já descobriu no save.
    - **Auxílio / Radar** (`200 m – 1000 m`): Revela tudo em um raio configurável ao redor do Link em tempo real.
    - **Complecionista**: Mostra todos os marcadores e segredos de Hyrule.
  - **Só Mapa Revelado (Fog of War)** e **Ocultar já Coletados**.
  - **Menu Lateral "Por Perto" (Radar)**: Lista viva dos pontos de interesse, missões, lojas, baús, monstros, NPCs, animais e plantas ao redor do Link, ordenados por relevância e proximidade.
  - **Pinos & Carimbos Bidirecionais**: Visualize pinos coloridos e carimbos do jogo em tempo real e crie, mova ou remova pinos/carimbos diretamente pelo Purah Pad.
  - **Inventário de Lojas & NPCs com Missões**: Clique em qualquer loja (inclusive Estátuas Peconhentas, Dispensadores/Refinarias e lojas de armadura) para ver todo o catálogo à venda com preços/moedas. NPCs com missões secundárias disponíveis exibem um ícone dourado exclusivo e botão direto para o Diário.
- **Catálogo / Wiki Completo de Itens**: Lista armas, arcos, flechas, escudos, armaduras, materiais, receitas, dispositivos Zonai e itens-chave, mostrando **onde conseguir** cada item (lojas, baús, dispensadores Zonai, coleta no mundo, drops de monstros e regiões) com botão **"Ver no Mapa"**.
- **Inventário, Diário de Missões & Arquivos**: Bolsa completa (equipamentos, fusões, bônus), Diário com passos e objetivos no mapa, Enciclopédia, Perfis de Personagens, Receitas, Memórias e Álbum de Fotos.
- **Acesso em Celular / Tablet (`--lan`)**: Rode `Iniciar Purah Pad.bat --lan` para acessar pela rede Wi-Fi local.

---

## Instalação / Installation

### Pré-requisitos
- **The Legend of Zelda: Tears of the Kingdom — PC Recomp** com os arquivos locais (`romfs` / dados do jogo presentes na pasta de instalação).
- **Python 3.10+** instalado no Windows com as dependências:
  ```bash
  pip install -r requirements.txt
  ```
- **Microsoft Edge** ou **Google Chrome** instalado (usado em App Mode para renderizar a interface na segunda tela).

### Passo a passo
1. Baixe o arquivo `PurahPad_TotK_Recomp_v1.0.0.zip` na aba [Releases](../../releases).
2. Extraia **`winmm.dll`** e a pasta **`PurahPad/`** para a pasta raiz onde está o executável do jogo (ex.: `totk.exe`).
3. Abra o jogo normalmente:
   - Na primeira execução, o Purah Pad gera o cache local de mapas, ícones e catálogo diretamente a partir dos arquivos do seu jogo (leva ~15–25 segundos).
   - Nas execuções seguintes, inicia instantaneamente no Monitor 2.
4. *(Opcional)* Para abrir sem iniciar o jogo ou acessar pelo celular na rede local, execute `PurahPad\Iniciar Purah Pad.bat` (ou passe `--lan`).

---

## Compilando `winmm.dll` a partir do código-fonte

Caso queira recompilar o proxy nativo x64 localmente (requer **Visual Studio 2022 Build Tools** C++ x64):
```bash
python mod_native/build_proxy.py
```
O pacote pronto será gerado em `mod_release/`.

---

## Aviso Legal / Disclaimer

Este projeto **não inclui nem redistribui** quaisquer arquivos, texturas, modelos, áudio ou dados com direitos autorais de *The Legend of Zelda: Tears of the Kingdom* / Nintendo. Todos os mapas, ícones e textos exibidos na interface são extraídos localmente em tempo de execução a partir da cópia legítima do próprio usuário.

---

## Licença

Distribuído sob a licença [MIT](LICENSE).

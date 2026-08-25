# Mobi: gateway ROS 1 e bridge ROS 2

Este Compose reúne o ambiente dos repositórios `ros1_only` e
`ros2-ros1-bridge` para a base Mobi:

```text
gateway Mobi (10.10.10.199)
          | rosserial TCP :11411
          v
rosserial + roscore (ROS 1 Noetic, host 10.10.10.1)
          |
          v
dynamic_bridge -> tópicos ROS 2 Humble
```

Foram detectados neste computador:

- interface USB-C Ethernet: `enx00e04c360038`;
- IP do computador nessa interface: `10.10.10.1/24`;
- gateway da base: `10.10.10.199` (respondendo a ping);
- porta rosserial padrão: `11411`.

## Iniciar

Na pasta `mobi`:

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f rosserial ros1-bridge
```

O primeiro build do bridge é demorado porque ele é compilado. O arquivo
pré-compilado de `ros2-ros1-bridge` é ARM64/Jetson e não executa diretamente
neste PC amd64; por isso o Dockerfile gera um binário nativo usando a mesma
estratégia e o mesmo branch `action_bridge_humble` do projeto de referência.
A compilação fica limitada a quatro jobs paralelos para não esgotar a memória
do computador.

## Verificar os tópicos

ROS 1:

```bash
docker compose exec ros-master bash -c \
  'source /opt/ros/noetic/setup.bash; rostopic list'
```

ROS 2:

```bash
docker compose exec ros1-bridge bash -c \
  'source /opt/ros/humble/setup.bash; source /ros-humble-ros1-bridge/install/local_setup.bash; ros2 topic list'
```

Exemplo de leitura de uma mensagem que já foi validado neste computador:

```bash
docker compose exec ros1-bridge bash -c \
  'source /opt/ros/humble/setup.bash; source /ros-humble-ros1-bridge/install/local_setup.bash; ros2 topic echo /battery_voltage std_msgs/msg/Float32 --once'
```

O log do serviço `rosserial` deve mostrar `Waiting for socket connections on
port 11411` e, depois que a base conectar, os publishers configurados pelo
gateway.

## Configuração

Os valores ativos ficam em `.env`; use `.env.example` como referência. Se o IP
da interface mudar, atualize `MOBI_HOST_IP`. O firmware/gateway deve conectar
ao IP `10.10.10.1` na porta `11411`, e as aplicações ROS 2 precisam usar o
mesmo `ROS_DOMAIN_ID`.

Os serviços usam `network_mode: host`, necessário no ROS 1 para que master,
nós e gateway consigam abrir conexões de retorno entre si. Nenhum acesso
privilegiado ou dispositivo serial USB é necessário para esta ligação
Ethernet.

## Parar

```bash
docker compose down
```

Para abrir shells já com o ambiente carregado:

```bash
docker compose exec ros-master bash -c \
  'source /opt/ros/noetic/setup.bash; exec bash'
docker compose exec ros1-bridge bash -c \
  'source /opt/ros/humble/setup.bash; source /ros-humble-ros1-bridge/install/local_setup.bash; exec bash'
```

O bridge cobre os pares de mensagens padrão presentes em ROS 1 Noetic e ROS 2
Humble. Mensagens próprias do firmware exigem que o pacote `_msgs` equivalente
seja adicionado e compilado para os dois lados antes de recompilar o bridge.

## Controle pelo joystick

O serviço `joystick` usa o pacote ROS 1 `joy` para ler o controle e o nó
`mobi_joy_teleop` para converter `sensor_msgs/Joy` em `geometry_msgs/Twist`.
A configuração ativa foi feita para o controle Xbox 360 detectado em
`/dev/input/js0`:

- analógico direito vertical: avanço/ré;
- analógico direito horizontal: giro;
- nenhum botão é necessário para o movimento normal;
- `RB` + analógico direito: modo turbo enquanto `RB` permanecer pressionado;
- velocidade normal: até `0,25 m/s` e `0,60 rad/s`;
- velocidade turbo: até `0,50 m/s` e `1,20 rad/s`.

Ao soltar o analógico, o nó publica velocidade zero. A zona morta de 12% evita
movimento causado por pequenas oscilações do controle. Um watchdog também
publica zero em até 250 ms caso o joystick seja desconectado ou deixe de enviar
dados. Para acompanhar os dados durante um teste com as rodas suspensas ou com
espaço livre ao redor do robô:

```bash
docker compose logs -f joystick
docker compose exec ros-master bash -c \
  'source /opt/ros/noetic/setup.bash; rostopic echo /joy'
docker compose exec ros-master bash -c \
  'source /opt/ros/noetic/setup.bash; rostopic echo /cmd_vel'
```

Se o controle for reconectado com outro nome de dispositivo, atualize
`JOY_DEVICE` no `.env` e recrie somente o serviço:

```bash
docker compose up -d --force-recreate joystick
```

## Sensores: Ouster, D435i, T265 e D455

Cada sensor roda como um serviço ROS 2 independente (perfil do Compose), ligado
via `network_mode: host` e `ipc: host` no mesmo `ROS_DOMAIN_ID` da base — assim
tudo aparece nos mesmos `ros2 topic list`, com ou sem esses containers de pé.
Suba/desligue qualquer combinação sem afetar os demais:

```bash
./mobi.sh network                 # uma vez: configura a Ethernet do Ouster
./mobi.sh up ouster,d435i,t265     # sobe a base + os sensores escolhidos
./mobi.sh up d435i                 # so a D435i, por exemplo
./mobi.sh stop t265                # desliga so a T265
./mobi.sh check base,ouster,d435i,t265   # confere se ha dado real em cada topico
./mobi.sh devices                  # lista as RealSense e o Ouster vistos pelo host
```

Tópicos publicados (com `ROS_DOMAIN_ID` igual em todos os processos ROS 2 que
forem consumir os dados):

- Ouster OS-0-128: `/ouster/points`, `/ouster/imu`, `/ouster/scan`
- D435i: `/d435i/color/image_raw`, `/d435i/aligned_depth_to_color/image_raw`, `/d435i/imu` (se `D435I_ENABLE_IMU=true`)
- T265: `/t265/pose/sample` (200 Hz), `/t265/imu`, `/t265/fisheye1|2/image_raw`
- D455 (quando conectada): mesmos tópicos da D435i em `/d455/...`

### Rede do Ouster

O Ouster fica na Ethernet dedicada `OUSTER_INTERFACE` (padrao `enp2s0`), com
`10.5.5.1/24` + link-local `169.254.1.1/16` no host — sem depender de DHCP. O
`./mobi.sh up` descobre o sensor por mDNS automaticamente; `OUSTER_HOSTNAME`
no `.env` e usado como fallback.

### D435i + T265 simultâneas: limites de hardware descobertos

Rodando a D435 e a T265 ao mesmo tempo neste computador, dois limites reais
apareceram e já estão contornados por padrão:

1. **`usbfs_memory_mb` do kernel** (padrão 16 MB) é baixo demais para os
   buffers USB de duas RealSense simultâneas — causa erros libusb
   (`Resource temporarily unavailable`). Corrigido no host (nao no container):
   ```bash
   echo 1000 | sudo tee /sys/module/usbcore/parameters/usbfs_memory_mb
   # persistente:
   echo 'options usbcore usbfs_memory_mb=1000' | sudo tee /etc/modprobe.d/realsense-usbfs.conf
   ```
2. **Pico de corrente do emissor IR da D435/D455**: com a T265 puxando USB ao
   mesmo tempo, ligar o emissor infravermelho derruba o módulo de
   profundidade (`Depth stream start failure`, erro de hardware). Por isso
   `D435I_ENABLE_INFRA` e `D435I_ENABLE_EMITTER` (idem para D455) vêm
   **desligados por padrão** no `.env`. Só ligue algum dos dois se for usar a
   câmera RealSense sozinha, sem a T265 ativa ao mesmo tempo.

### Buffer UDP do kernel (Ouster)

O driver do Ouster pede um `SO_RCVBUF` de 1 MB; o padrão do Linux
(`net.core.rmem_max=212992`) é menor e pode causar perda de pacotes na nuvem
de pontos sob carga. Ajustado no host:

```bash
sudo sysctl -w net.core.rmem_max=8388608 net.core.rmem_default=8388608
# persistente:
printf 'net.core.rmem_max=8388608\nnet.core.rmem_default=8388608\n' | sudo tee /etc/sysctl.d/99-ouster-udp.conf
sudo sysctl --system
```

### Gravar bags

```bash
./mobi.sh bag [NOME] [base,ouster,d435i,t265,d455]   # grava por grupo de sensor
./mobi.sh bag-info NOME
```

Cada grupo grava um conjunto de tópicos já mapeado (RGB+depth da câmera,
pose+imu da T265, nuvem+imu do Ouster, telemetria da base). Para escolher os
tópicos manualmente:

```bash
# Adiciona topicos extras aos grupos selecionados
BAG_TOPICS="/meu_topico" ./mobi.sh bag NOME ouster,t265

# Grava só os tópicos listados, ignorando os grupos
BAG_TOPICS="/odom,/ouster/points,/t265/pose/sample" BAG_TOPICS_ONLY=true ./mobi.sh bag NOME
```

A gravação espera cada tópico obrigatório publicar pelo menos uma mensagem
real antes de começar (evita bag vazia por sensor que ainda não subiu), grava
em MCAP e finaliza corretamente com `Ctrl+C` (ou `docker stop`).

Para uma duração fixa (encerra sozinha, sem precisar de `Ctrl+C`):

```bash
BAG_DURATION_SEC=10 ./mobi.sh bag NOME base,ouster,d435i,t265
```

### Metadados da sessão (dataset)

Toda gravação (terminal ou painel web) gera automaticamente, dentro da
própria pasta da bag, sem precisar fazer nada:

- `metadata.json` — schema versionado com sensores gravados, tópicos/tipos/
  contagem de mensagens (lidos do `metadata.yaml` do próprio rosbag2, não
  suposição), horário de início/fim, e o **commit git** (`mobi/` agora é um
  repositório git) que gerou aquela sessão, com um aviso se havia alterações
  não commitadas na hora da gravação (`git_dirty`). Sem repo git disponível,
  cai num fingerprint sha256 dos arquivos de config como fallback.
- `README.md` — a mesma informação em texto legível, pronta pra acompanhar
  o dataset quando for compartilhado.

Campos opcionais (operador/local/condições/notas) via terminal:

```bash
MOBI_OPERATOR="seu nome" MOBI_LOCATION="predio X" MOBI_CONDITIONS="indoor" \
  MOBI_NOTES="obs livre" ./mobi.sh bag NOME [grupos]
```

ou pelo painel web (`./mobi.sh dashboard`), que tem os mesmos campos no
formulário de gravação. A geração de metadata é *best-effort*: se falhar por
qualquer motivo, a bag em si nunca é invalidada (o aviso vai só pro log).

**Pipeline completo de dataset** (extração, validação, preview e catálogo já
prontos — ver seções abaixo). Falta só versionamento/distribuição de fato,
que depende de onde os dados vão ficar hospedados.

### Tamanho da bag e compressão

Com D435i+Ouster+T265+base ligados, a gravação bruta (sem compressão) fica em
torno de **~80 MB/s (~5 GB/min, ~290 GB/h)** — inviável para coletas longas.
Por isso a gravação usa compressão nativa do MCAP (**Zstd por chunk, sem
perda**: os bytes voltam bit a bit idênticos na leitura) por padrão, definida
em `config/mcap-compression.yaml`. Em teste real (Ouster+T265, 15s): 573 MiB
sem compressão → 141 MiB com — **~4x menor**. Para desligar (ex.: debug):

```bash
BAG_STORAGE_CONFIG="" ./mobi.sh bag NOME [grupos]
```

### Reproduzir bags

```bash
./mobi.sh play NOME                       # rate 1.0, publica /clock
BAG_PLAY_RATE=0.5 ./mobi.sh play NOME     # meia velocidade
BAG_PLAY_LOOP=true ./mobi.sh play NOME    # em loop
./mobi.sh play NOME --topics /ouster/points   # argumentos extras vao direto pro ros2 bag play
```

Finaliza corretamente com `Ctrl+C`. **Atenção:** se os sensores ao vivo (`ouster`,
`d435i`, `t265`) ainda estiverem no ar, a reprodução publica nos *mesmos*
tópicos e os dados se misturam (a frequência aparente dobra). Para avaliar a
bag isoladamente, pare os sensores antes:

```bash
./mobi.sh stop ouster,d435i,t265
./mobi.sh play NOME
```

## Extração para formatos abertos (sem precisar de ROS)

```bash
./mobi.sh extract NOME                        # tudo que tiver tipo suportado
./mobi.sh extract NOME --images-format jpg    # PNG e o padrao (sem perda)
./mobi.sh extract NOME --topics /ouster/points,/d435i/color/image_raw
```

Despacha por **tipo** de mensagem (funciona pra qualquer sessao gravada com
`config/topics.yaml`, sem lista de sensores hardcoded):

| Tipo ROS | Vira |
|---|---|
| `sensor_msgs/Image` | PNG (ou JPG) por frame, `images/<topico>/NNNNNN_<timestamp_ns>.png` |
| `sensor_msgs/PointCloud2` | PCD binario por frame, `pointclouds/<topico>/` |
| `sensor_msgs/Imu` | CSV, `imu/<topico>.csv` |
| `nav_msgs/Odometry` | TUM (formato padrao de SLAM) + CSV, `trajectories/<topico>.tum/.csv` |
| `sensor_msgs/CameraInfo` | YAML de calibracao (K/D/R/P), `camera_info/<topico>.yaml` |
| `/tf_static` | `extrinsics.yaml` com todas as transformacoes estaticas |

Um `manifest.json` lista o que foi extraido de cada tópico. **Importante**: o
PointCloud2 é reempacotado campo a campo (não é um memcpy do buffer cru) —
drivers como o do Ouster deixam padding entre campos que o formato PCD não
representa; copiar direto geraria nuvens com os campos desalinhados.

## Validação, preview e catálogo

```bash
./mobi.sh validate NOME   # validation_report.json
./mobi.sh preview NOME    # preview/thumbnail.jpg, contact_sheet.jpg, trajectory.png, pointcloud_top_view.png
./mobi.sh catalog         # escaneia bags/*/ inteiro -> bags/index.html + bags/catalog.json
./mobi.sh process NOME    # as 3 acima em sequencia (fluxo normal pos-gravacao)
```

**Validação** (`validate_bag.py`) lê só os timestamps que o próprio rosbag2
gravou (não decodifica payload — rápido mesmo com bag de imagem/nuvem
grande) e sinaliza:
- **gaps de tempo** suspeitos (>4x o intervalo mediano do tópico);
- **taxa observada muito abaixo da esperada** (`rate_hz` em `config/topics.yaml`,
  <60% do esperado);
- **tópico obrigatório do grupo gravado ausente ou vazio** na bag.

Status final `ok`/`warning`/`error` conforme a gravidade do que foi achado.

**Preview** (`preview_bag.py`, só cv2/numpy, sem dependência nova): thumbnail
e contact-sheet a partir de uma câmera de cor (evita pegar profundidade/infra
por engano), trajetória vista de cima a partir de uma odometria, e um mapa de
densidade visto de cima acumulando todos os frames de uma nuvem de pontos —
dá pra decidir se vale baixar a sessão inteira sem abrir a bag.

**Catálogo** (`build_catalog.py`) gera `bags/index.html` (com os
thumbnails/status de validação de cada sessão) e `bags/catalog.json`
(mesma informação, legível por máquina). Só referências relativas — abre
local ou funciona igual depois de subido pra qualquer lugar (Drive, servidor,
bucket), sem precisar mudar nada.

## TF tree e visualização (RViz2/rqt em container)

O pacote `ros2_ws/src/mobi_description` tem o URDF do robô (`urdf/mobi.urdf.xacro`)
e sobe um `robot_state_publisher` que publica os TFs estáticos ligando
`base_link` a cada sensor. O serviço `description` roda sempre (junto com
`./mobi.sh up`), então o `/tf_static` já sai completo mesmo sem abrir nenhuma
tela — inclusive nas bags gravadas.

**Medidas assumidas (provisórias):** caixa 700x500x400mm, 4 rodinhas nos
cantos, Ouster no topo quase na frente, D435i+T265 na face frontal, D455
suspensa por uma haste de 550mm no topo, um TOF por face lateral. Ajuste as
`xacro:property` no topo do `.xacro` quando tiver as medidas definitivas —
os nomes dos links (que é filho de quem) não devem precisar mudar.

Pontos de encaixe de cada sensor no `base_link` (nomes de frame confirmados
rodando de verdade, não suposição):

| Sensor | Link de encaixe | Observação |
|---|---|---|
| Ouster | `os_sensor` | driver publica `os_sensor` → `os_lidar`/`os_imu` |
| D435i  | `d435i_link` | driver publica `d435i_link` → frames óticos |
| T265   | `t265_mount` → `odom_frame` | ver nota abaixo |
| D455   | `d455_link` (no topo do `mast_link`) | ainda não conectada |
| TOFs   | `tof3d_front_link`/`_left`/`_rear`/`_right` | confirmado no frame_id da ponte |

**Nota sobre a T265:** o driver dela publica sua própria árvore estática com
raiz em `t265_pose_frame` (não em `t265_link` — esse já é filho interno do
driver). A única aresta livre é `odom_frame → t265_pose_frame`, publicada
dinamicamente pelo driver conforme o VIO se move. Por isso o URDF fecha
`base_link → t265_mount → odom_frame` (identidade), assumindo que a câmera liga
exatamente na pose do mount — na prática, é a pose da T265 evoluindo a partir
dali que aparece no RViz.

```bash
./mobi.sh viz    # RViz2 em container, com TF/RobotModel/PointCloud2/Imagem/Pose pré-configurados
./mobi.sh rqt    # so rqt_image_view, avulso
```

Sobe com aceleração de GPU (NVIDIA detectada neste PC via `nvidia-container-toolkit`;
sem GPU dedicada, defina `GUI_RUNTIME=runc` no `.env`). Usa `network_mode: host`
+ `ipc: host` (mesmo `ROS_DOMAIN_ID`) e X11 do host via `DISPLAY`/`XAUTHORITY` —
não precisa configurar nada manualmente além de já estar numa sessão gráfica
local. Se aparecer erro de autorização do X11, confirme que `$DISPLAY` e
`$XAUTHORITY` estão exportados no seu shell antes de rodar `./mobi.sh viz`
(em sessões GDM/Wayland, `XAUTHORITY` costuma ser algo como
`/run/user/1000/gdm/Xauthority`, não `~/.Xauthority`).

**Notebook com GPU híbrida (AMD/Intel integrada + NVIDIA dedicada):** o
serviço `gui` já define `__NV_PRIME_RENDER_OFFLOAD=1` e
`__GLX_VENDOR_LIBRARY_NAME=nvidia` para forçar o RViz2 a renderizar na NVIDIA
via PRIME. Sem isso, em `prime-select on-demand` (padrão Ubuntu), o contexto
GL fica inconsistente entre as duas GPUs e o RViz2 trava com `SIGSEGV` depois
de alguns segundos (sintoma: `amdgpu: drmGetDevice2 failed` no log).

**Atenção com QoS:** PointCloud2/Image/Odometry desses sensores publicam com
`Best Effort` (perfil de dado de sensor). O `mobi.rviz` já vem com essa
política setada por tópico; se adicionar um novo display, configure a mesma
coisa em "Topic → Reliability Policy", senão o RViz não recebe nada (fica
subscrito, mas com QoS incompatível, e nenhum aviso aparece na tela — só nos
logs do publisher).

**Daemon do `ros2cli`:** ele e compartilhado entre TODOS os containers (network/ipc
host) e pode ficar num estado invalido depois de muitos containers subindo e
caindo (erro tipico: `RuntimeError: !rclpy.ok()`). Os scripts e healthchecks
deste projeto sempre passam o tipo da mensagem explicitamente para o
`ros2 topic echo` (evita depender do daemon); se algum comando `ros2` seu
travar com esse erro, rode `ros2 daemon stop` dentro do container.

## Painel web (coleta, estado dos sensores, escolha de tópicos)

```bash
./mobi.sh dashboard
```

Abre em `http://localhost:8080` (porta em `DASHBOARD_PORT` no `.env`). Mostra,
ao vivo, a taxa de cada tópico configurado em `config/topics.yaml` (verde =
publicando, amarelo = atrasado, cinza = sem dado), deixa escolher quais
grupos/tópicos gravar (com um campo de tópicos extra, sem precisar editar
nada), mostra o tamanho da bag crescendo em tempo real durante a gravação, e
lista as bags já gravadas.

`config/topics.yaml` é a fonte única de verdade dos grupos/tópicos — usada
tanto pelo painel quanto por `record-bag.sh`/`check-sensors.sh` (via
`scripts/topics_config.py`). Para adicionar um tópico nunca precisa mexer em
bash: só editar o YAML.

O painel reusa o mesmo `record-bag.sh` do terminal (mesma espera por dado
real, mesmo MCAP, mesmo encerramento gracioso) — só troca a interface.

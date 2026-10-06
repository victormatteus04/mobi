# Mobi: operação (Jetson Thor)

Guia rápido para ligar, mapear e navegar. Tudo roda em Docker na Thor
(`~/akcit/mobi`, branch `jazzy`); o notebook só visualiza.

```text
PS4 (Bluetooth) ─► teleop ─┐
                           ├─► mobi_cmd_mux ─► base (ROS 1 / rosserial)
Nav2 ─► ponte (rosbridge) ─┘   joystick > Nav2 (só com L1) > parado
Ouster ─► SLAM (RTAB-Map, ICP) ─► mapa + localização ─► Nav2
```

## 1. Ligar

Ao ligar o robô, sobem sozinhos: base (ROS 1), controle, ponte, Ouster e
descrição do robô. **SLAM e Nav2 não sobem sozinhos** (seção 3 e 4).

1. Ligue o controle PS4 (botão PS). Ele reconecta sozinho.
2. Confira (na Thor: `ssh jetson-31500@192.168.7.2`, `cd ~/akcit/mobi`):
   ```bash
   ./mobi.sh status     # 8 serviços "Up"; joystick e ros-master "healthy"
   ```

## 2. Controle PS4

| Comando | Ação |
|---|---|
| Analógico direito ↑/↓ | frente / ré |
| Analógico esquerdo ←/→ | girar |
| R1 segurado | turbo (0,50 m/s; normal 0,25 m/s) |
| **L1 segurado** | **libera o Nav2 a mover o robô.** Soltou, parou. |

O analógico sempre tem prioridade sobre o Nav2. Controle desconectado = robô parado.

## 3. Mapear

```bash
./mobi.sh map lab        # mapa novo em maps/lab.db (não sobrescreve um existente)
```
Dirija **devagar**, sem turbo, gire com calma, passe de novo por lugares já
vistos e **termine onde começou**. Depois:
```bash
./mobi.sh slam-stop      # salva o mapa
```

## 4. Navegar sozinho

1. Coloque o robô **onde o mapeamento começou**, virado para o mesmo lado.
2. Suba a localização e o Nav2:
   ```bash
   ./mobi.sh localize lab
   ./mobi.sh nav
   ```
3. No RViz (seção 5): se o robô não estiver na posição certa no mapa, use
   **2D Pose Estimate**. Depois clique em **2D Goal Pose** no destino.
4. **Segure o L1** para o robô andar. Solte para parar a qualquer momento.

Para encerrar: `./mobi.sh slam-stop` (para Nav2 e localização).

## 5. Ver no notebook (RViz)

Uma vez: no `.env` do notebook, `MOBI_ZENOH_CONNECT=tcp/192.168.7.2:7447`
(IP da Thor). Depois, no notebook:
```bash
./mobi.sh viz
```
Mostra mapa, trajetória, robô, scan, obstáculos, costmaps e plano do Nav2.
O "Mapa 3D" vem desligado (pesado no Wi-Fi).

## 6. Problemas comuns

| Sintoma | O que fazer |
|---|---|
| Robô não responde ao controle | Botão PS no controle; `./mobi.sh logs joystick` |
| Sem dados do Ouster | `./mobi.sh logs ouster`; cabo na porta RJ45 da Thor |
| Base sem `/odom` | `./mobi.sh logs rosserial`; cabo USB-Ethernet da base |
| RViz vazio no notebook | Thor e notebook na mesma rede; IP no `MOBI_ZENOH_CONNECT` |
| Nav2 não anda | L1 segurado? `./mobi.sh logs nav` |
| Mapa "girado" em relação ao robô | `./mobi.sh check-yaw` (dirigir reto p/ frente) |
| Reiniciar tudo | `./mobi.sh down` e depois `./mobi.sh up` |

## 7. Ajustes

- Parâmetros do SLAM: `ros2_ws/src/mobi_bringup/config/slam_icp.yaml`
- Parâmetros do Nav2: `ros2_ws/src/mobi_bringup/config/nav2_params.yaml`
- Controle: `config/mobi-ps4.config.yaml`
- Montagem dos sensores (URDF): `ros2_ws/src/mobi_description/urdf/mobi.urdf.xacro`

YAML e launch valem ao recriar o serviço (`./mobi.sh map|localize|nav`), sem
rebuild. Mudou Dockerfile ou URDF: `docker compose build zenoh-router ros-master`
e `./mobi.sh up`.

## 8. Preparar uma Thor nova (uma vez)

```bash
gh repo clone victormatteus04/mobi ~/akcit/mobi -- -b jazzy && cd ~/akcit/mobi
cp .env.example .env     # ajuste OUSTER_INTERFACE (ip -br link), JOY_CONFIG=mobi-ps4.config.yaml
sudo OUSTER_INTERFACE=<interface> ./scripts/setup-ouster-network.sh
printf 'net.core.rmem_max=8388608\nnet.core.rmem_default=8388608\n' | sudo tee /etc/sysctl.d/99-ouster-udp.conf && sudo sysctl --system
docker compose build zenoh-router ros-master   # ~5 min
./mobi.sh up ouster
```
Parear o PS4: `bluetoothctl` → `scan on` → (PS + Share no controle) →
`pair <MAC>` → `trust <MAC>` → `connect <MAC>`.

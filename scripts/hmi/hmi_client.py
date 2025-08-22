#!/usr/bin/env python3
"""
CSTR HMI (Human-Machine Interface) – Modbus-TCP Client (MODIFIED)
------------------------------------------------------------------
* [수정] 서버로부터 노이즈가 포함된 측정값(Sensed Value)을 수신하여 표시
* [수정] Modbus 통신을 float -> scaled integer (x100) 방식으로 변경
* 0.5 s 주기로 서버(시뮬레이터)에서 상태값 읽어 그래프에 표시
* 슬라이더로 Set-point(유량·공급농도·냉각수 목표온도) 변경
* 최초 연결 시 점검용 데이터 1회 출력 + 10 s 마다 현재값 출력
"""

# ──────────────────────────────────────────────────────
# 0. 라이브러리
# ──────────────────────────────────────────────────────
import time
import threading
from collections import deque
import warnings

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider

from pymodbus.client import ModbusTcpClient

import koreanize_matplotlib  # 이 한 줄만 추가하면 됩니다! (한글 쓰게)

# ──────────────────────────────────────────────────────
# 1. Modbus 주소 상수 (서버와 동일)
# [변경 2-1] 서버와 동기화된 새 주소 사용
# ──────────────────────────────────────────────────────
# --- Write (HMI -> Server) ---
HR_ADDR_Q_SET_0       = 0
HR_ADDR_CAF_SET_1     = 1
HR_ADDR_TC_SET_2      = 2
# --- Read (Server -> HMI) ---
HR_ADDR_TC_ACTUAL_3   = 3
# HMI는 노이즈가 포함된 '측정(Sensed)' 값을 읽어옴
HR_ADDR_REACTOR_T_SENSED_6 = 6
HR_ADDR_REACTOR_CA_SENSED_7 = 7

MODBUS_UNIT_ID      = 1
SCALING_FACTOR      = 100.0

# ──────────────────────────────────────────────────────
# 2. scaled integer - float 변환 유틸
# [변경 2-2] 통신 방식 변경에 따른 유틸리티 함수 교체
# ──────────────────────────────────────────────────────
def val_to_int(value: float) -> int:
    """Float 값을 스케일링하여 정수로 변환"""
    return int(value * SCALING_FACTOR)

def int_to_val(reg_value: int) -> float:
    """스케일링된 정수를 Float 값으로 변환"""
    return float(reg_value) / SCALING_FACTOR

# ──────────────────────────────────────────────────────
# 3. 그래프 설정 파라미터 (변경 없음)
# ──────────────────────────────────────────────────────
WINDOW_SPAN_SEC      = 120
UI_REFRESH_PERIOD_S  = 0.5
# ──────────────────────────────────────────────────────
# 4. matplotlib Figure + Axes 레이아웃 및 선·슬라이더 정의 (수정안)
# ──────────────────────────────────────────────────────
# 4-0) Figure 생성
figure = plt.figure(figsize=(12, 8), constrained_layout=True)

# 4-1) GridSpec 설정
#      아래쪽 3개 그래프와 슬라이더의 너비를 맞추기 위해 width_ratios를 [2, 1, 1] 정도로 조정
#      슬라이더 높이를 위해 height_ratios의 마지막 값을 1.5 정도로 조정
grid = figure.add_gridspec(nrows=3, ncols=3, height_ratios=[5, 5, 1.5], width_ratios=[1, 1, 1])

# 4-2) 그래프 영역(Axes) 생성 (기존과 동일)
ax_temp_reactor   = figure.add_subplot(grid[0, 0:2])
ax_conc_reactor   = figure.add_subplot(grid[0, 2])
ax_flowrate_in    = figure.add_subplot(grid[1, 0])
ax_feed_conc      = figure.add_subplot(grid[1, 1])
ax_coolant_actual = figure.add_subplot(grid[1, 2])

# 4-3) x-lim, 그리드 기본 설정
for ax in (ax_temp_reactor, ax_conc_reactor, ax_flowrate_in, ax_feed_conc, ax_coolant_actual):
    ax.set_xlim(0, WINDOW_SPAN_SEC)
    ax.grid(True, alpha=0.3)
# 4-4) y-lim 기본 범위
ax_temp_reactor.set_ylim(280, 450); ax_conc_reactor.set_ylim(0.0, 1.2)
ax_flowrate_in.set_ylim(50, 150); ax_feed_conc.set_ylim(0.5, 1.5)
ax_coolant_actual.set_ylim(280, 320)
# 4-5) 선 객체(Line2D) 정의
line_temp, = ax_temp_reactor.plot([], [], "r-", lw=2.5, label="Reactor T (반응기 온도)[K]")
line_conc, = ax_conc_reactor.plot([], [], "b-", lw=2.0, label="Ca 반응기 내 농도 [mol/m³]")
line_flow, = ax_flowrate_in.plot([], [], "g-", lw=2.0, label="q_in (주입량)[L/s]")
line_feed, = ax_feed_conc.plot([], [], "m-", lw=2.0, label="Caf (유입물 내 농도)")
line_cool, = ax_coolant_actual.plot([], [], "c-", lw=2.0, label="Tc_actual 냉각수 온도 [K]")
# 4-6) 범례
for ax in (ax_temp_reactor, ax_conc_reactor, ax_flowrate_in, ax_feed_conc, ax_coolant_actual):
    ax.legend(loc="upper left", fontsize=9)

# 4-7) 슬라이더용 축(Axes)을 메인 GridSpec의 마지막 행에 직접 배치 (subgridspec 삭제)
slider_ax_q   = figure.add_subplot(grid[2, 0])
slider_ax_caf = figure.add_subplot(grid[2, 1])
slider_ax_tc  = figure.add_subplot(grid[2, 2])

# 4-9) 슬라이더 정의 (labelpad 인자 삭제)
slider_flowrate = Slider(
    ax=slider_ax_q,
    label="Flow q_in (주입량 설정) [L/s]",
    valmin=50, valmax=150,
    valinit=100, valstep=1,
    valfmt="%0.0f"
)

# 시나리오 상 농도 설정은 제외하는 편이 적절할 듯 함.
# 시뮬레이터로서는 적절.
slider_feedconc = Slider(
    ax=slider_ax_caf,
    label="Feed Caf (유입물 내 농도 설정) [mol/m³]",
    valmin=0.5, valmax=1.5,
    valinit=1.0, valstep=0.05,
    valfmt="%0.2f"
)
slider_coolset = Slider(
    ax=slider_ax_tc,
    label="Coolant Tc_set (냉각수 온도 설정) [K]",
    valmin=295, valmax=305,
    valinit=300, valstep=1,
    valfmt="%0.0f"
)

# 4-9) 생성된 슬라이더의 레이블 위치를 직접 조정 (기존과 동일)
for slider in (slider_flowrate, slider_feedconc, slider_coolset):
    slider.label.set_position((0.5, 0.9))
# ──────────────────────────────────────────────────────
# 5. Modbus 클라이언트 연결
# ──────────────────────────────────────────────────────
client = ModbusTcpClient(host="127.0.0.1", port=5020, timeout=1.0)
if not client.connect():
    warnings.warn("Modbus 서버에 연결되지 않았습니다. IP/포트 확인!")
    raise SystemExit
print("[HMI] Connected to Modbus server 127.0.0.1:5020")

# [변경 2-3] 쓰기 헬퍼: Set-point를 scaled int로 전송
def write_setpoint_scaled(hr_address: int, value: float) -> None:
    client.write_register(
        address=hr_address,
        value=val_to_int(value),
        slave=MODBUS_UNIT_ID,
    )

slider_flowrate.on_changed(lambda v: write_setpoint_scaled(HR_ADDR_Q_SET_0, v))
slider_feedconc.on_changed(lambda v: write_setpoint_scaled(HR_ADDR_CAF_SET_1, v))
slider_coolset.on_changed(lambda v: write_setpoint_scaled(HR_ADDR_TC_SET_2,  v))

write_setpoint_scaled(HR_ADDR_Q_SET_0, slider_flowrate.val)
write_setpoint_scaled(HR_ADDR_CAF_SET_1, slider_feedconc.val)
write_setpoint_scaled(HR_ADDR_TC_SET_2, slider_coolset.val)

# ──────────────────────────────────────────────────────
# 6. 서버-값 읽기 헬퍼
# ──────────────────────────────────────────────────────
def read_scaled_int(hr_address: int) -> float:
    """1-word 읽어서 float 변환 (읽기 실패 시 np.nan)"""
    response = client.read_holding_registers(
        address=hr_address, count=1, slave=MODBUS_UNIT_ID,
    )
    return int_to_val(response.registers[0]) if response else np.nan

# ──────────────────────────────────────────────────────
# 7. 히스토리 버퍼 (deque) 초기화
# ──────────────────────────────────────────────────────
max_points = int(WINDOW_SPAN_SEC / UI_REFRESH_PERIOD_S)
history: dict[str, deque] = {
    key: deque(maxlen=max_points)
    for key in ("time_s", "reactor_T", "reactor_Ca",
                "coolant_Tc", "flowrate_q", "feed_Caf")
}

# [변경 2-3] 수정된 주소와 함수로 최초 샘플 읽기
initial_T       = read_scaled_int(HR_ADDR_REACTOR_T_SENSED_6)
initial_Ca      = read_scaled_int(HR_ADDR_REACTOR_CA_SENSED_7)
initial_Tc_act  = read_scaled_int(HR_ADDR_TC_ACTUAL_3)

history["time_s"].append(0.0)
history["reactor_T"].append(initial_T)
history["reactor_Ca"].append(initial_Ca)
history["coolant_Tc"].append(initial_Tc_act)
history["flowrate_q"].append(slider_flowrate.val)
history["feed_Caf"].append(slider_feedconc.val)

# 초기 선/축 갱신 (변경 없음)
line_temp.set_data(history["time_s"], history["reactor_T"])
line_conc.set_data(history["time_s"], history["reactor_Ca"])
line_cool.set_data(history["time_s"], history["coolant_Tc"])
line_flow.set_data(history["time_s"], history["flowrate_q"])
line_feed.set_data(history["time_s"], history["feed_Caf"])
for axis in (ax_temp_reactor, ax_conc_reactor, ax_flowrate_in, ax_feed_conc, ax_coolant_actual):
    axis.relim(); axis.autoscale_view()
figure.canvas.draw()

print(
    f"[HMI] INITIAL → T={initial_T:6.1f} K, Ca={initial_Ca:5.3f}, "
    f"Tc_act={initial_Tc_act:6.1f} K, q={slider_flowrate.val:6.1f}, "
    f"Caf={slider_feedconc.val:4.2f}"
)

# ──────────────────────────────────────────────────────
# 8. 데이터-갱신 스레드
# ──────────────────────────────────────────────────────
def ui_update_loop() -> None:
    program_start_time = time.perf_counter()
    last_console_print = program_start_time

    while plt.fignum_exists(figure.number):
        loop_start = time.perf_counter()

        # [변경 2-3] 수정된 주소와 함수로 서버에서 값 읽기
        coolant_Tc   = read_scaled_int(HR_ADDR_TC_ACTUAL_3)
        reactor_T    = read_scaled_int(HR_ADDR_REACTOR_T_SENSED_6) # <- Sensed
        reactor_Ca   = read_scaled_int(HR_ADDR_REACTOR_CA_SENSED_7) # <- Sensed
        flowrate_q   = read_scaled_int(HR_ADDR_Q_SET_0)
        feed_Caf     = read_scaled_int(HR_ADDR_CAF_SET_1)

        # 이하 로직은 대부분 변경 없음
        elapsed_time = loop_start - program_start_time
        for key, value in (
            ("time_s",      elapsed_time), ("reactor_T",   reactor_T),
            ("reactor_Ca",  reactor_Ca), ("coolant_Tc",  coolant_Tc),
            ("flowrate_q",  flowrate_q), ("feed_Caf",    feed_Caf),
        ):
            history[key].append(value)

        line_temp.set_data(history["time_s"], history["reactor_T"])
        line_conc.set_data(history["time_s"], history["reactor_Ca"])
        line_cool.set_data(history["time_s"], history["coolant_Tc"])
        line_flow.set_data(history["time_s"], history["flowrate_q"])
        line_feed.set_data(history["time_s"], history["feed_Caf"])

        if elapsed_time >= WINDOW_SPAN_SEC:
            for axis in (ax_temp_reactor, ax_conc_reactor, ax_flowrate_in, ax_feed_conc, ax_coolant_actual):
                axis.set_xlim(elapsed_time - WINDOW_SPAN_SEC, elapsed_time)

        for axis in (ax_temp_reactor, ax_conc_reactor, ax_flowrate_in, ax_feed_conc, ax_coolant_actual):
            axis.relim(); axis.autoscale_view(scalex=False)

        if loop_start - last_console_print >= 10.0:
            print(
                f"[HMI] t={elapsed_time:6.1f}s → "
                f"T={reactor_T:6.1f} K, Ca={reactor_Ca:5.3f}, "
                f"Tc_act={coolant_Tc:6.1f} K, q={flowrate_q:6.1f}, "
                f"Caf={feed_Caf:4.2f}"
            )
            last_console_print = loop_start

        figure.canvas.draw_idle()
        loop_elapsed = time.perf_counter() - loop_start
        time.sleep(max(0.01, UI_REFRESH_PERIOD_S - loop_elapsed))

threading.Thread(
    target=ui_update_loop, daemon=True, name="HMI_UpdateThread"
).start()

# ──────────────────────────────────────────────────────
# 9. 블로킹 show() (창 닫을 때까지 대기)
# ──────────────────────────────────────────────────────
try:
    plt.show(block=True)
finally:
    client.close()
    print("[HMI] Window closed, client disconnected")

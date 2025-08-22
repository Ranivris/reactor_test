#!/usr/bin/env python3
"""
Continuous-Stirred Tank Reactor (CSTR) -- Modbus-TCP Server (MODIFIED)
----------------------------------------------------------------------
* [수정] 실제 공정값(Real)에 노이즈를 더한 측정값(Sensed)을 HMI로 전송
* [수정] Modbus 통신을 float -> scaled integer (x100) 방식으로 변경
* 공정 동적 모델: 발열 1차 반응이 있는 CSTR
* 외부(PLC/HMI)로부터 받는 Set-point
    - 유량  q_in                [L/s]
    - 공급 농도 feed_conc_set   [mol/m³]
    - 냉각수 목표 온도 Tc_set   [K]
* 내부에서 계산해 주는 공정 상태값
    - 냉각수 실제 온도 Tc_actual [K] (1차 지연 모델)
    - 반응조 온도 reactor_T     [K]
    - 반응물 농도 reactor_Ca    [mol/m³]
* 0.1 s 주기로 모델 적분, 10 s 주기로 로그 출력 + 최초 1회 즉시 로그

pymodbus 3.9.x  (StartTcpServer = 동기 서버)
"""

# ──────────────────────────────────────────────────────
# 0. 표준 라이브러리 / 서드파티 의존성
# ──────────────────────────────────────────────────────
import time
import threading
import logging

import numpy as np
from scipy.integrate import solve_ivp

from pymodbus.server import StartTcpServer
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusSlaveContext,
    ModbusServerContext,
)

# ──────────────────────────────────────────────────────
# [변경 1-1] 시뮬레이션 파라미터 추가
# ──────────────────────────────────────────────────────
NOISE_STD_DEV_T_K  = 0.15   # 측정 온도값 노이즈 표준편차 [K]
NOISE_STD_DEV_CA   = 0.005  # 측정 농도값 노이즈 표준편차 [mol/m³]
SCALING_FACTOR     = 100.0  # 정수 통신을 위한 스케일 팩터

# ──────────────────────────────────────────────────────
# 1. Modbus 주소 매핑 (Holding Register 기준)
# [변경 1-2] 주소 재정의: float(2-word) -> int(1-word)에 맞게 순차적으로 변경
# ──────────────────────────────────────────────────────
# --- Client -> Server (Write) ---
HR_ADDR_Q_SET_0       = 0   # 유량 Set-point
HR_ADDR_CAF_SET_1     = 1   # 공급 농도 Set-point
HR_ADDR_TC_SET_2      = 2   # 냉각수 목표온도 Set-point

# --- Server -> Client (Read) ---
HR_ADDR_TC_ACTUAL_3   = 3   # 냉각수 실제 온도
HR_ADDR_REACTOR_T_REAL_4 = 4 # 반응조 실제 온도 (노이즈 없음)
HR_ADDR_REACTOR_CA_REAL_5 = 5 # 반응물 실제 농도 (노이즈 없음)
HR_ADDR_REACTOR_T_SENSED_6 = 6 # 반응조 측정 온도 (HMI용, 노이즈 포함)
HR_ADDR_REACTOR_CA_SENSED_7 = 7 # 반응물 측정 농도 (HMI용, 노이즈 포함)

MODBUS_UNIT_ID      = 1   # 슬레이브 ID

# ──────────────────────────────────────────────────────
# 2. 유틸리티: scaled integer <--> float 변환
# [변경 1-3] 통신 방식을 정수 스케일링으로 변경
# ──────────────────────────────────────────────────────
def val_to_int(value: float) -> int:
    """Float 값을 스케일링하여 정수로 변환"""
    return int(value * SCALING_FACTOR)

def int_to_val(reg_value: int) -> float:
    """스케일링된 정수를 Float 값으로 변환"""
    return float(reg_value) / SCALING_FACTOR

# ──────────────────────────────────────────────────────
# 3. Modbus 메모리맵(데이터스토어) 초기화
# ──────────────────────────────────────────────────────
slave_data_block = ModbusSequentialDataBlock(0, [0] * 120)
slave_context    = ModbusSlaveContext(hr=slave_data_block)
server_context   = ModbusServerContext(
    slaves={MODBUS_UNIT_ID: slave_context},
    single=False
)

def read_scaled_int_from_hr(address: int) -> float:
    """지정 Holding Register 1-word를 읽어 float으로 변환"""
    reg = server_context[MODBUS_UNIT_ID].getValues(3, address, count=1)[0]
    return int_to_val(reg)

def write_float_to_hr_scaled(address: int, value: float) -> None:
    """float 값을 스케일링된 정수로 변환하여 HR 1-word에 기록"""
    server_context[MODBUS_UNIT_ID].setValues(
        3, address, [val_to_int(value)]
    )

# ──────────────────────────────────────────────────────
# 4. CSTR 모델 파라미터 (전역 상수)
# ──────────────────────────────────────────────────────
CSTR_VOLUME_M3          = 100.0
LIQUID_DENSITY_KG_M3    = 1_000.0
HEAT_CAPACITY_KJ_KG_K   = 0.239
ARRHENIUS_E_OVER_R      = 8_750.0
ARRHENIUS_PREEXP        = 7.2e10
U_A_J_PER_S_K           = 5.0e4
REACTION_ENTHALPY_KJ_M  = -5.5e4
FEED_TEMPERATURE_K      = 350.0

# ──────────────────────────────────────────────────────
# 5. CSTR 모델: 미분방정식 RHS (변경 없음)
# ──────────────────────────────────────────────────────
def cstr_ode_rhs(
    time_sec: float, state_vec: np.ndarray, flow_rate_lps: float,
    coolant_temp_k: float, feed_concentration_molm3: float,
):
    concentration_Ca, temperature_T = state_vec

    # 반응 속도
    reaction_rate = (
        ARRHENIUS_PREEXP * np.exp(-ARRHENIUS_E_OVER_R / max(temperature_T, 1.0))
        * concentration_Ca
    )

    # 축적량 = 유입량 - 유출량 + 생성령 - 소모량
    dCa_dt = (
        flow_rate_lps / CSTR_VOLUME_M3 * (feed_concentration_molm3 - concentration_Ca)
        - reaction_rate
    )

    # 에너지 축적량 (Accumulation) = 에너지 유입량 (In) - 에너지 유출량 (Out) + 에너지 생성량 (Generation) - 에너지 소모량 (Consumption)
    dT_dt = (
        (flow_rate_lps / CSTR_VOLUME_M3) * (FEED_TEMPERATURE_K - temperature_T)
        - REACTION_ENTHALPY_KJ_M / (LIQUID_DENSITY_KG_M3 * HEAT_CAPACITY_KJ_KG_K) * reaction_rate
        + U_A_J_PER_S_K / (LIQUID_DENSITY_KG_M3 * HEAT_CAPACITY_KJ_KG_K * CSTR_VOLUME_M3)
        * (coolant_temp_k - temperature_T)
    )
    return [dCa_dt, dT_dt]

# ──────────────────────────────────────────────────────
# 6. 1-스텝 적분 도우미 (변경 없음)
# ──────────────────────────────────────────────────────
def integrate_one_time_step(
    current_state: np.ndarray, flow_rate_lps: float, coolant_temp_k: float,
    feed_concentration_molm3: float, time_step_sec: float = 0.1,
) -> np.ndarray:
    solution = solve_ivp(
        fun=cstr_ode_rhs, t_span=(0, time_step_sec), y0=current_state,
        args=(flow_rate_lps, coolant_temp_k, feed_concentration_molm3),
        method="Radau", rtol=1e-6, atol=1e-8,
    )
    return np.clip(solution.y[:, -1], a_min=[-1.0, -1.0], a_max=[1e5, 1e5])

# ──────────────────────────────────────────────────────
# 7. 시뮬레이션 루프 (백그라운드 스레드)
# ──────────────────────────────────────────────────────
def simulation_thread(
    integration_dt_sec: float = 0.1, coolant_change_rate_kps: float = 0.1,
):
    state_vector = np.array([0.9, 310.0], dtype=float)
    coolant_temp_actual_k = 300.0

    # ★ 초기 레지스터 값 세팅 (수정된 주소 및 함수 사용)
    write_float_to_hr_scaled(HR_ADDR_Q_SET_0, 100.0)
    write_float_to_hr_scaled(HR_ADDR_CAF_SET_1, 1.0)
    write_float_to_hr_scaled(HR_ADDR_TC_SET_2, coolant_temp_actual_k)
    write_float_to_hr_scaled(HR_ADDR_TC_ACTUAL_3, coolant_temp_actual_k)
    write_float_to_hr_scaled(HR_ADDR_REACTOR_T_REAL_4, state_vector[1])
    write_float_to_hr_scaled(HR_ADDR_REACTOR_CA_REAL_5, state_vector[0])
    # HMI가 사용할 측정값(Sensed)도 초기화
    write_float_to_hr_scaled(HR_ADDR_REACTOR_T_SENSED_6, state_vector[1])
    write_float_to_hr_scaled(HR_ADDR_REACTOR_CA_SENSED_7, state_vector[0])


    logging.info(
        "Initial Plant state → T=%6.1f K, Ca=%5.3f, Tc_act=%6.1f K",
        state_vector[1], state_vector[0], coolant_temp_actual_k,
    )
    last_log_time = time.perf_counter()

    while True:
        loop_start_time = time.perf_counter()

        # [변경 1-5] 수정된 주소와 함수로 Set-point 읽기
        flow_rate_lps      = read_scaled_int_from_hr(HR_ADDR_Q_SET_0)
        feed_conc_molm3    = read_scaled_int_from_hr(HR_ADDR_CAF_SET_1)
        coolant_temp_set_k = read_scaled_int_from_hr(HR_ADDR_TC_SET_2)

        delta_tc = np.clip(
            coolant_temp_set_k - coolant_temp_actual_k,
            -coolant_change_rate_kps * integration_dt_sec,
            coolant_change_rate_kps * integration_dt_sec,
        )
        coolant_temp_actual_k += delta_tc

        state_vector = integrate_one_time_step(
            current_state=state_vector, flow_rate_lps=flow_rate_lps,
            coolant_temp_k=coolant_temp_actual_k,
            feed_concentration_molm3=feed_conc_molm3,
            time_step_sec=integration_dt_sec,
        )
        # '실제(Real)' 값
        real_Ca, real_T = state_vector

        # [변경 1-4] '실제 값'에 노이즈를 더해 '측정 값(Sensed)' 생성
        sensed_T = real_T + (np.random.randn() * NOISE_STD_DEV_T_K)
        sensed_Ca = real_Ca + (np.random.randn() * NOISE_STD_DEV_CA)

        # 결과 레지스터 기록
        write_float_to_hr_scaled(HR_ADDR_TC_ACTUAL_3, coolant_temp_actual_k)
        # 실제 값 기록
        write_float_to_hr_scaled(HR_ADDR_REACTOR_T_REAL_4, real_T)
        write_float_to_hr_scaled(HR_ADDR_REACTOR_CA_REAL_5, real_Ca)
        # HMI가 사용할 측정 값 기록
        write_float_to_hr_scaled(HR_ADDR_REACTOR_T_SENSED_6, sensed_T)
        write_float_to_hr_scaled(HR_ADDR_REACTOR_CA_SENSED_7, sensed_Ca)


        current_time = time.perf_counter()
        if current_time - last_log_time >= 10.0:
            logging.info(
                "Plant state → T_real=%6.1f K, Ca_real=%5.3f, Tc_act=%6.1f K",
                real_T, real_Ca, coolant_temp_actual_k,
            )
            last_log_time = current_time

        elapsed = time.perf_counter() - loop_start_time
        time.sleep(max(0.0, integration_dt_sec - elapsed))


"""
SIM + MODBUS_SERVER 
# ──────────────────────────────────────────────────────
# 8. Modbus 서버 실행 (main 함수 변경 없음)
# ──────────────────────────────────────────────────────
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="SIM %(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    threading.Thread(
        target=simulation_thread, daemon=True, name="CSTR_SimulationThread"
    ).start()
    logging.info("Server listening.")
    StartTcpServer(
        context=server_context, address=("0.0.0.0", 5020),
        trace_connect=lambda c: logging.info("Client %s", "connected" if c else "disconnected"),
    )

if __name__ == "__main__":
    main()
"""
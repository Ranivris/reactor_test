#!/usr/bin/env python3
"""
CSTR 오프라인 시뮬레이션 실행 및 리포트 생성기 (조건부 이벤트 기능 개선)
"""
import os
import time
import operator  # 연산자 모듈 임포트
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sim.cstr_sim as sim

import koreanize_matplotlib

# ──────────────────────────────────────────────────────
# 1. 시뮬레이션 및 리포트 설정
# ──────────────────────────────────────────────────────
SIMULATION_DURATION_SEC = 240.0
INTEGRATION_DT_SEC = 0.1
OUTPUT_DIR = "../../simulation_result"

attack_coolant_temp = 303.0
emergency_coolant_operation_condition = 334.0
# 1-1. 시간 기반 시나리오
SCENARIO = {
    30.0: {
        'Tc_set': attack_coolant_temp,
        'comment': '냉각수 온도를 305K로 높여 반응 유도'
    }
}

# ★★★★★ 1-2. 조건 기반 이벤트 시나리오 ★★★★★
# [ {조건}, {액션}, {설명}, {상태} ] 형태로 이벤트 정의
CONDITIONAL_EVENTS = [
    {
        'trigger_variable': 'T_real',  # 감시할 변수
        'operator': '>=',  # 비교 연산자
        'value': emergency_coolant_operation_condition,  # 임계값
        'action': {'Tc_set': 295.0},  # 실행할 동작
        'comment': '반응기 온도 350K 초과, 긴급 냉각 실시!',
        'triggered': False,  # 실행 여부 플래그
    },
    # 여기에 다른 조건들을 추가할 수 있습니다.
    # 예: 농도가 0.1 이하로 떨어지면 유량을 줄이는 조건
    # {
    #     'trigger_variable': 'Ca_real',
    #     'operator': '<=',
    #     'value': 0.1,
    #     'action': {'q_in': 80.0},
    #     'comment': '반응물 고갈, 유량 감소',
    #     'triggered': False,
    # }
]
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★


SCENARIO_NAME = f"공격_{attack_coolant_temp}_긴급냉각_{emergency_coolant_operation_condition}"

# 연산자 문자열을 실제 함수로 매핑
OPERATORS = {
    '>': operator.gt,
    '<': operator.lt,
    '>=': operator.ge,
    '<=': operator.le,
    '==': operator.eq
}


# ──────────────────────────────────────────────────────
# 2. 시뮬레이션 실행 (수정된 버전)
# ──────────────────────────────────────────────────────
def perform_cstr_simulation(output_csv_path):

    # 환경 설정 변경
    sim.ARRHENIUS_PREEXP *= 0.9


    """CSTR 시뮬레이션을 수행하고 결과를 CSV 파일로 저장합니다."""
    print("Step 1: Running CSTR simulation...")

    # 시뮬레이션 초기화
    state_vector = np.array([0.9, 310.0], dtype=float)
    coolant_temp_actual_k = 300.0
    sim.write_float_to_hr_scaled(sim.HR_ADDR_Q_SET_0, 100.0)
    sim.write_float_to_hr_scaled(sim.HR_ADDR_CAF_SET_1, 1.0)
    sim.write_float_to_hr_scaled(sim.HR_ADDR_TC_SET_2, coolant_temp_actual_k)

    results_data = []

    num_steps = int(SIMULATION_DURATION_SEC / INTEGRATION_DT_SEC)
    for i in range(num_steps + 1):
        current_sim_time = i * INTEGRATION_DT_SEC

        # 1. 시간 기반 시나리오 실행
        for t, event in SCENARIO.items():
            if np.isclose(current_sim_time, t):
                print(f"\n[Time Event at t={current_sim_time:.1f}s] {event['comment']}")
                if 'Tc_set' in event:
                    sim.write_float_to_hr_scaled(sim.HR_ADDR_TC_SET_2, event['Tc_set'])
                if 'q_in' in event:
                    sim.write_float_to_hr_scaled(sim.HR_ADDR_Q_SET_0, event['q_in'])

        # 2. 1-step 시뮬레이션 로직
        # ... (이전 코드와 동일, 생략) ...
        flow_rate_lps = sim.read_scaled_int_from_hr(sim.HR_ADDR_Q_SET_0)
        feed_conc_molm3 = sim.read_scaled_int_from_hr(sim.HR_ADDR_CAF_SET_1)
        coolant_temp_set_k = sim.read_scaled_int_from_hr(sim.HR_ADDR_TC_SET_2)

        coolant_change_rate_kps = 0.1
        delta_tc = np.clip(coolant_temp_set_k - coolant_temp_actual_k, -coolant_change_rate_kps * INTEGRATION_DT_SEC,
                           coolant_change_rate_kps * INTEGRATION_DT_SEC)
        coolant_temp_actual_k += delta_tc

        state_vector = sim.integrate_one_time_step(
            current_state=state_vector, flow_rate_lps=flow_rate_lps,
            coolant_temp_k=coolant_temp_actual_k,
            feed_concentration_molm3=feed_conc_molm3,
            time_step_sec=INTEGRATION_DT_SEC,
        )
        real_Ca, real_T = state_vector

        # 현재 상태를 딕셔너리로 저장
        current_state = {'T_real': real_T, 'Ca_real': real_Ca}

        # ★★★★★ 3. 조건 기반 이벤트 검사 및 실행 ★★★★★
        for event in CONDITIONAL_EVENTS:
            # 아직 실행되지 않은 이벤트만 검사
            if not event['triggered']:
                trigger_var_value = current_state.get(event['trigger_variable'])
                op_func = OPERATORS.get(event['operator'])

                # 조건이 충족되면 액션 실행
                if op_func and trigger_var_value is not None and op_func(trigger_var_value, event['value']):
                    print(f"\n[!!! Conditional Event at t={current_sim_time:.1f}s !!!]")
                    print(
                        f"  -> Trigger: {event['trigger_variable']} ({trigger_var_value:.2f}) {event['operator']} {event['value']}")
                    print(f"  -> Action: {event['comment']}")

                    # 액션 실행
                    if 'Tc_set' in event['action']:
                        sim.write_float_to_hr_scaled(sim.HR_ADDR_TC_SET_2, event['action']['Tc_set'])
                    if 'q_in' in event['action']:
                        sim.write_float_to_hr_scaled(sim.HR_ADDR_Q_SET_0, event['action']['q_in'])

                    # 플래그를 True로 설정하여 중복 실행 방지
                    event['triggered'] = True
        # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

        # 4. 결과 기록
        results_data.append([
            current_sim_time, flow_rate_lps, feed_conc_molm3,
            coolant_temp_set_k, coolant_temp_actual_k, real_T, real_Ca
        ])

    # DataFrame 생성 및 CSV 저장
    # ... (이하 동일) ...
    headers = ["Time_sec", "Q_set", "Caf_set", "Tc_set", "Tc_actual", "T_real", "Ca_real"]
    df = pd.DataFrame(results_data, columns=headers)
    df.to_csv(output_csv_path, index=False, float_format='%.4f')
    print(f"\nSimulation data saved to '{output_csv_path}'")
    return df


# ... (generate_report, main 함수는 이전과 동일하므로 생략) ...
def generate_report(df, md_path, png_path):
    """DataFrame을 받아 그래프와 Markdown 리포트를 생성합니다."""
    print("Step 2: Generating plot...")

    # --- Matplotlib으로 그래프 생성 ---
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True, gridspec_kw={'height_ratios': [2, 1]})
    fig.suptitle(f'CSTR Simulation Results: {SCENARIO_NAME}', fontsize=16)

    # 첫 번째 플롯: 온도 변화
    ax1.plot(df['Time_sec'], df['T_real'], label='Reactor Temperature ($T_{real}$)', color='r', linewidth=2)
    ax1.plot(df['Time_sec'], df['Tc_actual'], label='Coolant Temperature ($T_{c, actual}$)', color='b', linestyle='--')
    ax1.plot(df['Time_sec'], df['Tc_set'], label='Coolant Setpoint ($T_{c, set}$)', color='c', linestyle=':')
    ax1.set_ylabel('Temperature (K)')
    ax1.legend()
    ax1.grid(True, linestyle='--', alpha=0.6)

    # 두 번째 플롯: 농도 변화
    ax2.plot(df['Time_sec'], df['Ca_real'], label='Reactant Concentration ($C_{a, real}$)', color='g')
    ax2.set_xlabel('Time (seconds)')
    ax2.set_ylabel('Concentration (mol/m³)')
    ax2.legend()
    ax2.grid(True, linestyle='--', alpha=0.6)

    # 시나리오 변경 지점 세로선으로 표시
    for t in SCENARIO.keys():
        ax1.axvline(x=t, color='gray', linestyle='--', linewidth=1)
        ax2.axvline(x=t, color='gray', linestyle='--', linewidth=1)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(png_path)
    plt.close(fig)
    print(f"Plot saved to '{png_path}'")

    # --- Markdown 리포트 파일 생성 ---
    print("Step 3: Generating Markdown report...")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f"# 📜 CSTR 시뮬레이션 리포트: {SCENARIO_NAME}\n\n")
        f.write(f"시뮬레이션 일시: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## 📝 시간 기반 시나리오\n\n")
        f.write("| 시간 (초) | 이벤트 내용 |\n")
        f.write("|:---:|:---|\n")
        for t, event in sorted(SCENARIO.items()):
            f.write(f"| {t:.1f} | {event['comment']} |\n")

        f.write("\n## 🚨 조건 기반 시나리오\n\n")
        f.write("| 조건 | 액션 |\n")
        f.write("|:---:|:---|\n")
        for event in CONDITIONAL_EVENTS:
            condition_str = f"`{event['trigger_variable']}` {event['operator']} `{event['value']}`"
            f.write(f"| {condition_str} | {event['comment']} |\n")

        f.write("\n## 📈 시뮬레이션 결과 그래프\n\n")
        f.write(f"![Simulation Results](./{os.path.basename(png_path)})\n")

    print(f"Markdown report saved to '{md_path}'")


def main():
    """메인 실행 함수"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # CONDITIONAL_EVENTS의 triggered 상태 초기화 (재실행을 위해)
    for event in CONDITIONAL_EVENTS:
        event['triggered'] = False

    csv_filename = f"{SCENARIO_NAME}_data.csv"
    png_filename = f"{SCENARIO_NAME}.png"
    md_filename = f"{SCENARIO_NAME}.md"

    csv_path = os.path.join(OUTPUT_DIR, csv_filename)
    png_path = os.path.join(OUTPUT_DIR, png_filename)
    md_path = os.path.join(OUTPUT_DIR, md_filename)

    results_df = perform_cstr_simulation(csv_path)
    generate_report(results_df, md_path, png_path)

    print(f"\n✅ All tasks completed. Check the '{OUTPUT_DIR}' folder.")


if __name__ == "__main__":
    main()
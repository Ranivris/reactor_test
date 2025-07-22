#!/usr/bin/env python3
import time, csv, threading, numpy as np
from collections import deque
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button
from scipy.integrate import solve_ivp


# ==============================================================================
# 1. 공정 모델 (최종 수정본 적용)
# ==============================================================================
def cstr_rhs(t, x, q, Tc, Caf):
    Ca, T = x
    V = 100.0
    rho, Cp = 1_000.0, 0.239

    # 열 폭주 및 제어가 가능한 검증된 파라미터 세트
    E_R = 8750.0
    k0 = 7.2e10
    UA = 5.0e4
    dH = -5.5e4

    rA = k0 * np.exp(-E_R / max(T, 1)) * Ca
    dCa = q / V * (Caf - Ca) - rA

    # 발열 반응(dH < 0)이므로, 앞에 (-)를 붙여 열 발생(양수) 항으로 수정
    dT = (q / V * (350.0 - T)
          - dH / (rho * Cp) * rA
          + UA / (rho * Cp * V) * (Tc - T))

    return [dCa, dT]


def one_step(x, q, Tc, Caf, dt):
    sol = solve_ivp(cstr_rhs, [0, dt], x, args=(q, Tc, Caf), method='Radau', rtol=1e-6, atol=1e-8)
    Ca, T = sol.y[:, -1]
    return np.array([np.clip(Ca, -1, 1e5), np.clip(T, -1, 1e5)])


# ==============================================================================
# 2. 공유 데이터 버퍼 및 설정
# ==============================================================================
WIN = 120
dt_sim = 0.1
dt_ui = 0.5
max_pts = int(WIN / dt_sim)

t_hist, T_hist, Ca_hist = (deque(maxlen=max_pts) for _ in range(3))
q_hist, caf_hist, tc_hist = (deque(maxlen=max_pts) for _ in range(3))

buffer_lock = threading.Lock()
TEMP_NOISE_STD = 0.20


# ==============================================================================
# 3. 시뮬레이션 루프
# ==============================================================================
def simulation_loop():
    state = np.array([0.9, 310.0])
    t0 = time.perf_counter()

    with open('cstr_ui_log.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['time', 'q_set', 'caf_set', 'tc_set', 'T_measured', 'Ca_actual'])

        while running.is_set():
            now = time.perf_counter() - t0

            q_set = slider_q.val
            caf_set = slider_caf.val
            tc_set = slider_tc.val

            state = one_step(state, q_set, tc_set, caf_set, dt_sim)
            Ca_true, T_true = state

            noise = np.random.randn() * TEMP_NOISE_STD
            T_measured = T_true + noise

            with buffer_lock:
                t_hist.append(now)
                T_hist.append(T_measured)
                Ca_hist.append(Ca_true)
                q_hist.append(q_set)
                caf_hist.append(caf_set)
                tc_hist.append(tc_set)

            writer.writerow([f'{now:.1f}', f'{q_set:.2f}', f'{caf_set:.3f}',
                             f'{tc_set:.2f}', f'{T_measured:.3f}', f'{Ca_true:.4f}'])
            f.flush()

            time.sleep(dt_sim)


# ==============================================================================
# 4. UI 초기화 및 레이아웃 설정
# ==============================================================================
def init_plot():
    fig = plt.figure(figsize=(12, 8))

    axT = fig.add_subplot(2, 3, (1, 2))
    axCa = fig.add_subplot(2, 3, 3)
    axQ = fig.add_subplot(2, 3, 4)
    axCaf = fig.add_subplot(2, 3, 5)
    axTc = fig.add_subplot(2, 3, 6)

    plt.subplots_adjust(left=0.15, right=0.85, bottom=0.25, top=0.95, hspace=0.35, wspace=0.25)

    # 그래프 라벨 (영문 Tag로 수정)
    lnT, = axT.plot([], [], 'r-', lw=2.5, label='Reactor Temperature (T)')
    lnCa, = axCa.plot([], [], 'b-', lw=2, label='Reactant Concentration (Ca)')
    lnQ, = axQ.plot([], [], 'g-', lw=2, label='Flow Rate (q)')
    lnCaf, = axCaf.plot([], [], 'm-', lw=2, label='Feed Concentration (Caf)')
    lnTc, = axTc.plot([], [], 'c-', lw=2, label='Coolant Temperature (Tc)')

    axes = {'T': axT, 'Ca': axCa, 'q': axQ, 'Caf': axCaf, 'Tc': axTc}

    for ax in axes.values():
        ax.set_xlim(0, WIN)
        ax.grid(True)
        ax.legend(loc='upper left')
        ax.ticklabel_format(useOffset=False, style='plain')

    # 축 제목 및 설명 (영문 Tag로 수정)
    axT.set_title("CSTR Reactor Status", fontsize=14)
    axT.set_ylim(280, 450)
    axT.set_ylabel('Temperature [K]')
    axT.set_xlabel('Time [s]')

    axCa.set_ylim(0, 1.2)
    axCa.set_ylabel('Concentration [mol/m³]')
    axCa.set_xlabel('Time [s]')

    axQ.set_ylim(50, 150)
    axQ.set_ylabel('Flow Rate [L/s]')
    axQ.set_xlabel('Time [s]')

    axCaf.set_ylim(0.5, 1.5)
    axCaf.set_ylabel('Concentration [mol/m³]')
    axCaf.set_xlabel('Time [s]')

    axTc.set_ylim(280, 320)
    axTc.set_ylabel('Temperature [K]')
    axTc.set_xlabel('Time [s]')

    ax_q_slider = plt.axes([0.1, 0.12, 0.85, 0.03])
    ax_caf_slider = plt.axes([0.1, 0.07, 0.85, 0.03])
    ax_tc_slider = plt.axes([0.1, 0.02, 0.85, 0.03])

    # 슬라이더 라벨 (영문 Tag로 수정)
    sld_q = Slider(ax_q_slider, 'Flow Rate (q)', 50, 150, valinit=100)
    sld_caf = Slider(ax_caf_slider, 'Feed Conc. (Caf)', 0.5, 1.5, valinit=1.0)
    sld_tc = Slider(ax_tc_slider, 'Coolant Temp. (Tc)', 280, 320, valinit=300)

    return fig, axes, (lnT, lnCa, lnQ, lnCaf, lnTc), (sld_q, sld_caf, sld_tc)


# ==============================================================================
# 5. UI 갱신 루프
# ==============================================================================
def ui_loop():
    last_update = time.perf_counter()
    while plt.fignum_exists(fig.number) and running.is_set():
        if time.perf_counter() - last_update >= dt_ui:
            with buffer_lock:
                lnT.set_data(t_hist, T_hist)
                lnCa.set_data(t_hist, Ca_hist)
                lnQ.set_data(t_hist, q_hist)
                lnCaf.set_data(t_hist, caf_hist)
                lnTc.set_data(t_hist, tc_hist)

            if T_hist:
                t_max = max(T_hist)
                ylim_t = axes['T'].get_ylim()
                if t_max > ylim_t[1]:
                    axes['T'].set_ylim(ylim_t[0], t_max * 1.1)

            if t_hist and t_hist[-1] > WIN:
                right = t_hist[-1]
                for ax in axes.values():
                    ax.set_xlim(right - WIN, right)

            fig.canvas.draw_idle()
            last_update = time.perf_counter()

        plt.pause(0.05)


# ==============================================================================
# 6. 실행 부분
# ==============================================================================
if __name__ == '__main__':
    fig, axes, lines, sliders = init_plot()
    lnT, lnCa, lnQ, lnCaf, lnTc = lines
    slider_q, slider_caf, slider_tc = sliders

    running = threading.Event()
    running.set()

    sim_thread = threading.Thread(target=simulation_loop, daemon=True)
    sim_thread.start()

    try:
        ui_loop()
    finally:
        running.clear()
        sim_thread.join()
        plt.close(fig)
        print("Simulation Ended.")

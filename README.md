# Introduction
This is a simple CSTR (Continuous Stirred-Rank Reactor) Simulator

## What is CSTR? 
CSTR(Continuous-Stirred Tank Reactor)은 **'내용물이 계속 흐르면서 완벽하게 섞이는 화학 반응 탱크'**입니다.

마치 '자동으로 주스를 만드는 믹서기'와 같습니다.

C (Continuous / 연속): 원료(물과 주스 가루)가 계속해서 들어가고, 완성된 제품(주스)이 계속해서 흘러나옵니다. 한 번에 만들고 끝나는 냄비 요리와는 다릅니다.

S (Stirred / 교반): 탱크 안에는 강력한 믹서(임펠러)가 있어 내용물을 항상 완벽하게 섞어줍니다. 이 때문에 탱크 내부 어디를 떠서 맛보아도 농도와 온도가 똑같습니다.

T (Tank / 탱크): 반응이 일어나는 공간인 통 자체를 의미합니다.

R (Reactor / 반응기): 탱크 안에서 원료가 제품으로 변하는 화학 반응이 일어납니다.

### 가장 큰 특징
가장 큰 특징은 탱크 내부의 모든 지점에서 농도와 온도가 동일하다는 것입니다. 따라서 탱크에서 흘러나오는 제품의 상태는 탱크 내부의 상태와 정확히 같습니다.

이러한 특성 때문에 대규모 화학제품 생산, 폐수 처리, 의약품 제조 등 다양한 산업 분야에서 널리 사용됩니다.

## sim/cstr_sim.py 
시뮬레이터 내용 담고 있음. 모드버스 내용 분리 할지 말지 결정 필요 

## real_time_simulation/cstr_sim_server.py 
시뮬레이터를 실시간으로 동작하는 서비스

## batch/run_simulation.py
비실시간으로, 미리 설정한 대로 동작함. 설정 값에 따른 동작 결과 확인에 적합 

## hmi/hmi_client.py
HMI + Simple Modbus Client, cstr_sim.py 가 먼저 실행되어야 함 

(In thie scenario, just simple graphs serves as HMI)

### 적분기: Solve_IVP 사용  
### 변화율 계산 함수 : ode_rhs( **O**rdinary **D**ifferential **E**quation - **R**ight **H**and **S**ide) 를 이용해서 연속 공정 시뮬레이션 

### 변수 정의

Ca
: 반응기 내 반응물 A의 농도 (concentration_Ca)

T
: 반응기 온도 (temperature_T)

r 
: 반응 속도 (reaction_rate)

q 
: 유입 유량 (flow_rate_lps)

V 
: 반응기 부피 (CSTR_VOLUME_M3)

Caf
: 유입물 내 A의 농도 (feed_concentration_molm3)

Tf
: 유입물 온도 (FEED_TEMPERATURE_K)

Tc
: 냉각수 온도 (coolant_temp_k)

k0
: 반응 속도 상수 전인자 (ARRHENIUS_PREEXP)

E/R 
: 활성화 에너지 / 기체 상수 (ARRHENIUS_E_OVER_R)

−ΔHr
  : 반응 엔탈피 (REACTION_ENTHALPY_KJ_M)

ρ 
: 밀도 (LIQUID_DENSITY_KG_M3)

Cp
  : 비열 (HEAT_CAPACITY_KJ_KG_K)

UA 
: 총괄 열전달 계수 × 면적 (U_A_J_PER_S_K)

### 변화율 계산 함수 내부 로직 

**축적량 = 유입량 - 유출량 + 생성령 - 소모량**
- **축적량**: `(시간 t+Δt에서의 총량) - (시간 t에서의 총량)`
- **유입량**: `(유입 농도) * (유량) * (시간)`
- **유출량**: `(유출 농도) * (유량) * (시간)`
- **소모량**: `(반응 속도) * (부피) * (시간)`
- `V * Ca(t+Δt) - V * Ca(t) = (q*Caf - q*Ca - V*r) * Δt`
- `(Ca(t+Δt) - Ca(t)) / Δt = (q/V)*(Caf - Ca) - r`
- `dCa/dt = (q/V)*(Caf - Ca) - r`

**에너지 축적량 (Accumulation) = 에너지 유입량 (In) - 에너지 유출량 (Out) + 에너지 생성량 (Generation) - 에너지 소모량 (Consumption)**
- **축적량**: `(시간 t+Δt의 총에너지) - (시간 t의 총에너지)`
- **유입량 (흐름)**: `(유량) * (밀도) * (비열) * (유입 온도) * (시간)`
- **유출량 (흐름)**: `(유량) * (밀도) * (비열) * (유출 온도) * (시간)`
- **생성량 (반응열)**: `(반응 속도) * (부피) * (반응 엔탈피) * (시간)`
- **소모량 (냉각)**: `(열전달량) * (시간)`
- `VρC_p * (T(t+Δt) - T(t)) = (qρC_pT_f - qρC_pT + rV(-ΔH_r) - UA(T - T_c)) * Δt`
- `(T(t+Δt) - T(t)) / Δt = (q/V)*(T_f - T) + (r(-ΔH_r))/(ρC_p) - (UA(T - T_c))/(VρC_p)`
- `dT/dt = (q/V)*(T_f - T) + ((-ΔH_r) / (ρC_p))*r + (UA / (VρC_p))*(T_c - T)`


In Attack Scenario,
  If Jacket Water (Coolant) 300 K -> 305K for a few seconds, The system will fall out of equilibrium.

# Execution Example. 
## Normal 
![Normal](./img/normal.png)
## Attack 
![After Modification](./img/attack.png)

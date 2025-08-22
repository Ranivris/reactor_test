#!/usr/bin/env python3
from sim.cstr_sim import *

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

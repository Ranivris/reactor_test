# Introduction
This is a simple CSTR (Continuous Stirred-Rank Reactor) Simulator 

Two python files. 

sim_server.py : Simulator + Simple Modbus Server 

hmi_client.py : HMI + Simple Modbus Client 

In Attack Scenario, 

  If Jacket Water (Coolant) 300 K -> 305K for a few seconds, The system will fall out of equilibrium.

# Execution Example. 
## Normal 
![Normal](./img/normal.png)
## Attack 
![After Modification](./img/attack.png)

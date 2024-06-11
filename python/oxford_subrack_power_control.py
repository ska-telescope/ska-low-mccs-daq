from utilities.skalab.hardware_client import WebHardwareClient
from time import sleep

# TODO: Add method to report which slots are ON or OFF

RAL_SUBRACK_1 = "10.132.0.14"
RAL_SUBRACK_2 = "10.132.0.34"
RAL_SURBACK_3 = "10.132.0.54"
RAL_SUBRACK_4 = "10.132.0.74"
# OXFORD_SUBRACK_1 = "10.0.10.64"

S8_SUBRACK_1 = "10.132.0.1"
S8_SUBRACK_2 = "10.132.0.17"
S8_SUBRACK_3 = "10.132.0.33"
S8_SUBRACK_4 = "10.132.0.49"

class Subrack:
    def __init__(self, ip):
        self._ip = ip
      
    def connect_to_subrack(self):
        client = WebHardwareClient(self._ip, "8081")
        if not client.connect():
            print("Error: Could not connect to subrack")
            return None
        print(f"Connected to subrack {self._ip}:8081")
        return client

    def power_on_all_tpms(self):
        client = self.connect_to_subrack()
        if client:
            while True:
                print("Issuing command to subrack...")
                ret = client.execute_command(command="turn_on_tpms")
                print(f"Subrack Returned: {ret}")
                if ret['status'] != 'BUSY':
                    break
                print("Retrying...")
                sleep(2)
            print("All TPMs are now ON!")

    def power_off_all_tpms(self):
        client = self.connect_to_subrack()
        if client:
            while True:
                print("Issuing command to subrack...")
                ret = client.execute_command(command="turn_off_tpms")
                print(f"Subrack Returned: {ret}")
                if ret['status'] != 'BUSY':
                    break
                print("Retrying...")
                sleep(2)
            print("All TPMs are now OFF!")

    def power_cycle_all_tpms(self):
        self.power_off_all_tpms()
        self.power_on_all_tpms()
        print("Request complete!")

    def power_on_tpm(self, slot_list):
        client = self.connect_to_subrack()
        if client:
            for slot in slot_list:
                if not isinstance(slot, int) or int(slot) > 8 or int(slot) < 1:
                    print(f"Error: slot number must be an integer 1-8. Got {slot}")
                    continue
                while True:
                    print("Issuing command to subrack...")
                    ret = client.execute_command(command="turn_on_tpm", parameters=slot)
                    print(f"Subrack Returned: {ret}")
                    if ret['status'] != 'BUSY':
                        break
                    print("Retrying...")
                    sleep(2)
                print(f"TPM {slot} is now ON!")
            print("Power ON Request complete!")

    def power_off_tpm(self, slot_list):
        client = self.connect_to_subrack()
        if client:
            for slot in slot_list:
                if not isinstance(slot, int) or int(slot) > 8 or int(slot) < 1:
                    print(f"Error: slot number must be an integer 1-8. Got {slot}")
                    continue
                while True:
                    print("Issuing command to subrack...")
                    ret = client.execute_command(command="turn_off_tpm", parameters=slot)
                    print(f"Subrack Returned: {ret}")
                    if ret['status'] != 'BUSY':
                        break
                    print("Retrying...")
                    sleep(2)
                print(f"TPM {slot} is now OFF!")
            print("Power OFF Request complete!")

    def power_cycle_tpm(self, slot_list):
        self.power_off_tpm(slot_list)
        self.power_on_tpm(slot_list)

    # So far retry loop does not seem to be required for configuring subrack fans
    # Can be added if requires as above
    def set_fan_speed(self, speed=80):
        client = self.connect_to_subrack()
        if client:
            for i in range(4):
                ret = client.execute_command(command="set_fan_mode", parameters=f"{i+1},0")
                print(f"Subrack Returned: {ret}")
                print(f"Subrack Fan {i+1} speed set to MANUAL")
                sleep(0.5)
                ret = client.execute_command(command="set_subrack_fan_speed", parameters=f"{i+1},{speed}")
                print(f"Subrack Returned: {ret}")
                print(f"Subrack Fan {i+1} speed set to {speed}%")


# class OxfordSubrack(Subrack):
#     def __init__(self):
#        super().__init__(ip=OXFORD_SUBRACK_1)

class RALSubrack1(Subrack):
    def __init__(self):
        super().__init__(ip=RAL_SUBRACK_1)

class RALSubrack2(Subrack):
    def __init__(self):
        super().__init__(ip=RAL_SUBRACK_2)

class RALSubrack3(Subrack):
    def __init__(self):
        super().__init__(ip=RAL_SUBRACK_3)

class RALSubrack4(Subrack):
    def __init__(self):
        super().__init__(ip=RAL_SUBRACK_4)


class S8Subrack1(Subrack):
    def __init__(self):
       super().__init__(ip=S8_SUBRACK_1)

class S8Subrack2(Subrack):
    def __init__(self):
        super().__init__(ip=S8_SUBRACK_2)

class S8Subrack3(Subrack):
    def __init__(self):
        super().__init__(ip=S8_SUBRACK_3)

class S8Subrack4(Subrack):
    def __init__(self):
        super().__init__(ip=S8_SUBRACK_4)

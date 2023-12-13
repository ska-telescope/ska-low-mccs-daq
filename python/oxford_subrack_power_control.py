from utilities.skalab.hardware_client import WebHardwareClient
from time import sleep

# TODO: When more than one subrack is installed, add a lookup for subrack IP and specify subrack 'name' as argument to all commands

# TODO: Add method to set all fans to 60, 80 or 100%. Useful once subrack has been power cycled

# TODO: Add method to report which slots of ON or OFF

def connected_to_subrack(func):
    """
    Decorator method to connect to subrack web server before issuing command.
    """
    def inner_func(*args, **kwargs):
        client = WebHardwareClient("10.0.10.64", "8081")
        if not client.connect():
            print("Error: Could not connect to subrack")
            return
        print("Connected to subrack 10.0.10.64:8081")
        return func(client, *args, **kwargs)
    return inner_func

@connected_to_subrack
def power_on_all_tpms(client):
    while True:
        print("Issuing command to subrack...")
        ret = client.execute_command(command="turn_on_tpms")
        print(f"Subrack Returned: {ret}")
        if ret['status'] != 'BUSY':
            break
        print("Retrying...")
        sleep(2)
    print("All TPMs are now ON!")

@connected_to_subrack
def power_off_all_tpms(client):
    while True:
        print("Issuing command to subrack...")
        ret = client.execute_command(command="turn_off_tpms")
        print(f"Subrack Returned: {ret}")
        if ret['status'] != 'BUSY':
            break
        print("Retrying...")
        sleep(2)
    print("All TPMs are now OFF!")

def power_cycle_all_tpms():
    power_off_all_tpms()
    power_on_all_tpms()
    print("Request complete!")

@connected_to_subrack
def power_on_tpm(client, slot_list):
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

@connected_to_subrack
def power_off_tpm(client, slot_list):
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

def power_cycle_tpm(slot_list):
    power_off_tpm(slot_list)
    power_on_tpm(slot_list)

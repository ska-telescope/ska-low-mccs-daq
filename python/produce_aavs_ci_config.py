from jinja2 import Environment, FileSystemLoader

with open("../.latest-firmware-version") as file:
    latest_firmware_version = file.read().strip(" \n")
    latest_firmware_version = latest_firmware_version.replace(".", "")

env = Environment(loader=FileSystemLoader("jinja_templates/"))
template = env.get_template("ral_ci_runner_aavs.jinja")
rendered_template = template.render(firmware_version=latest_firmware_version)

with open("../config/ral_ci_runner_aavs.yml", mode="w", encoding="utf-8") as file:
    file.write(rendered_template)

print("AAVS CI config produced")
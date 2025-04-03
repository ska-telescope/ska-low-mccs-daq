from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import os


def generate_templates(bitfile_path, template_name=None, start_fc=None, f_width=None, tile_40g_subnet=None, dst_ip=None,
                       dst_port=None, tiles=None):
    data = {
        "observation": {
            "start_frequency_channel": start_fc or "156.25e6",
            "bandwidth": f_width or "6.25e6"
        },
        "station": {
            "bitfile": bitfile_path
        },
        "network": {
            "tile_40g_subnet": tile_40g_subnet or "10.130.0.51/25",
            "dst_ip": dst_ip or "10.132.61.2",
            "dst_port": dst_port or "6660"
        },
        "tiles": tiles or ["10.132.0.61", "10.132.0.62"]
    }

    config_dir = Path(__file__).resolve().parents[2] / "config"
    file_loader = FileSystemLoader('/')
    environment = Environment(loader=file_loader)
    # Iterate through templates dir for all .template files
    for file in Path(f'{config_dir}/templates').iterdir():
        if file.is_file() and file.name.endswith('.template'):
            # If all templates or specific template found
            if template_name is None or template_name == file.name:
                template = environment.get_template(str(file))
                output_file = file.name.replace('.template', '')
                with open(Path(config_dir) / output_file, mode="w", encoding="utf-8") as config_yml:
                    config_yml.write(template.render(data=data))

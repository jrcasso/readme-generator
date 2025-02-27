#!/usr/bin/env python3
from typing import List, Dict, Set, Optional, Any, Tuple, Iterator
import os
import re
import json
import yaml
import argparse
import pathspec


def load_global_gitignore(base_dir: str) -> Optional[pathspec.PathSpec]:
    gitignore_path = os.path.join(base_dir, '.gitignore')
    if os.path.exists(gitignore_path) and pathspec:
        with open(gitignore_path, 'r', encoding='utf-8') as f:
            patterns = f.read().splitlines()
        return pathspec.PathSpec.from_lines('gitwildmatch', patterns)
    return None


def walk_with_gitignore(base_dir: str, global_spec: Optional[pathspec.PathSpec] = None) -> Iterator[Tuple[str, List[str], List[str]]]:
    for root, dirs, files in os.walk(base_dir, topdown=True):
        rel_root = os.path.relpath(root, base_dir)
        if global_spec and rel_root != "." and global_spec.match_file(rel_root):
            dirs[:] = []
            files[:] = []
            continue

        # Load local .gitignore (if present) and filter children accordingly.
        local_spec = None
        local_gitignore = os.path.join(root, ".gitignore")
        if os.path.exists(local_gitignore) and pathspec:
            try:
                with open(local_gitignore, 'r', encoding='utf-8') as f:
                    patterns = f.read().splitlines()
                if patterns:
                    local_spec = pathspec.PathSpec.from_lines(
                        'gitwildmatch', patterns)
            except Exception as e:
                print(f"Error processing {local_gitignore}: {e}")
        if local_spec:
            dirs[:] = [d for d in dirs if not local_spec.match_file(d)]
            files = [f for f in files if not local_spec.match_file(f)]
        yield root, dirs, files


def find_files(base_dir: str, filename_regex: str, global_spec: Optional[pathspec.PathSpec] = None) -> List[str]:
    matches = []
    pattern = re.compile(filename_regex)
    for root, dirs, files in walk_with_gitignore(base_dir, global_spec):
        for file in files:
            if pattern.fullmatch(file):
                matches.append(os.path.join(root, file))
    return matches


def remove_json_comments(text: str) -> str:
    pattern = r'("(?:\\.|[^"\\])*")|(/\*.*?\*/|//.*?$)'

    def replacer(match):
        if match.group(1) is not None:
            return match.group(1)
        return ""
    return re.sub(pattern, replacer, text, flags=re.MULTILINE | re.DOTALL)


def remove_trailing_commas(text: str) -> str:
    return re.sub(r',\s*([}\]])', r'\1', text)


def parse_json_file(file_path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
            text = remove_json_comments(text)
            text = remove_trailing_commas(text)
            return json.loads(text)
        except Exception as inner_e:
            print(f"Error reading {file_path} even after cleaning: {inner_e}")
            return None
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return None


def parse_yaml_file(file_path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return None


def generate_html_table(headers: List[str], rows: List[List[str]]) -> str:
    if not rows:
        return ""
    num_cols = len(headers)
    non_empty_cols = []
    for col_index in range(num_cols):
        if any(row[col_index].strip() for row in rows):
            non_empty_cols.append(col_index)
    new_headers = [headers[i] for i in non_empty_cols]
    new_rows = [[row[i] for i in non_empty_cols] for row in rows]
    table = "<table style='border-collapse: collapse;'>"
    table += "<tr>" + \
        "".join(
            f"<th style='border: 1px solid #ddd; padding:4px;'>{h}</th>" for h in new_headers) + "</tr>"
    for row in new_rows:
        table += "<tr>" + \
            "".join(
                f"<td style='border: 1px solid #ddd; padding:4px;'>{cell}</td>" for cell in row) + "</tr>"
    table += "</table>"
    return table


def format_devcontainer_extensions(extensions_list: Optional[List[str]]) -> str:
    if not extensions_list:
        return ""
    rows = []
    for ext in extensions_list:
        ext = ext.strip()
        if ext:
            link = f'<a href="https://marketplace.visualstudio.com/items?itemName={ext}" target="_blank">{ext}</a>'
            rows.append([ext, link])
    return generate_html_table(["Name", "Store Link"], rows)


def format_inputs_table(input_ids: Set[str], input_definitions: Dict[str, Dict[str, Any]]) -> str:
    rows = []
    for input_id in sorted(input_ids):
        if input_id in input_definitions:
            inp = input_definitions[input_id]
            desc = inp.get("description", "").strip()
            default = inp.get("default")
            options = inp.get("options")
            options_str = ""
            if options:
                if isinstance(options, list):
                    formatted_options = []
                    for opt in options:
                        if default not in [None, ""] and str(opt) == str(default):
                            formatted_options.append(f"`{opt}`✓")
                        else:
                            formatted_options.append(f"`{opt}`")
                    options_str = " ".join(formatted_options)
                else:
                    if default not in [None, ""] and options == default:
                        options_str = f"`{options}✓`"
                    else:
                        options_str = f"`{options}`"
            rows.append([input_id, desc, options_str])
        else:
            rows.append([input_id, "", ""])
    return generate_html_table(["Name", "Description", "Options"], rows) if rows else ""


def format_volumes_table(volumes_list: List[str]) -> str:
    def format_host(host: str) -> str:
        if (host == "."):
            return "(Project directory)"
        return host

    rows = []
    for vol in volumes_list:
        parts = vol.split(":")
        host = format_host(parts[0]) if len(parts) > 0 else ""
        container = parts[1] if len(parts) > 1 else ""
        mode = parts[2] if len(parts) > 2 else ""
        rows.append([host, container, mode])
    return generate_html_table(["Host", "Container", "Mode"], rows) if rows else ""


def format_env_table(env_filtered: Dict[str, str]) -> str:
    rows = []
    for key in sorted(env_filtered.keys()):
        rows.append([f"`${key}`"])
    return generate_html_table(["Host ENV variable"], rows) if rows else ""


def extract_all_input_ids(obj: Any) -> Set[str]:
    found = set()
    if isinstance(obj, dict):
        for value in obj.values():
            found.update(extract_all_input_ids(value))
    elif isinstance(obj, list):
        for item in obj:
            found.update(extract_all_input_ids(item))
    elif isinstance(obj, str):
        found.update(re.findall(r"\$\{input:([^}]+)\}", obj))
    return found


def parse_vscode_tasks(file_path: str) -> List[Dict[str, str]]:
    data = parse_json_file(file_path)
    tasks_info: List[Dict[str, Any]] = []
    if not data:
        return tasks_info
    input_definitions = {}
    if isinstance(data, dict):
        inputs_list = data.get("inputs", [])
        input_definitions = {
            inp.get("id"): inp for inp in inputs_list if "id" in inp}
        tasks = data.get("tasks", [])
    else:
        tasks = data
    for task in tasks:
        label = task.get("label", "")
        detail = task.get("detail", "")
        command = task.get("command", "")
        if command:
            command = f'`{os.path.basename(command)}`'
        input_ids = extract_all_input_ids(task)
        input_details = format_inputs_table(
            input_ids, input_definitions) if input_ids else ""
        tasks_info.append({
            "label": label,
            "detail": detail,
            "command": command,
            "inputs": input_details
        })
    return tasks_info


def parse_vscode_launch(file_path: str) -> List[Dict[str, str]]:
    data = parse_json_file(file_path)
    launch_info: List[Dict[str, Any]] = []
    if not data:
        return launch_info
    input_definitions = {}
    configurations = []
    if isinstance(data, dict):
        if "inputs" in data:
            inputs_list = data.get("inputs", [])
            input_definitions = {
                inp.get("id"): inp for inp in inputs_list if "id" in inp}
        configurations = data.get("configurations", [])
    else:
        configurations = data
    for config in configurations:
        name = config.get("name", "")
        type_ = config.get("type", "")
        input_ids = extract_all_input_ids(config)
        input_details = format_inputs_table(
            input_ids, input_definitions) if input_ids else ""
        launch_info.append({
            "name": name,
            "type": type_,
            "inputs": input_details
        })
    return launch_info


def parse_devcontainer(file_path: str) -> Dict[str, str]:
    data = parse_json_file(file_path)
    dev_info: Dict[str, Any] = {}
    if not data:
        return dev_info
    customizations = data.get("customizations", {})
    if isinstance(customizations, dict):
        vscode_custom = customizations.get("vscode", {})
        if isinstance(vscode_custom, dict):
            extensions = vscode_custom.get("extensions", [])

    extensions = list(dict.fromkeys(extensions))
    dev_info["extensions"] = format_devcontainer_extensions(extensions)
    dev_info["file"] = os.path.relpath(file_path, os.getcwd())
    return dev_info


def parse_dockerfile(file_path: str) -> Dict[str, str]:
    base_image = ""
    exposed_ports = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.upper().startswith("FROM"):
                    parts = line.split()
                    if len(parts) >= 2:
                        base_image = parts[1]
                elif line.upper().startswith("EXPOSE"):
                    ports = line.split()[1:]
                    exposed_ports.extend(ports)
    except Exception as e:
        print(f"Error reading Dockerfile {file_path}: {e}")
    return {"base_image": base_image, "exposed_ports": ', '.join(exposed_ports)}


def parse_docker_compose(file_path: str) -> Dict[str, Any]:
    data = parse_yaml_file(file_path)
    compose_info: Dict[str, Any] = {"services": []}
    if not data or "services" not in data:
        return compose_info
    for service_name, service in data["services"].items():
        image = service.get("image", "(custom)")
        ports = service.get("ports", [])
        env_vars = service.get("environment", {})
        if isinstance(env_vars, list):
            env_dict = {}
            for item in env_vars:
                if '=' in item:
                    key, val = item.split('=', 1)
                    env_dict[key] = val
            env_vars = env_dict
        env_filtered = {k: v for k, v in env_vars.items(
        ) if isinstance(v, str) and "${" in v}
        env_str = format_env_table(env_filtered)
        svc_volumes = service.get("volumes", [])
        volumes_str = format_volumes_table(svc_volumes)
        build_prop = service.get("build")
        compose_info["services"].append({
            "service": service_name,
            "image": image,
            "ports": ', '.join(ports) if ports else "",
            "volumes": volumes_str,
            "environment": env_str,
            "build": build_prop
        })
    return compose_info


def generate_markdown_table(headers: List[str], rows: List[List[str]]) -> str:
    md = ""
    md += "| " + " | ".join(headers) + " |\n"
    md += "| " + " | ".join(["---"] * len(headers)) + " |\n"
    for row in rows:
        md += "| " + " | ".join(row) + " |\n"
    return md


def update_readme_table(new_section: str, readme_path: str = "README.md") -> None:
    start_marker = "<!-- README_DEVINFO:START -->"
    end_marker = "<!-- README_DEVINFO:END -->"
    wrapped_section = f"{start_marker}\n{new_section}\n{end_marker}"
    if os.path.exists(readme_path):
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
        if start_marker in content and end_marker in content:
            new_content = re.sub(f"{re.escape(start_marker)}.*?{re.escape(end_marker)}",
                                 wrapped_section, content, flags=re.DOTALL)
        else:
            new_content = content + "\n\n" + wrapped_section
    else:
        new_content = wrapped_section
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"Development info updated in {readme_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse VS Code and Docker configuration files to generate a markdown summary."
    )
    parser.add_argument("base_dir", nargs="?", default=".",
                        help="Project root directory")
    parser.add_argument("--unified", action="store_true",
                        help="Generate a unified table summary")
    args = parser.parse_args()
    base_dir = os.path.abspath(args.base_dir)
    global_spec = load_global_gitignore(base_dir)

    comp_file = "docker-compose.yml"
    additional_dockerfiles = set()
    compose_data = parse_docker_compose(comp_file)
    compose_data["file"] = os.path.relpath(comp_file, base_dir)
    data = parse_yaml_file(comp_file)
    if data and "services" in data:
        for service in data["services"].values():
            build_prop = service.get("build")
            if isinstance(build_prop, dict) and "dockerfile" in build_prop:
                dockerfile_path = os.path.join(
                    os.path.dirname(comp_file), build_prop["dockerfile"])
                additional_dockerfiles.add(os.path.abspath(dockerfile_path))

    dockerfile_set = set(find_files(base_dir, r"Dockerfile", global_spec))
    dockerfiles = list(dockerfile_set.union(additional_dockerfiles))

    tasks_files = find_files(base_dir, r"tasks\.json", global_spec)
    launch_files = find_files(base_dir, r"launch\.json", global_spec)
    devcontainer_files = find_files(
        base_dir, r"devcontainer\.json", global_spec)

    tasks_data = []
    for file in tasks_files:
        tasks_data.extend(parse_vscode_tasks(file))
    launch_data = []
    for file in launch_files:
        launch_data.extend(parse_vscode_launch(file))
    devcontainer_data = []
    for file in devcontainer_files:
        dev_info = parse_devcontainer(file)
        if dev_info:
            devcontainer_data.append(dev_info)
    dockerfile_data = []
    for file in dockerfiles:
        df_info = parse_dockerfile(file)
        df_info["file"] = os.path.relpath(file, base_dir)
        dockerfile_data.append(df_info)

    md_content = ""

    if compose_data:
        headers = ["Service", "Image", "Ports",
                   "Volumes", "Injected ENV variables"]
        rows = []
        for svc in compose_data.get("services", []):
            rows.append([
                svc.get("service", ""),
                svc.get("image", ""),
                svc.get("ports", ""),
                svc.get("volumes", ""),
                svc.get("environment", "")
            ])
        md_content += "## Docker Compose Configurations\n" + \
            generate_markdown_table(headers, rows) + "\n\n"

    if tasks_data:
        headers = ["Name", "Description", "Command", "Inputs"]
        rows = [[
            task.get("label", ""),
            task.get("detail", ""),
            task.get("command", ""),
            task.get("inputs", "")
        ] for task in tasks_data]
        md_content += "## VS Code Tasks\n" + \
            generate_markdown_table(headers, rows) + "\n\n"

    if launch_data:
        headers = ["Name", "Type", "Inputs"]
        rows = [[
            config.get("name", ""),
            config.get("type", ""),
            config.get("inputs", "")
        ] for config in launch_data]
        md_content += "## VS Code Launch Configurations\n" + \
            generate_markdown_table(headers, rows) + "\n\n"

    if devcontainer_data:
        headers = ["Extensions"]
        rows = [[
            dev.get("extensions", ""),
        ] for dev in devcontainer_data]
        md_content += "## Devcontainer Configurations\n" + \
            generate_markdown_table(headers, rows) + "\n\n"

    if dockerfile_data:
        headers = ["File", "Base Image", "Exposed Ports"]
        rows = [[
            df.get("file", ""),
            df.get("base_image", ""),
            df.get("exposed_ports", "")
        ] for df in dockerfile_data]
        md_content += "## Dockerfiles\n" + \
            generate_markdown_table(headers, rows) + "\n\n"

    if args.unified:
        headers = ["Config Type", "Details"]
        rows = [
            ["VS Code Tasks", f"{len(tasks_data)} tasks found"],
            ["VS Code Launch",
                f"{len(launch_data)} launch configurations found"],
            ["Devcontainer",
                f"{len(devcontainer_data)} devcontainer configs found"],
            ["Dockerfiles", f"{len(dockerfile_data)} Dockerfiles found"],
            ["Docker Compose",
                f"{len(compose_data)} docker-compose files found"]
        ]
        md_content += "## Unified Configuration Summary\n" + \
            generate_markdown_table(headers, rows) + "\n\n"

    update_readme_table(md_content)


if __name__ == "__main__":
    main()

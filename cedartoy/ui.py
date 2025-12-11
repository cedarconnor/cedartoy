import sys
from .options_schema import OPTIONS, Option
from typing import Any

def prompt_value(opt: Option, current_value: Any) -> Any:
    # Format the prompt
    type_str = f"[{opt.type}]"
    default_str = f" (default: {current_value})"
    if opt.choices:
        choices_str = f" {opt.choices}"
    else:
        choices_str = ""
        
    prompt = f"{opt.label} {type_str}{choices_str}{default_str}: "
    
    while True:
        val = input(prompt).strip()
        if not val:
            return current_value
            
        try:
            if opt.type == "int":
                return int(val)
            elif opt.type == "float":
                return float(val)
            elif opt.type == "bool":
                if val.lower() in ['y', 'yes', 'true', '1']:
                    return True
                if val.lower() in ['n', 'no', 'false', '0']:
                    return False
                raise ValueError("Invalid boolean")
            elif opt.type == "choice":
                if val not in opt.choices:
                    print(f"Invalid choice. Must be one of {opt.choices}")
                    continue
                return val
            elif opt.type == "path":
                # We could validate existence here, but maybe it's an output path
                return val
            else:
                return val
        except ValueError:
            print(f"Invalid input for type {opt.type}")

def run_wizard():
    print("CedarToy Configuration Wizard")
    print("-----------------------------")
    
    config = {}
    # Iterate and prompt
    # In a real app we might load existing config first
    for opt in OPTIONS:
        val = prompt_value(opt, opt.default)
        config[opt.name] = val
        
    print("\nGenerated Configuration:")
    for k, v in config.items():
        print(f"{k}: {v}")
        
    # TODO: Save to file option
    save = input("\nSave to cedartoy.yaml? [y/N]: ").strip().lower()
    if save in ['y', 'yes']:
        try:
            import yaml
            with open("cedartoy.yaml", "w") as f:
                yaml.dump(config, f)
            print("Saved to cedartoy.yaml")
        except ImportError:
            import json
            with open("cedartoy.json", "w") as f:
                json.dump(config, f, indent=2)
            print("Saved to cedartoy.json (PyYAML not found)")
        except Exception as e:
            print(f"Error saving: {e}")

if __name__ == "__main__":
    run_wizard()

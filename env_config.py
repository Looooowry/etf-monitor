import os


def get_env_str(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def get_env_int(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        print(f"Invalid integer for {name}: {value}. Using default {default}.")
        return default


def get_env_float(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        print(f"Invalid float for {name}: {value}. Using default {default}.")
        return default

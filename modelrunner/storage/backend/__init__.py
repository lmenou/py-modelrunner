import importlib
from .memory import MemoryStorage

AVAILABLE_STORAGE = [MemoryStorage]

POTENTIAL_STORAGE = {
    "json": "JSONStorage",
    "yaml": "YAMLStorage",
    "hdf": "HDFStorage",
    "zarr": "ZarrStorage",
}

# check which potential storages are available with the current setup
for module_name, cls_name in POTENTIAL_STORAGE.items():
    try:
        module = importlib.import_module("." + module_name, package=__name__)
    except ImportError:
        pass  # module cannot be loaded, likely because a package is missing
    else:
        cls = getattr(module, cls_name)
        globals()[cls.__name__] = cls  # make class available in this module
        AVAILABLE_STORAGE.append(cls)  # add class to list of available storages

# determine the objects available for full import
__all__ = ["AVAILABLE_STORAGE"] + [cls.__name__ for cls in AVAILABLE_STORAGE]

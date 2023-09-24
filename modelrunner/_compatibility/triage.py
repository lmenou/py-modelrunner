"""
Contains code necessary for deciding which format version was used to write a file

.. codeauthor:: David Zwicker <david.zwicker@ds.mpg.de>
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional, Union

from ..model import ModelBase
from ..results import Result

if TYPE_CHECKING:
    from zarr.storage import BaseStore  # @UnusedImport


Store = Union[str, Path, "BaseStore"]


def guess_format(path: Path) -> str:
    """guess the format of a given store

    Args:
        path (str or :class:`~pathlib.Path`):
            Path pointing to a file

    Returns:
        str: The store format
    """
    # guess format from path extension
    ext = Path(path).suffix.lower()
    if ext == ".json":
        return "json"
    elif ext in {".yml", ".yaml"}:
        return "yaml"
    elif ext in {".h5", ".hdf", ".hdf5"}:
        return "hdf"
    else:
        return "zarr"  # fallback to the default storage method based on zarr


def normalize_zarr_store(store: Store, mode: str = "a") -> Optional[Store]:
    """determine best file format for zarr storage

    In particular, we use a :class:`~zarr.storage.ZipStore` when a path looking like a
    file is given.

    Args:
        store: User-provided store
        mode (str): The mode with which the file will be opened

    Returns:
    """
    import zarr

    if isinstance(store, (str, Path)):
        store = Path(store)
        if store.is_file():
            store = zarr.storage.ZipStore(store, mode=mode)
        else:
            return None
    return store


def _find_version(data: Mapping[str, Any], label: str) -> Optional[int]:
    """try finding version information in different places in `data`

    Args:
        data (dict):
            A mapping that contains attribute information
        label (str):
            The label of the data that should be loaded

    Returns:
        int: The format version or None if it could not be found
    """

    def read_version(item) -> Optional[str]:
        """try reading attribute from a particular item"""
        if hasattr(item, "attrs"):
            return read_version(item.attrs)
        elif "__version__" in item:
            return item["__version__"]  # type: ignore
        elif "__attrs__" in item:
            return read_version(item["__attrs__"])
        elif "attributes" in item:
            return read_version(item["attributes"])
        else:
            return None

    format_version = read_version(data)
    if format_version is None and label in data:
        format_version = read_version(data[label])
    if format_version is None and "state" in data:
        format_version = read_version(data["state"])

    if isinstance(format_version, str):
        return json.loads(format_version)  # type: ignore
    else:
        return format_version


def result_check_load_old_version(
    path: Path, loc: str, *, model: Optional[ModelBase] = None
) -> Optional[Result]:
    """check whether the resource can be loaded with an older version of the package

    Args:
        path (str or :class:`~pathlib.Path`):
            The path to the resource to be loaded
        loc (str):
            Label, key, or location of the item to be loaded
        model (:class:`~modelrunner.model.ModelBase`, optional):
            Optional model that was used to write this result

    Returns:
        :class:`~modelrunner.result.Result`:
            The loaded result or `None` if we cannot load it with the old versions
    """
    label = "data" if loc is None else loc
    format_version = None
    # check for compatibility
    fmt = guess_format(path)
    if fmt == "json":
        with open(path, mode="r") as fp:
            format_version = _find_version(json.load(fp), label)

    elif fmt == "yaml":
        import yaml

        with open(path, mode="r") as fp:
            format_version = _find_version(yaml.safe_load(fp), label)

    elif fmt == "hdf":
        import h5py

        with h5py.File(path, mode="r") as root:
            format_version = _find_version(root, label)

    elif fmt == "zarr":
        import zarr

        store = normalize_zarr_store(path, mode="r")
        if store is None:
            return None  # could not open zarr file
        with zarr.open_group(store, mode="r") as root:
            format_version = _find_version(root, label)
            if format_version is None and label != "data":
                format_version = _find_version(root, "data")
                if format_version is not None:
                    label = "data"

    else:
        return None

    if format_version in {0, None}:
        # load result written with format version 0
        from .version0 import result_from_file_v0

        return result_from_file_v0(path, model=model)

    elif format_version == 1:
        # load result written with format version 1
        from .version1 import result_from_file_v1

        return result_from_file_v1(path, label=label, model=model)

    elif not isinstance(format_version, int):
        raise RuntimeError(f"Unsupported format version {format_version}")

    return None

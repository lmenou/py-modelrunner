"""
Defines a class storing data in memory. 

.. codeauthor:: David Zwicker <david.zwicker@ds.mpg.de> 
"""

from __future__ import annotations

import copy
from typing import Any, Collection, Dict, Optional, Sequence, Tuple

import numpy as np
from numpy.typing import ArrayLike, DTypeLike

from ..access_modes import AccessError, ModeType
from ..attributes import Attrs
from ..base import StorageBase


class MemoryStorage(StorageBase):
    """store items in memory"""

    encode_internal_attrs: bool = False
    """bool: Flag determining whether flags used by this class internally are encoded as
    a string. This can be important if the data is stored to a file later"""

    _data: Attrs

    def __init__(self, *, mode: ModeType = "insert"):
        """
        Args:
            mode (str or :class:`~modelrunner.storage.access_modes.AccessMode`):
                The file mode with which the storage is accessed. Determines allowed
                operations.
        """
        super().__init__(mode=mode)
        self._data = {}

    def clear(self) -> None:
        """truncate the storage by removing all stored data.

        Args:
            clear_data_shape (bool):
                Flag determining whether the data shape is also deleted.
        """
        self._data = {}

    def _get_parent(
        self, loc: Sequence[str], *, check_write: bool = False
    ) -> Tuple[Dict, str]:
        """get the parent group for a particular location

        Args:
            loc (list of str):
                The location in the storage where the group will be created
            check_write (bool):
                Check whether the parent group is writable if `True`

        Returns:
            (group, str):
                A tuple consisting of the parent group and the name of the current item
        """
        value = self._data
        for part in loc[:-1]:
            try:
                value = value[part]
            except KeyError:
                if isinstance(value, dict):
                    value[part] = {}
                    value = value[part]
                else:
                    raise TypeError(f"Cannot add item to `/{'/'.join(loc)}`")
        if not isinstance(value, dict):
            raise TypeError(f"Cannot add item to `/{'/'.join(loc)}`")

        try:
            name = loc[-1]
        except IndexError:
            raise KeyError(f"Location `/{'/'.join(loc)}` has no parent")

        if check_write and not self.mode.overwrite and name in value:
            raise AccessError(f"Overwriting `/{'/'.join(loc)}` disabled")
        return value, name

    def __getitem__(self, loc: Sequence[str]) -> Any:
        if loc:
            parent, name = self._get_parent(loc)
            return parent[name]
        else:
            return self._data

    def keys(self, loc: Sequence[str]) -> Collection[str]:
        keys = self[loc].keys() if loc else self._data.keys()
        return [k for k in keys if not k.startswith("__")]

    def is_group(self, loc: Sequence[str]) -> bool:
        item = self[loc]
        if isinstance(item, dict):
            # dictionaries are usually groups, unless they have the `__type__` attribute
            return "__type__" not in item.get("__attrs__", {})
        else:
            return False  # no group, since it's not a dictionary

    def _create_group(self, loc: Sequence[str]) -> None:
        parent, name = self._get_parent(loc, check_write=True)
        parent[name] = {}

    def _read_attrs(self, loc: Sequence[str]) -> Attrs:
        res = self[loc].get("__attrs__", {})
        if isinstance(res, dict):
            return res
        else:
            raise RuntimeError(f"No attributes at `/{'/'.join(loc)}`")

    def _write_attr(self, loc: Sequence[str], name: str, value: str) -> None:
        item = self[loc]
        if "__attrs__" not in item:
            item["__attrs__"] = {name: value}
        else:
            item["__attrs__"][name] = value

    def _read_array(
        self, loc: Sequence[str], *, index: Optional[int] = None
    ) -> np.ndarray:
        # read the data from the location
        if index is None:
            return self[loc]["data"]  # type: ignore
        else:
            return self[loc]["data"][index]  # type: ignore

    def _write_array(self, loc: Sequence[str], arr: np.ndarray) -> None:
        parent, name = self._get_parent(loc, check_write=True)
        parent[name] = {"data": np.copy(arr)}

    def _create_dynamic_array(
        self,
        loc: Sequence[str],
        shape: Tuple[int, ...],
        dtype: DTypeLike,
        *,
        record_array: bool = False,
    ) -> None:
        parent, name = self._get_parent(loc, check_write=True)
        if name in parent:
            raise RuntimeError(f"Array `/{'/'.join(loc)}` already exists")
        parent[name] = {
            "data": [],
            "shape": tuple(shape),
            "dtype": np.dtype(dtype),
        }
        if record_array:
            parent[name]["record_array"] = True

    def _extend_dynamic_array(self, loc: Sequence[str], arr: ArrayLike) -> None:
        item = self[loc]

        # check data shape that is stored at this position
        data = np.asanyarray(arr)
        stored_shape = item["shape"]
        if stored_shape != data.shape:
            raise TypeError(f"Shape mismatch ({stored_shape} != {data.shape})")

        # convert the data to the correct format
        stored_dtype = item["dtype"]
        if not np.issubdtype(data.dtype, stored_dtype):
            raise TypeError(f"Dtype mismatch ({data.dtype} != {stored_dtype}")

        # append the data to the dynamic array
        if data.ndim == 0:
            item["data"].append(data.item())
        else:
            item["data"].append(np.array(data, copy=True))

    def _read_object(self, loc: Sequence[str]) -> Any:
        return self[loc]["data"]

    def _write_object(self, loc: Sequence[str], obj: Any) -> None:
        parent, name = self._get_parent(loc, check_write=True)
        parent[name] = {"data": copy.deepcopy(obj)}

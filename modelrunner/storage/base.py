"""
Base classes for managing hierarchical storage in which data is stored

The storage classes provide low-level abstraction to store data in a hierarchical format
and should thus not be used directly. Instead, the user typically interacts with
:class:`~modelrunner.storage.group.StorageGroup` objects, i.e., returned by
:func:`~modelrunner.storage.tools.open_storage`.

The role of `StorageBase` is to ensure access rights and provide an interface that can
be specified easily by subclasses to provide new storage formats. In contrast, the
interface of `StorageGroup` is more user-friendly and provides additional convenience
methods.

The main structure of the storage is a hierarchical tree of *groups*, which can contain
other groups or specific data items. Currently, items can be either arrays or arbitrary
objects, which are serialized transparently. Moreover, each group and each item can have
attributes, which are a mapping with string keys and arbitrary values, which are also
serialized transparently. Note that keys with double underscores are reserved for
internal use and should thus not be used.

.. codeauthor:: David Zwicker <david.zwicker@ds.mpg.de> 
"""

from __future__ import annotations

import logging
from abc import ABCMeta, abstractmethod
from typing import (
    TYPE_CHECKING,
    Any,
    Collection,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Type,
)

import numcodecs
import numpy as np
from numpy.typing import ArrayLike, DTypeLike

from .access_modes import AccessError, AccessMode, ModeType
from .attributes import Attrs, AttrsLike, decode_attrs, encode_attr
from .utils import encode_class

if TYPE_CHECKING:
    from .group import StorageGroup  # @UnusedImport


class StorageBase(metaclass=ABCMeta):
    """base class for storing data"""

    extensions: List[str] = []
    """list of str: all file extensions supported by this storage"""
    default_codec = numcodecs.Pickle()
    """:class:`numcodecs.Codec`: the default codec used for encoding binary data"""

    _codec: numcodecs.abc.Codec
    """:class:`numcodecs.Codec`: the specific codec used for encoding binary data"""

    def __init__(self, *, mode: ModeType = "read"):
        """
        Args:
            mode (str or :class:`~modelrunner.storage.access_modes.AccessMode`):
                The file mode with which the storage is accessed. Determines allowed
                operations.
        """
        self.mode = AccessMode.parse(mode)
        self._logger = logging.getLogger(self.__class__.__name__)

    def close(self) -> None:
        """closes the storage, potentially writing data to a persistent place"""
        ...

    @property
    def can_update(self) -> bool:
        """bool: indicates whether the storage supports updating items"""
        # we are using a property instead of an attribute to make this read-only
        return True

    @property
    def codec(self) -> numcodecs.abc.Codec:
        """:class:`~numcodecs.abc.Codec`: A codec used to encode binary data"""
        try:
            return self._codec
        except AttributeError:
            attrs = self._read_attrs([])
            if "__codec__" in attrs:
                self._codec = numcodecs.get_codec(attrs["__codec__"])
            else:
                self._codec = self.default_codec
                if self.mode.set_attrs:
                    self._write_attr([], "__codec__", self._codec.get_config())
        return self._codec

    @abstractmethod
    def keys(self, loc: Sequence[str]) -> Collection[str]:
        """return all sub-items defined at a given location

        Args:
            loc (sequence of str):
                A list of strings determining the location in the storage

        Returns:
            list: a list of all items defined at this location
        """

    def __contains__(self, loc: Sequence[str]):
        if not loc:
            return True  # the root is always contained in the storage
        try:
            return loc[-1] in self.keys(loc[:-1])
        except KeyError:
            return False

    @abstractmethod
    def is_group(self, loc: Sequence[str]) -> bool:
        """determine whether the location is a group

        Args:
            loc (sequence of str):
                A list of strings determining the location in the storage

        Returns:
            bool: `True` if the loation is a group
        """

    @abstractmethod
    def _create_group(self, loc: Sequence[str]) -> None:
        """create a group at a particular location

        Args:
            loc (sequence of str):
                A list of strings determining the location in the storage
        """

    def create_group(
        self,
        loc: Sequence[str],
        *,
        attrs: Optional[Attrs] = None,
        cls: Optional[Type] = None,
    ) -> "StorageGroup":
        """create a new group at a particular location

        Args:
            loc (list of str):
                The location in the storage where the group will be created
            attrs (dict, optional):
                Attributes stored with the group
            cls (type):
                A class associated with this group. The class will be used to re-create
                the object when this group is later accessed directly.

        Returns:
            :class:`StorageGroup`: The reference of the new group
        """
        from .group import StorageGroup  # @Reimport to avoid circular import

        if loc in self:
            # group already exists
            if self.mode.overwrite:
                pass  # group already exists, but we can overwrite things
            else:
                # we cannot overwrite anything
                raise AccessError(f"Group `/{'/'.join(loc)}` already exists")

        else:
            # group needs to be created
            if not self.mode.insert:
                raise AccessError(f"No right to insert group `/{'/'.join(loc)}`")

            # create all parent groups
            for i in range(len(loc)):
                if loc[: i + 1] not in self:
                    self._create_group(loc[: i + 1])

        self._write_item_attrs(loc, attrs, cls=cls)
        return StorageGroup(self, loc)

    def ensure_group(self, loc: Sequence[str]) -> None:
        """ensures the a group exists in the storage

        If the group is not already in the storage, it is created (recursively).

        Args:
            loc (list of str):
                The group location in the storage
        """
        if loc not in self:
            # check whether we can insert a group
            if not self.mode.insert:
                raise AccessError(f"No right to insert group `/{'/'.join(loc)}`")
            # create group
            self.create_group(loc)

    @abstractmethod
    def _read_attrs(self, loc: Sequence[str]) -> AttrsLike:
        """read attributes at a particular location

        Args:
            loc (sequence of str):
                A list of strings determining the location in the storage
        """

    def read_attrs(self, loc: Sequence[str]) -> Attrs:
        """read attributes associated with a particular location

        Args:
            loc (list of str):
                The location in the storage where the attributes are read

        Returns:
            dict: A copy of the attributes at this location
        """
        if not self.mode.read:
            raise AccessError("No right to read attributes")
        attrs = {
            k: v for k, v in self._read_attrs(loc).items() if not k.startswith("__")
        }
        return decode_attrs(attrs)

    @abstractmethod
    def _write_attr(self, loc: Sequence[str], name: str, value: str) -> None:
        """write a single attribute to a particular location

        Args:
            loc (list of str):
                The location in the storage where the attributes are written
            name (str):
                Name of the attribute
            value (str):
                Value of the attribute
        """

    def write_attrs(self, loc: Sequence[str], attrs: Optional[Attrs]) -> None:
        """write attributes to a particular location

        Args:
            loc (list of str):
                The location in the storage where the attributes are written
            attrs (dict):
                The attributes to be added to this location
        """
        # check whether we can insert anything
        if not self.mode.set_attrs:
            raise AccessError(f"No right to set attributes of `/{'/'.join(loc)}`")
        # check whether there are actually any attributes to be written
        if attrs is None or len(attrs) == 0:
            return

        for name, value in attrs.items():
            if name.startswith("__"):
                # do not encode internal attributes
                self._write_attr(loc, name, value)
            else:
                # serialize and encode all foreign attributes
                self._write_attr(loc, name, encode_attr(value))

    def _write_item_attrs(
        self,
        loc: Sequence[str],
        attrs: Optional[Attrs],
        *,
        item_type: Optional[Literal["array", "dynamic_array", "object"]] = None,
        cls: Optional[Type] = None,
    ) -> None:
        """write attributes to a particular location

        Args:
            loc (list of str):
                The location in the storage where the attributes are written
            attrs (dict):
                The attributes to be added to this location
            item_type (str):
                Information about the type of the item
            cls (type):
                Class information that needs to be stored alongside
        """
        if attrs is None:
            attrs = {}
        if item_type is not None:
            attrs.setdefault("__type__", str(item_type))
        if cls is not None:
            attrs.setdefault("__class__", encode_class(cls))
        self.write_attrs(loc, attrs)

    def _check_write_access(self, loc: Sequence[str], *, name: str = "item") -> None:
        """check whether we can safely write to a location

        Args:
            loc (list of str):
                The location in the storage where the array is read
            name (str):
                A name of the item appearing in error messages
        """
        if not loc:
            raise RuntimeError(f"Cannot write {name} to the storage root")
        elif loc in self:
            # check whether we can overwrite the existing array
            if not self.can_update:
                raise RuntimeError("Storage does not support updating items")
            if not self.mode.overwrite:
                raise AccessError(f"{name} `/{'/'.join(loc)}` already exists")
        else:
            # check whether we can insert a new array
            if not self.mode.insert:
                raise AccessError(f"No right to insert {name} at `/{'/'.join(loc)}`")
            # make sure the parent group exists
            self.ensure_group(loc[:-1])

    def _read_array(
        self,
        loc: Sequence[str],
        *,
        index: Optional[int] = None,
    ) -> ArrayLike:
        raise NotImplementedError(f"Cannot read arrays from {self.__class__.__name__}")

    def read_array(
        self,
        loc: Sequence[str],
        *,
        out: Optional[np.ndarray] = None,
        index: Optional[int] = None,
        copy: bool = True,
    ) -> np.ndarray:
        """read an array from a particular location

        Args:
            loc (list of str):
                The location in the storage where the array is created
            out (array):
                An array to which the results are written
            index (int, optional):
                An index denoting the subarray that will be read
            copy (bool):
                Determines whether a copy of the data is returned. Set this flag to
                `False` for better performance in cases where the array is not modified.

        Returns:
            :class:`~numpy.ndarray`:
                An array containing the data. Identical to `out` if specified.
        """
        if not self.mode.read:
            raise AccessError("No right to read array")

        if out is not None:
            out[:] = self._read_array(loc, index=index)
        elif copy:
            out = np.array(self._read_array(loc, index=index), copy=True)
        else:
            out = np.asanyarray(self._read_array(loc, index=index))
        return out

    def _write_array(self, loc: Sequence[str], arr: np.ndarray) -> None:
        raise NotImplementedError(f"Cannot write arrays in {self.__class__.__name__}")

    def write_array(
        self,
        loc: Sequence[str],
        arr: np.ndarray,
        *,
        attrs: Optional[Attrs] = None,
        cls: Optional[Type] = None,
    ) -> None:
        """write an array to a particular location

        Args:
            loc (list of str):
                The location in the storage where the array is read
            arr (:class:`~numpy.ndarray`):
                The array that will be written
            attrs (dict, optional):
                Attributes stored with the array
            cls (type):
                A class associated with this array. The class will be used to re-create
                the object when this array is later accessed. If no class is supplied,
                a generic `~modelrunner.storage.utils.Array` will be returned.
        """
        self._check_write_access(loc, name="array")
        self._write_array(loc, arr)
        self._write_item_attrs(loc, attrs, cls=cls, item_type="array")

    def _create_dynamic_array(
        self,
        loc: Sequence[str],
        shape: Tuple[int, ...],
        *,
        dtype: DTypeLike,
        record_array: bool = False,
    ) -> None:
        raise NotImplementedError(f"No dynamic arrays for {self.__class__.__name__}")

    def create_dynamic_array(
        self,
        loc: Sequence[str],
        shape: Tuple[int, ...],
        *,
        dtype: DTypeLike = float,
        record_array: bool = False,
        attrs: Optional[Attrs] = None,
        cls: Optional[Type] = None,
    ) -> None:
        """creates a dynamic array of flexible size

        Args:
            loc (list of str):
                The location in the storage where the dynamic array is created
            shape (tuple of int):
                The shape of the individual arrays. A singular axis is prepended to the
                shape, which can then be extended subsequently.
            dtype:
                The data type of the array to be written
            record_array (bool):
                Flag indicating whether the array is of type :class:`~numpy.recarray`
            attrs (dict, optional):
                Attributes stored with the array
            cls (type):
                A class associated with this array
        """
        self._check_write_access(loc, name="array")
        self._create_dynamic_array(
            loc, tuple(shape), dtype=dtype, record_array=record_array
        )
        self._write_item_attrs(loc, attrs, cls=cls, item_type="dynamic_array")

    def _extend_dynamic_array(self, loc: Sequence[str], arr: ArrayLike) -> None:
        raise NotImplementedError(f"No dynamic arrays for {self.__class__.__name__}")

    def extend_dynamic_array(self, loc: Sequence[str], arr: ArrayLike) -> None:
        """extend a dynamic array previously created

        Args:
            loc (list of str):
                The location in the storage where the dynamic array is located
            arr (array):
                The array that will be appended to the dynamic array
        """
        if not self.mode.dynamic_append:
            raise AccessError(f"Cannot append data to dynamic array `/{'/'.join(loc)}`")
        if self._read_attrs(loc).get("__type__") != "dynamic_array":
            raise RuntimeError(f"Cannot extend array at `/{'/'.join(loc)}`")
        self._extend_dynamic_array(loc, arr)

    def _read_object(self, loc: Sequence[str]) -> Any:
        raise NotImplementedError(f"Cannot read objects from {self.__class__.__name__}")

    def read_object(self, loc: Sequence[str]) -> Any:
        """read an object from a particular location

        Args:
            loc (list of str):
                The location in the storage where the object is created

        Returns:
            The object that has been read from the storage
        """
        if not self.mode.read:
            raise AccessError("No right to read object")
        if self._read_attrs(loc).get("__type__") != "object":
            raise RuntimeError(f"No object stored at `/{'/'.join(loc)}`")
        return self._read_object(loc)

    def _write_object(self, loc: Sequence[str], obj: Any) -> None:
        raise NotImplementedError(f"Cannot write objects in {self.__class__.__name__}")

    def write_object(
        self,
        loc: Sequence[str],
        obj: Any,
        *,
        attrs: Optional[Attrs] = None,
        cls: Optional[Type] = None,
    ) -> None:
        """write an object to a particular location

        Args:
            loc (list of str):
                The location in the storage where the object is read.
            obj:
                The object that will be written
            attrs (dict, optional):
                Attributes stored with the object
            cls (type):
                A class associated with this object. The class will be used to re-create
                the object when this object is later accessed. If no class is supplied,
                a generic python object will be returned.
        """
        self._check_write_access(loc, name="object")
        self._write_object(loc, obj)
        self._write_item_attrs(loc, attrs, cls=cls, item_type="object")

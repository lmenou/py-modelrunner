"""
Base classes for storing data

.. codeauthor:: David Zwicker <david.zwicker@ds.mpg.de> 
"""

from __future__ import annotations

import logging
from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Collection, List, Optional, Sequence, Tuple, Type

import numcodecs
import numpy as np
from numpy.typing import ArrayLike, DTypeLike

from .access_modes import AccessError, AccessMode, ModeType
from .attributes import Attrs, AttrsLike, decode_attrs, encode_attr
from .utils import encode_class

if TYPE_CHECKING:
    from .group import StorageGroup  # @UnusedImport


class StorageBase(metaclass=ABCMeta):
    """base class for storing data

    The storage classes should usually not be used directly. Instead, the user
    typically interacts with :class:`~modelrunner.storage.group.StorageGroup` objects,
    i.e., returned by :func:`~modelrunner.storage.tools.open_storage`.

    The role of `StorageBase` is to ensure access rights and provide an interface that
    can be specified easily by subclasses to provide new storage formats. In contrast,
    the interface of `StorageGroup` is more user-friendly and provides additional
    convenience methods.
    """

    extensions: List[str] = []
    """list of str: all file extensions supported by this storage"""
    default_codec = numcodecs.Pickle()
    """:class:`numcodecs.Codec`: the default codec used for encoding binary data"""

    _codec: numcodecs.abc.Codec
    """:class:`numcodecs.Codec`: the specific codec used for encoding binary data"""

    def __init__(self, *, mode: ModeType = "readonly"):
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
                self._write_attr([], "__codec__", self._codec.get_config())
        return self._codec

    def _get_attrs(
        self, attrs: Optional[Attrs], *, cls: Optional[Type] = None
    ) -> Attrs:
        """create attributes dictionary

        Args:
            attrs (dict):
                Dictionary with arbitrary attributes
            cls (type):
                Class information that needs to be stored alongside
        """
        if attrs is None:
            attrs = {}
        else:
            attrs = dict(attrs)
        if cls is not None:
            attrs["__class__"] = encode_class(cls)
        return attrs

    @abstractmethod
    def keys(self, loc: Sequence[str]) -> Collection[str]:
        """return all sub-items defined at a given location

        Args:
            loc (sequence of str):
                A list of strings determining the location in the storage

        Returns:
            list: a list of all items defined at this location
        """
        ...

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
        ...

    @abstractmethod
    def _create_group(self, loc: Sequence[str]) -> None:
        ...

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
                A class associated with this group

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
                raise AccessError(f"Group `{'/'.join(loc)}` already exists")

        else:
            # group needs to be created
            if not self.mode.insert:
                raise AccessError(f"No right to insert group `{'/'.join(loc)}`")

            # create all parent groups
            for i in range(len(loc)):
                if loc[: i + 1] not in self:
                    self._create_group(loc[: i + 1])

        self.write_attrs(loc, self._get_attrs(attrs, cls=cls))
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
                raise AccessError(f"No right to insert group `{'/'.join(loc)}`")
            # create group
            self.create_group(loc)

    @abstractmethod
    def _read_attrs(self, loc: Sequence[str]) -> AttrsLike:
        ...

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
        attrs = self._read_attrs(loc)
        return decode_attrs(attrs)

    @abstractmethod
    def _write_attr(self, loc: Sequence[str], name: str, value) -> None:
        """write a single attribute to a particular location"""
        ...

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
            raise AccessError(f"No right to set attributes of `{'/'.join(loc)}`")
        # check whether there are actually any attributes to be written
        if attrs is None or len(attrs) == 0:
            return

        self.ensure_group(loc)  # make sure the group exists

        for name, value in attrs.items():
            self._write_attr(loc, name, encode_attr(value))

    @abstractmethod
    def _read_array(
        self,
        loc: Sequence[str],
        *,
        index: Optional[int] = None,
    ) -> ArrayLike:
        ...

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

    @abstractmethod
    def _write_array(self, loc: Sequence[str], arr: np.ndarray) -> None:
        ...

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
                A class associated with this array
        """
        if not loc:
            raise RuntimeError(f"Cannot write an array to the storage root")
        elif loc in self:
            # check whether we can overwrite the existing array
            if not self.mode.overwrite:
                raise AccessError(f"Array `{'/'.join(loc)}` already exists")
        else:
            # check whether we can insert a new array
            if not self.mode.insert:
                raise AccessError(f"No right to insert array `{'/'.join(loc)}`")
            # make sure the parent group exists
            self.ensure_group(loc[:-1])

        self._write_array(loc, arr)
        self.write_attrs(loc, self._get_attrs(attrs, cls=cls))

    @abstractmethod
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
        if not loc:
            raise RuntimeError(f"Cannot write an array to the storage root")
        elif loc in self:
            # check whether we can overwrite the existing array
            if not self.mode.overwrite:
                raise RuntimeError(f"Array `{'/'.join(loc)}` already exists")
            # TODO: Do we need to clear this array?
        else:
            # check whether we can insert a new array
            if not self.mode.insert:
                raise AccessError(f"No right to insert array `{'/'.join(loc)}`")
            self.ensure_group(loc[:-1])  # make sure the parent group exists

        self._create_dynamic_array(
            loc, tuple(shape), dtype=dtype, record_array=record_array
        )
        self.write_attrs(loc, self._get_attrs(attrs, cls=cls))

    @abstractmethod
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
            raise AccessError(f"Cannot append data to dynamic array `{'/'.join(loc)}`")
        self._extend_dynamic_array(loc, arr)

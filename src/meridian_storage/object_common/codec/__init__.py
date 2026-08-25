# SPDX-License-Identifier: Apache-2.0
"""Portable digest and logical-reference codecs."""

from .digest import Sha256Accumulator
from .signed import (
    SIGNED_REFERENCE_FORMAT_VERSION,
    SIGNED_REFERENCE_OPERATIONS,
    HmacSha256Key,
    ReferenceSigner,
    SignedObjectReference,
    parse_logical_reference,
    sign_object_reference,
)

__all__ = [
    "SIGNED_REFERENCE_FORMAT_VERSION",
    "SIGNED_REFERENCE_OPERATIONS",
    "HmacSha256Key",
    "ReferenceSigner",
    "Sha256Accumulator",
    "SignedObjectReference",
    "parse_logical_reference",
    "sign_object_reference",
]

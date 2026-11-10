"""Minisign reference vectors and tampering checks, without network access.

Vectors: https://github.com/jedisct1/rust-minisign-verify (version 0.2.5).
"""

import base64
import unittest

from verify_release import verify_signature


PUBLIC = base64.b64decode("RWQf6LRCGA9i53mlYecO4IzT51TGPpvWucNSCh1CBM0QTaLn73Y7GFO3")
LEGACY = """untrusted comment: signature from minisign secret key
RWQf6LRCGA9i59SLOFxz6NxvASXDJeRtuZykwQepbDEGt87ig1BNpWaVWuNrm73YiIiJbq71Wi+dP9eKL8OC351vwIasSSbXxwA=
trusted comment: timestamp:1555779966\tfile:test
QtKMXWyYcwdpZAlPF7tE2ENJkRd1ujvKjlj1m9RtHTBnZPa5WKU5uWRs5GoP5M/VqE81QFuMKI5k/SfNQUaOAA=="""
PREHASHED = """untrusted comment: signature from minisign secret key
RUQf6LRCGA9i559r3g7V1qNyJDApGip8MfqcadIgT9CuhV3EMhHoN1mGTkUidF/z7SrlQgXdy8ofjb7bNJJylDOocrCo8KLzZwo=
trusted comment: timestamp:1556193335\tfile:test
y/rUw2y8/hOUYjZU71eHp/Wo1KZ40fGy2VJEDl34XMJM+TX48Ss/17u3IvIfbVR1FkZZSNCisQbuQY+bHwhEBg=="""


class SignatureTests(unittest.TestCase):
    def test_reference_signatures_and_tauri_base64_encoding(self):
        for signature in (LEGACY, PREHASHED):
            with self.subTest(algorithm=signature.splitlines()[1][:4]):
                verify_signature(b"test", signature, PUBLIC)
                verify_signature(b"test", base64.b64encode(signature.encode()).decode(), PUBLIC)

    def test_modified_artifact_is_rejected(self):
        for signature in (LEGACY, PREHASHED):
            with self.subTest(algorithm=signature.splitlines()[1][:4]):
                with self.assertRaisesRegex(ValueError, "signature verification failed"):
                    verify_signature(b"Test", signature, PUBLIC)

    def test_modified_trusted_comment_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            verify_signature(b"test", PREHASHED.replace("1556193335", "1556193336"), PUBLIC)

    def test_wrong_key_id_is_rejected(self):
        other_id = PUBLIC[:2] + bytes([PUBLIC[2] ^ 1]) + PUBLIC[3:]
        with self.assertRaisesRegex(ValueError, "key ID mismatch"):
            verify_signature(b"test", PREHASHED, other_id)


if __name__ == "__main__":
    unittest.main()

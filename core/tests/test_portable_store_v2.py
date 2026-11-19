"""Fork (Scotty): version 2 portable vaults use the stronger Argon2id cost; version 1 vaults still
open with their own cost and are rewritten as version 2. Costs are cut to Argon2id's minimum here
(two different minimums, so a key derived at the wrong version cannot decrypt) to keep tests fast."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from nacl.pwhash import argon2id
from nacl.secret import SecretBox
from nacl.utils import random

from core import portable_store
from core.portable_store import PortableStore, PortableStoreUnlockError

FAST = dict(KDF_OPSLIMIT_V1=argon2id.OPSLIMIT_MIN, KDF_MEMLIMIT_V1=argon2id.MEMLIMIT_MIN,
            KDF_OPSLIMIT=argon2id.OPSLIMIT_MIN + 1, KDF_MEMLIMIT=argon2id.MEMLIMIT_MIN * 2)


def version_1_vault(path, passphrase, data=b'{"pairing":"keys"}'):
    salt = random(argon2id.SALTBYTES)
    key = argon2id.kdf(SecretBox.KEY_SIZE, passphrase.encode(), salt,
                       opslimit=portable_store.KDF_OPSLIMIT_V1, memlimit=portable_store.KDF_MEMLIMIT_V1)
    with open(path, "wb") as out:
        out.write(portable_store._MAGIC_V1 + salt + bytes(SecretBox(key).encrypt(data)))


class VaultVersionTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.multiple(portable_store, **FAST)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = tempfile.mkdtemp(prefix="scotty-vault-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "settings.vault")

    def header(self):
        with open(self.path, "rb") as source:
            return source.read(len(portable_store._MAGIC))

    def test_a_new_vault_is_version_2(self):
        PortableStore(self.path).unlock("correct horse battery")
        self.assertEqual(self.header(), portable_store._MAGIC)

    def test_a_version_1_vault_opens_and_is_upgraded_in_place(self):
        version_1_vault(self.path, "correct horse battery")
        store = PortableStore(self.path)
        store.unlock("correct horse battery")
        self.assertEqual(store.read(), {"pairing": "keys"})
        self.assertEqual(self.header(), portable_store._MAGIC)
        again = PortableStore(self.path)
        again.unlock("correct horse battery")
        self.assertEqual(again.read(), {"pairing": "keys"})

    def test_a_wrong_passphrase_leaves_a_version_1_vault_untouched(self):
        version_1_vault(self.path, "correct horse battery")
        with open(self.path, "rb") as source:
            before = source.read()
        with self.assertRaises(PortableStoreUnlockError):
            PortableStore(self.path).unlock("wrong passphrase!!")
        with open(self.path, "rb") as source:
            self.assertEqual(source.read(), before)

    def test_a_version_1_vault_that_cannot_be_rewritten_still_opens(self):
        version_1_vault(self.path, "correct horse battery")
        store = PortableStore(self.path)
        with mock.patch.object(PortableStore, "_save", side_effect=PermissionError("read-only")):
            store.unlock("correct horse battery")
        self.assertEqual(store.read(), {"pairing": "keys"})
        store.write({"pairing": "keys", "more": 1})
        self.assertEqual(self.header(), portable_store._MAGIC)

    def test_the_version_not_the_file_decides_the_cost(self):
        # A version 2 header on data keyed at version 1's cheaper cost does not open: nothing in a
        # crafted file can lower the work an attacker's guesses take.
        version_1_vault(self.path, "correct horse battery")
        with open(self.path, "r+b") as vault:
            vault.write(portable_store._MAGIC)
        with self.assertRaises(PortableStoreUnlockError):
            PortableStore(self.path).unlock("correct horse battery")

    def test_shipping_costs_are_the_stronger_ones(self):
        self.assertEqual(FAST["KDF_OPSLIMIT"], portable_store.KDF_OPSLIMIT)
        mock.patch.stopall()
        self.assertEqual(portable_store.KDF_OPSLIMIT, argon2id.OPSLIMIT_MODERATE)
        self.assertEqual(portable_store.KDF_MEMLIMIT, argon2id.MEMLIMIT_MODERATE)


if __name__ == "__main__":
    unittest.main()
